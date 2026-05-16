"""Shark Tank Vision Agents backend (P2).

Edge: tencent.Edge (Linux) or getstream.Edge fallback (macOS dev).
LLM: gemini.Realtime per judge -- voice + system instruction baked into config.
VAD: smart_turn.TurnDetection.
On each user turn: rotate judge, adapt prompt to mood, emit websocket msg,
upload audio to COS (stubbed until COS creds arrive).
"""

import json
import os
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dotenv import load_dotenv
from google.genai.types import (
    LiveConnectConfigDict,
    Modality,
    PrebuiltVoiceConfigDict,
    SpeechConfigDict,
    VoiceConfigDict,
)

load_dotenv()

from getstream import Stream as StreamClient
from vision_agents.core import Agent, User
from vision_agents.core.llm.events import RealtimeUserSpeechTranscriptionEvent
from vision_agents.plugins import gemini, getstream, smart_turn
import judges

# Tencent only ships manylinux wheels -- import is safe, construction raises on macOS
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
# Mood stub
# ---------------------------------------------------------------------------

def get_mood() -> float:
    """Latest mood snapshot. Replace with real webcam analysis (~3s)."""
    return 0.5


# ---------------------------------------------------------------------------
# Per-judge LLM factory
# ---------------------------------------------------------------------------

def make_llm_for_judge(judge_key: str, mood: float) -> gemini.Realtime:
    """Return a gemini.Realtime with the judge's voice and mood-adapted prompt."""
    voice = _JUDGES_EXPORT[judge_key]["gemini_voice"]
    system_instruction = judges.render_system_prompt(judge_key, mood)
    return gemini.Realtime(
        model=GEMINI_MODEL,
        config=LiveConnectConfigDict(
            response_modalities=[Modality.AUDIO],
            speech_config=SpeechConfigDict(
                voice_config=VoiceConfigDict(
                    prebuilt_voice_config=PrebuiltVoiceConfigDict(voice_name=voice)
                ),
                language_code="en-US",
            ),
            system_instruction=system_instruction,
        ),
        fps=3,
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
# COS stub (no-op until COS creds arrive from P1)
# ---------------------------------------------------------------------------

def _upload_audio_stub(session_id: str, turn_idx: int, judge_key: str,
                        audio_bytes: bytes) -> str:
    print(f"[cos stub] upload_audio session={session_id} turn={turn_idx} judge={judge_key} "
          f"bytes={len(audio_bytes)}", flush=True)
    return ""


def _upload_session_stub(session_id: str, data: dict) -> str:
    print(f"[cos stub] upload_session session={session_id} turns={len(data.get('turns', []))}",
          flush=True)
    return ""


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
        except RuntimeError as e:
            print(f"Tencent TRTC unavailable ({e}), falling back to GetStream", flush=True)

    print("Edge: GetStream", flush=True)
    return getstream.Edge()


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def build_agent(session: Session) -> Agent:
    initial_llm = make_llm_for_judge(session.current_judge_key, session.mood)

    agent = Agent(
        edge=build_edge(),
        agent_user=User(name="Shark Tank Judge", id="shark-tank-agent"),
        instructions="",  # system instruction lives inside each judge's LLM config
        llm=initial_llm,
        turn_detection=smart_turn.TurnDetection(),
    )

    @agent.subscribe
    async def on_turn_end(event: RealtimeUserSpeechTranscriptionEvent):
        start = time.monotonic()
        transcript = event.text or ""

        # Update mood snapshot
        session.mood = get_mood()

        # Pick next judge and rotate
        next_judge = judges.pick_next_judge(session.turn_index, session.mood)
        latency_ms = int((time.monotonic() - start) * 1000)

        print(
            f"\n[turn {session.turn_index}] judge={next_judge}  "
            f"mood={session.mood:.2f}  latency={latency_ms}ms",
            flush=True,
        )
        print(f"  transcript: {transcript!r}", flush=True)

        session.record(transcript, next_judge, latency_ms)

        # Swap judge LLM if judge changed
        if next_judge != session.current_judge_key:
            session.current_judge_key = next_judge
            new_llm = make_llm_for_judge(next_judge, session.mood)
            # Hot-swap: if Vision Agents supports it this takes effect next turn.
            # If not, plan B is rebuilding the agent -- acceptable 1-2s dead air.
            agent.llm = new_llm
            print(f"  judge swapped -> {next_judge}", flush=True)

        session.turn_index += 1

        # COS upload (stubbed until creds arrive)
        audio_bytes: bytes = b""  # P2: capture from agent audio output
        response_text: str = ""   # P2: capture from agent transcript event
        _upload_audio_stub(session.id, session.turn_index - 1, next_judge, audio_bytes)

        # Websocket emit to P3: {judge, text, audio}
        ws_payload = {"judge": next_judge, "text": response_text, "audio": audio_bytes}
        _emit_to_p3(ws_payload)

    return agent


def _emit_to_p3(payload: dict) -> None:
    """Send {judge, text, audio} to the P3 browser frontend over websocket.
    Stubbed -- P2 wires the real websocket server here."""
    print(f"[ws -> P3] judge={payload['judge']}  text={payload['text']!r}", flush=True)


# ---------------------------------------------------------------------------
# Join-call with REST polling (waits for a human before connecting the agent)
# ---------------------------------------------------------------------------

async def join_call(
    agent: Agent,
    session: Session,
    call_type: str = "default",
    call_id: str = "sharktank-dev",
) -> None:
    call = await agent.create_call(call_type, call_id)

    api_key = os.environ["STREAM_API_KEY"]
    api_secret = os.environ["STREAM_API_SECRET"]
    token = StreamClient(api_key=api_key, api_secret=api_secret).create_token("demo-user")
    url = (
        "https://getstream.io/video/demos/join/"
        + call.id
        + "?"
        + urlencode({
            "api_key": api_key,
            "token": token,
            "skip_lobby": "true",
            "user_name": "Founder",
        })
    )

    print(f"\n🔗 Open this URL in your browser:\n  {url}\n", flush=True)
    print(f"Session ID: {session.id}", flush=True)
    print("Polling for participant -- agent connects once you join...\n", flush=True)

    # Poll REST API until a human participant is present
    sync_call = StreamClient(api_key=api_key, api_secret=api_secret).video.call(call_type, call_id)
    while True:
        try:
            resp = sync_call.get()
            # resp.data.call.session.participants is the live list of active
            # WebRTC participants in the current session
            session_obj = getattr(resp.data.call, "session", None)
            participants = getattr(session_obj, "participants", []) or []
            human_participants = [
                p for p in participants
                if getattr(getattr(p, "user", None), "id", None) != "shark-tank-agent"
            ]
            if human_participants:
                names = [getattr(getattr(p, "user", None), "id", "?") for p in human_participants]
                print(f"[poll] human participants detected: {names}", flush=True)
                break
        except Exception as e:
            print(f"[poll] error: {e}", flush=True)
        await asyncio.sleep(2)

    print("Participant detected -- agent joining call...\n", flush=True)

    async with agent.join(call):
        await agent.finish()

    # Session end: upload full log (stubbed)
    _upload_session_stub(session.id, session.to_dict())
    print(f"\nSession {session.id} complete. Turns: {session.turn_index}", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run() -> None:
    session = Session()
    agent = build_agent(session)
    print(
        f"Agent ready -- judge={session.current_judge_key}  "
        f"voice={_JUDGES_EXPORT[session.current_judge_key]['gemini_voice']}",
        flush=True,
    )
    await join_call(agent, session)


if __name__ == "__main__":
    asyncio.run(run())
