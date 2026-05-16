"""Vision Agents starter for Shark Tank Simulator (P2 reference).

Wired: tencent.Edge() from env, gemini.Realtime with response_modalities=
[AUDIO] and per-judge voice swap, judge prompts from judges_export.json,
judge rotation (cuban opens, low-mood -> corcoran, else rotate), COS
callbacks for per-turn audio + session JSON.

P2 owns: websocket transport to P3, smart-turn VAD wiring under
tencent.Edge, real mood processor (webcam, ~3s), agent.llm hot-swap or
agent reconstruction per judge change.
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
from vision_agents.plugins import gemini, smart_turn, tencent

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


def make_edge() -> "tencent.Edge":
    return tencent.Edge(
        app_id=int(os.environ["TRTC_SDK_APP_ID"]),
        secret=os.environ["TRTC_SECRET_KEY"],
    )


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
    """Latest mood snapshot. P2 replaces with real webcam analysis (~3s)."""
    return 0.6  # placeholder


# Callbacks.

def on_turn_end(session: Session, transcript: str, agent: "Agent") -> dict[str, Any]:
    """Called by Vision Agents when smart-turn detects pitch end.

    Returns dict to emit to websocket: {judge, text, audio}.
    """
    import cos  # P1's module, sibling to your Vision Agents app

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
    # _emit_audio_output_event. P2: capture those bytes (24kHz PCM) and any
    # emitted text, then fill in:
    audio_bytes_24khz_pcm = b""  # P2 fills from agent output
    response_text = ""  # P2 fills from agent output

    try:
        audio_url = cos.upload_audio(
            session.id, turn_idx, next_judge, audio_bytes_24khz_pcm
        )
    except Exception as exc:
        print(f"[warn] cos.upload_audio failed: {exc}")
        audio_url = ""

    latency_ms = int((time.monotonic() - start) * 1000)
    session.add_turn(transcript, next_judge, response_text, audio_url, latency_ms)

    # P2: emit this over your websocket to P3. P3 expects {judge, text, audio}.
    # Audio may need transcoding (raw 24kHz PCM vs. base64 MP3); see
    # HANDOFF_TO_P2.md open question 3.
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
    return Agent(
        edge=make_edge(),
        llm=make_llm_for_judge(session.current_judge, session.mood),
        turn_detection=smart_turn.VAD(),
    )


def main() -> None:
    """Minimal smoke loop with no websocket. Replace with the real Vision
    Agents lifecycle and websocket server."""
    session = Session()
    voice = JUDGES[session.current_judge]["gemini_voice"]
    print(f"Session: {session.id}")
    print(f"Judges loaded: {list(JUDGES.keys())}")
    print(f"Initial judge: {session.current_judge} ({voice})")
    print("Sample prompt (Cuban, mood=0.5):")
    print("  " + render_system_prompt("cuban", 0.5)[:200] + "...")
    # P2: uncomment once Vision Agents deps are installed:
    # agent = build_agent(session); agent.run()


if __name__ == "__main__":
    main()
