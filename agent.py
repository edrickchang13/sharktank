

"""Shark Tank Vision Agents backend (P2).

Edge: tencent.Edge (Linux) or getstream.Edge fallback.
LLM: gemini.Realtime per judge -- voice + system instruction baked into config.
VAD: smart_turn.TurnDetection.
On each user turn: rotate judge, adapt prompt to mood, emit websocket msg,
upload audio to COS.
"""

import base64
import json
import os
import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from google.genai.types import (
    LiveConnectConfigDict,
    Modality,
    PrebuiltVoiceConfigDict,
    SpeechConfigDict,
    VoiceConfigDict,
)

# Optional VAD tuning types -- newer google-genai exposes these for tightening
# silence detection. If unavailable, we fall back to library defaults (slow).
try:
    from google.genai.types import (
        AutomaticActivityDetection,
        EndSensitivity,
        RealtimeInputConfig,
        StartSensitivity,
    )
    _FAST_VAD = RealtimeInputConfig(
        automatic_activity_detection=AutomaticActivityDetection(
            start_of_speech_sensitivity=StartSensitivity.START_SENSITIVITY_HIGH,
            end_of_speech_sensitivity=EndSensitivity.END_SENSITIVITY_HIGH,
            silence_duration_ms=300,
            prefix_padding_ms=50,
        )
    )
except Exception:
    _FAST_VAD = None

load_dotenv()

from vision_agents.core import Agent, User
from vision_agents.core.llm.events import (
    RealtimeAgentSpeechTranscriptionEvent,
    RealtimeAudioOutputDoneEvent,
    RealtimeAudioOutputEvent,
    RealtimeUserSpeechTranscriptionEvent,
)
from vision_agents.plugins import gemini, getstream, smart_turn
import cos
import judges
import trtc as trtc_mod

try:
    from vision_agents.plugins import tencent as _tencent_mod
    _TENCENT_AVAILABLE = True
except ImportError:
    _TENCENT_AVAILABLE = False

_JUDGES_EXPORT: dict[str, Any] = json.loads(
    (Path(__file__).parent / "judges_export.json").read_text()
)["judges"]

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
)

# ---------------------------------------------------------------------------
# WebSocket broadcast hook (registered by main.py)
# ---------------------------------------------------------------------------

_broadcast_fn: Optional[Callable] = None
_session_fn: Optional[Callable] = None


def set_broadcast(fn: Callable) -> None:
    global _broadcast_fn
    _broadcast_fn = fn


def set_session_hook(fn: Callable) -> None:
    """main.py registers a callback to receive the live Session for mood writes."""
    global _session_fn
    _session_fn = fn


async def _emit_to_p3(payload: dict) -> None:
    print(f"[ws -> P3] {payload}", flush=True)
    if _broadcast_fn:
        try:
            await _broadcast_fn(payload)
        except Exception as e:
            print(f"[ws error] {e}", flush=True)


# ---------------------------------------------------------------------------
# Mood: webcam snapshot -> Gemini vision score (runs in thread pool)
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=1)


def _get_mood_sync() -> float:
    """Mood now arrives from the browser via main.py WS; cv2 path disabled.

    The real signal is set from main.py's WebSocket frame handler which calls
    Gemini Vision on uploaded JPEGs and writes to ``session.mood`` directly.
    """
    return 0.5


async def _mood_loop(session: "Session") -> None:
    """Background task: update session.mood every ~3s without blocking the event loop."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(3)
        try:
            session.mood = await loop.run_in_executor(_executor, _get_mood_sync)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[mood] {e}", flush=True)


# ---------------------------------------------------------------------------
# Per-judge LLM factory
# ---------------------------------------------------------------------------

def make_llm_for_judge(judge_key: str, mood: float) -> gemini.Realtime:
    voice = _JUDGES_EXPORT[judge_key]["gemini_voice"]
    system_instruction = judges.render_system_prompt(judge_key, mood)
    config_kwargs: dict[str, Any] = dict(
        response_modalities=[Modality.AUDIO],
        speech_config=SpeechConfigDict(
            voice_config=VoiceConfigDict(
                prebuilt_voice_config=PrebuiltVoiceConfigDict(voice_name=voice)
            ),
            language_code="en-US",
        ),
        system_instruction=system_instruction,
        output_audio_transcription={},
        input_audio_transcription={},
    )
    # Tighten Gemini's silence-to-turn-end window when the model supports it.
    # Default is ~800-1000ms; 300ms makes the judge feel real-time.
    if _FAST_VAD is not None:
        config_kwargs["realtime_input_config"] = _FAST_VAD

    return gemini.Realtime(
        model=GEMINI_MODEL,
        config=LiveConnectConfigDict(**config_kwargs),
        # fps=1 instead of 3: still enough for facial-mood and gesture reads
        # at hackathon scale, frees compute and bandwidth so audio response
        # comes back faster.
        fps=1,
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    turn_index: int = 0
    current_judge_key: str = "cuban"
    mood: float = 0.5
    transcript_history: list[dict[str, Any]] = field(default_factory=list)
    _start_ts: float = field(default_factory=time.monotonic, repr=False)

    def record(self, transcript: str, judge_key: str, latency_ms: int) -> None:
        self.transcript_history.append({
            "turn_idx": self.turn_index,
            "transcript": transcript,
            "judge": judge_key,
            "mood": self.mood,
            "latency_ms": latency_ms,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "turns": self.transcript_history,
            "total_latency_ms": int((time.monotonic() - self._start_ts) * 1000),
        }


# ---------------------------------------------------------------------------
# Edge selection
# ---------------------------------------------------------------------------

def build_edge():
    trtc_app_id = os.environ.get("TRTC_SDK_APP_ID")
    trtc_secret = os.environ.get("TRTC_SECRET_KEY")

    if _TENCENT_AVAILABLE and trtc_app_id and trtc_secret:
        try:
            edge = _tencent_mod.Edge(sdk_app_id=int(trtc_app_id), key=trtc_secret)
            print("Edge: Tencent TRTC", flush=True)
            return edge
        except Exception as e:
            print(
                f"Tencent TRTC unavailable ({type(e).__name__}: {e}), "
                "falling back to GetStream",
                flush=True,
            )

    print("Edge: GetStream", flush=True)
    return getstream.Edge()


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

async def _cos_upload_audio(
    session_id: str, turn_idx: int, judge_key: str, audio_bytes: bytes
) -> None:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None, cos.upload_audio, session_id, turn_idx, judge_key, audio_bytes
        )
    except Exception as e:
        print(f"[cos] upload_audio failed: {e}", flush=True)


def build_agent(session: Session) -> Agent:
    initial_llm = make_llm_for_judge(session.current_judge_key, session.mood)

    # Drop smart_turn: gemini.Realtime owns VAD internally and silently
    # disables external turn detectors. Passing it adds a no-op plugin
    # init cost without affecting behavior. Removing tightens startup.
    agent = Agent(
        edge=build_edge(),
        agent_user=User(name="Shark Tank Judge", id="shark-tank-agent"),
        instructions="",
        llm=initial_llm,
    )

    _audio_buffer: list[bytes] = []

    @agent.subscribe
    async def on_user_turn_end(event: RealtimeUserSpeechTranscriptionEvent):
        start = time.monotonic()
        transcript = event.text or ""

        next_judge = judges.pick_next_judge(session.turn_index, session.mood)
        latency_ms = int((time.monotonic() - start) * 1000)

        print(
            f"\n[turn {session.turn_index}] judge={next_judge}  "
            f"mood={session.mood:.2f}  latency={latency_ms}ms",
            flush=True,
        )
        print(f"  transcript: {transcript!r}", flush=True)

        session.record(transcript, next_judge, latency_ms)

        if next_judge != session.current_judge_key:
            session.current_judge_key = next_judge
            agent.llm = make_llm_for_judge(next_judge, session.mood)
            print(f"  judge swapped -> {next_judge}", flush=True)

        session.turn_index += 1

        await _emit_to_p3({
            "type": "judge",
            "judge": next_judge,
            "mood": round(session.mood, 3),
            "turn_idx": session.turn_index,
        })

    @agent.subscribe
    async def on_audio_chunk(event: RealtimeAudioOutputEvent):
        if event.data is not None and event.data.samples is not None:
            raw = event.data.samples.tobytes()
            if raw:
                _audio_buffer.append(raw)

    @agent.subscribe
    async def on_audio_done(event: RealtimeAudioOutputDoneEvent):
        if event.interrupted or not _audio_buffer:
            _audio_buffer.clear()
            return
        audio_bytes = b"".join(_audio_buffer)
        _audio_buffer.clear()
        judge_key = session.current_judge_key
        turn_idx = max(0, session.turn_index - 1)
        asyncio.create_task(_cos_upload_audio(session.id, turn_idx, judge_key, audio_bytes))

    @agent.subscribe
    async def on_agent_speech(event: RealtimeAgentSpeechTranscriptionEvent):
        if event.mode == "final" and event.text:
            print(f"  [judge speech] {event.text!r}", flush=True)
            await _emit_to_p3({
                "type": "transcript",
                "judge": session.current_judge_key,
                "text": event.text,
                "mood": round(session.mood, 3),
                "turn_idx": session.turn_index,
            })

    return agent


# ---------------------------------------------------------------------------
# Join call via TRTC room
# ---------------------------------------------------------------------------

async def join_call(agent: Agent, session: Session) -> None:
    # Derive a uint32 numeric room ID from session hex ID (8 hex chars = 32 bits)
    room_id = int(session.id, 16)

    founder_user_id = "founder-" + uuid.uuid4().hex[:8]
    creds = trtc_mod.make_room_credentials(room_id=room_id, user_id=founder_user_id)

    print(f"\nSession ID:   {session.id}", flush=True)
    print(f"TRTC Room ID: {room_id}", flush=True)
    print(f"\nOpen the frontend:\n  http://localhost:8000/?room_id={room_id}\n", flush=True)

    await _emit_to_p3({
        "type": "room_ready",
        "room_id": room_id,
        "sdk_app_id": creds["sdk_app_id"],
        "user_id": creds["user_id"],
        "user_sig": creds["user_sig"],
    })

    # call_id as decimal string -> TencentEdge.create_call converts to int room_id
    call = await agent.create_call("default", str(room_id))

    print("Waiting for founder to join the TRTC room...\n", flush=True)
    async with agent.join(call, participant_wait_timeout=None):
        await agent.finish()

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, cos.upload_session, session.id, session.to_dict()
        )
        print(f"Session log uploaded for {session.id}", flush=True)
    except Exception as e:
        print(f"[cos] upload_session failed: {e}", flush=True)

    print(f"\nSession {session.id} complete. Turns: {session.turn_index}", flush=True)


# ---------------------------------------------------------------------------
# Entry point (called from main.py via run_agent, or directly)
# ---------------------------------------------------------------------------

async def run_agent() -> None:
    session = Session()
    if _session_fn is not None:
        try:
            _session_fn(session)
        except Exception as e:
            print(f"[session hook] {e}", flush=True)
    agent = build_agent(session)
    print(
        f"Agent ready -- judge={session.current_judge_key}  "
        f"voice={_JUDGES_EXPORT[session.current_judge_key]['gemini_voice']}",
        flush=True,
    )
    mood_task = asyncio.create_task(_mood_loop(session))
    try:
        await join_call(agent, session)
    finally:
        mood_task.cancel()
        try:
            await mood_task
        except asyncio.CancelledError:
            pass


async def run() -> None:
    await run_agent()


if __name__ == "__main__":
    asyncio.run(run())
