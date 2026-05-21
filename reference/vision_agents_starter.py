"""Vision Agents starter for Shark Tank Simulator (reference starter).

Wired: tencent.Edge() primary with getstream.Edge() fallback, gemini.Realtime
with response_modalities=[AUDIO] and per-judge voice swap, judge prompts
from judges_export.json, judge rotation (cuban opens, low-mood -> corcoran,
else rotate), COS callbacks for per-turn audio + session JSON.

Owned by the Vision Agents backend: websocket transport to the browser
frontend, real mood processor (webcam, ~3s), agent.llm hot-swap or agent
reconstruction per judge change, Stream REST participant polling so the agent
joins only after the browser has joined.

Required env vars (from a secure channel, paste into .env):
  TRTC_SDK_APP_ID, TRTC_SECRET_KEY (Tencent transport, primary)
  STREAM_API_KEY, STREAM_API_SECRET (GetStream transport, fallback)
  GOOGLE_API_KEY (Gemini Live, sole LLM+TTS+VAD)
  GEMINI_MODEL (default below)
  TENCENT_SECRET_ID, TENCENT_SECRET_KEY, COS_BUCKET, COS_REGION (cos.py)
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.genai.types import (
    LiveConnectConfigDict,
    Modality,
    PrebuiltVoiceConfigDict,
    SpeechConfigDict,
    VoiceConfigDict,
)
from vision_agents import Agent
from vision_agents.plugins import gemini, getstream, tencent

load_dotenv()

JUDGES_EXPORT_PATH = Path(__file__).parent / "judges_export.json"
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
)


def load_judge_data() -> dict[str, dict[str, str]]:
    with open(JUDGES_EXPORT_PATH) as f:
        data = json.load(f)
    return data["judges"]


JUDGES = load_judge_data()  # {key: {name, gemini_voice, system_prompt, ...}}


# Mood and rotation logic (lifted from judges.py so this file stands alone).

def mood_descriptor(mood: float) -> str:
    if mood < 0.3:
        return "visibly nervous, voice shaky, avoiding eye contact"
    if mood < 0.55:
        return "uncertain but holding together"
    if mood < 0.8:
        return "composed and steady"
    return "confident, maybe overconfident"


def pick_next_judge(turn_idx: int, mood: float) -> str:
    if turn_idx == 0:
        return "cuban"
    if mood < 0.4:
        return "corcoran"
    cycle = ["oleary", "corcoran", "cuban"]
    return cycle[(turn_idx - 1) % 3]


def render_system_prompt(judge_key: str, mood: float) -> str:
    template = JUDGES[judge_key]["system_prompt"]
    return template.format(mood_desc=mood_descriptor(mood))


# Vision Agents wiring.

def make_llm_for_judge(judge_key: str, mood: float) -> "gemini.Realtime":
    voice = JUDGES[judge_key]["gemini_voice"]
    instructions = render_system_prompt(judge_key, mood)
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
            system_instruction=instructions,
        ),
        fps=3,
    )


def make_edge():
    """Construct WebRTC transport. Prefers Tencent (sponsor track) but falls
    back to GetStream if Tencent.Edge fails (common on feat/tencent-rtc as of
    May 16). Both reach the same SFU pool via different ingress paths.
    """
    try:
        return tencent.Edge(
            app_id=int(os.environ["TRTC_SDK_APP_ID"]),
            secret=os.environ["TRTC_SECRET_KEY"],
        )
    except Exception as exc:
        print(f"[warn] tencent.Edge unavailable ({exc}); falling back to getstream.Edge")
        return getstream.Edge(
            api_key=os.environ["STREAM_API_KEY"],
            api_secret=os.environ["STREAM_API_SECRET"],
        )


def wait_for_participant(call_id: str, timeout_s: int = 120) -> None:
    """Poll Stream REST API for participants in call_id. Returns when first
    non-agent participant joins. Raises TimeoutError after timeout_s.

    Note: agent.Edge() join() against an empty room times out.
    Browser must join first.
    """
    # TODO: poll GET /video/call/default/{call_id} every 2-3s for
    # participants list; return when len(participants) > 0 and any
    # participant is not the agent itself.
    raise NotImplementedError("Poll Stream REST API here")


# Session state.

class Session:
    def __init__(self) -> None:
        self.id: str = uuid.uuid4().hex[:8]
        self.turns: list[dict[str, Any]] = []
        self.current_judge: str = "cuban"
        self.mood: float = 0.5
        self.start_ts: float = time.monotonic()

    def add_turn(self, transcript: str, judge: str, response_text: str,
                 audio_url: str, latency_ms: int) -> None:
        self.turns.append({
            "turn_idx": len(self.turns),
            "transcript": transcript,
            "judge": judge,
            "response": response_text,
            "audio_url": audio_url,
            "mood": self.mood,
            "latency_ms": latency_ms,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "turns": self.turns,
            "total_latency_ms": int((time.monotonic() - self.start_ts) * 1000),
        }


def get_mood() -> float:
    """Latest mood snapshot. Replace with real webcam analysis (~3s)."""
    return 0.6  # placeholder


# Callbacks.

def on_turn_end(session: Session, transcript: str, agent: "Agent") -> dict[str, Any]:
    """Called by Vision Agents when Gemini's internal VAD detects pitch end.

    Returns dict to emit to websocket: {judge, text, audio}.
    """
    import cos  # this repo's module, sibling to your Vision Agents app

    start = time.monotonic()
    session.mood = get_mood()
    turn_idx = len(session.turns)
    next_judge = pick_next_judge(turn_idx, session.mood)

    if next_judge != session.current_judge:
        session.current_judge = next_judge
        # Hot-swap unconfirmed. If unsupported, recreate the agent here:
        #   agent = Agent(edge=make_edge(), llm=make_llm_for_judge(next_judge, session.mood), ...)
        agent.llm = make_llm_for_judge(next_judge, session.mood)

    # Vision Agents will send transcript -> gemini.Realtime, stream the audio
    # response on the call track, and emit audio bytes via
    # _emit_audio_output_event. Capture those bytes (24kHz PCM) and any
    # emitted text, then fill in:
    audio_bytes_24khz_pcm = b""  # fill from agent output
    response_text = ""  # fill from agent output

    try:
        audio_url = cos.upload_audio(
            session.id, turn_idx, next_judge, audio_bytes_24khz_pcm
        )
    except Exception as exc:
        print(f"[warn] cos.upload_audio failed: {exc}")
        audio_url = ""

    latency_ms = int((time.monotonic() - start) * 1000)
    session.add_turn(transcript, next_judge, response_text, audio_url, latency_ms)

    # Emit this over the websocket to the browser frontend, which expects
    # {judge, text, audio}. Audio may need transcoding (raw 24kHz PCM vs.
    # base64 MP3) before the browser frontend can play it; confirm format
    # with the browser frontend during integration.
    return {
        "judge": next_judge,
        "text": response_text,
        "audio": audio_bytes_24khz_pcm,
    }


def on_session_end(session: Session) -> str:
    """Upload the full session log to COS. Returns presigned URL."""
    import cos
    try:
        return cos.upload_session(session.id, session.to_dict())
    except Exception as exc:
        print(f"[warn] cos.upload_session failed: {exc}")
        return ""


def build_agent(session: Session) -> "Agent":
    # Gemini Realtime handles VAD internally, smart_turn would be a no-op
    # (and silently disables ElevenLabs TTS too). Do not pass turn_detection.
    return Agent(
        edge=make_edge(),
        llm=make_llm_for_judge(session.current_judge, session.mood),
    )


def main() -> None:
    """Local smoke check. The real run loop:
    1. Print the call join URL for the browser user
    2. Call wait_for_participant(call_id) to block until a human joins
    3. Build agent and call agent.run() / lifecycle method
    4. Agent participates in the call, emits audio, fires on_turn_end on
       Gemini's internal VAD events
    5. The Vision Agents backend routes on_turn_end to cos.upload_audio and
       emits the websocket message {judge, text, audio} to the browser
       frontend

    Gotcha: under `uv run`, asyncio.run_in_executor(None, input) fails with
    EOFError because there is no stdin. Use wait_for_participant (REST poll)
    instead of any input() prompt to block until the browser joins.
    """
    session = Session()
    voice = JUDGES[session.current_judge]["gemini_voice"]
    print(f"Session: {session.id}")
    print(f"Judges loaded: {list(JUDGES.keys())}")
    print(f"Initial judge: {session.current_judge} ({voice})")
    print("Sample prompt (Cuban, mood=0.5):")
    print("  " + render_system_prompt("cuban", 0.5)[:200] + "...")
    # Uncomment once Vision Agents deps are installed:
    # agent = build_agent(session); agent.run()


if __name__ == "__main__":
    main()
