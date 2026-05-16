"""Shark Tank judge agent (LiveKit Agents + LemonSlice avatar).

One judge per LiveKit session. Persona is locked at session start from the
participant attribute ``judge_key`` (default ``cuban``). LemonSlice's
AvatarSession binds image + movement prompt at start time and cannot be
hot-swapped, so judge rotation = end this session and start a new one.

Audio pipeline: Gemini Live (google.beta.realtime.RealtimeModel) owns
STT+LLM+TTS in one socket. Domain content (prompts, voices, rotation) is
reused from judges.py and judges_export.json. COS log via cos.py.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    room_io,
)
from livekit.plugins import google, lemonslice

import cos
import judges

load_dotenv(".env")

logger = logging.getLogger("shark-tank-judge")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Static configuration
# ---------------------------------------------------------------------------

_JUDGES_EXPORT: dict[str, Any] = json.loads(
    (Path(__file__).parent / "judges_export.json").read_text()
)["judges"]

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
)

# Envvar-overridable avatar URLs so user can swap to real photos without code.
DEFAULT_AVATAR_URLS: dict[str, str] = {
    "cuban": os.getenv("CUBAN_AVATAR_URL", "https://iili.io/frL9tuj.png"),
    "oleary": os.getenv("OLEARY_AVATAR_URL", "https://iili.io/frL9L8u.png"),
    "corcoran": os.getenv("CORCORAN_AVATAR_URL", "https://iili.io/frL9Qyb.png"),
}

# Per-judge avatar movement prompt - drives LemonSlice body language.
AVATAR_PROMPTS: dict[str, str] = {
    "cuban": (
        "Be aggressive and direct. Sharp gestures. Quick head movements. "
        "Lean in when challenging numbers. Show impatience with vague answers."
    ),
    "oleary": (
        "Be cold and analytical. Minimal expression. Steady eye contact. "
        "Show dismissiveness through subtle facial cues. Lean back, evaluate."
    ),
    "corcoran": (
        "Be warm but sharp. Read the person. Show genuine interest in their "
        "story. Softer gestures, but pointed when calling out theatrics."
    ),
}

VALID_JUDGES = tuple(_JUDGES_EXPORT.keys())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class UserData:
    """Mutable session state shared across the AgentSession lifecycle."""

    ctx: Optional[JobContext] = None
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    judge_key: str = "cuban"
    turn_index: int = 0
    mood: float = 0.5
    transcript_history: list[dict[str, Any]] = field(default_factory=list)
    start_ts: float = field(default_factory=time.time)


# Module-level session registry so main.py can update mood by session_id.
_active_sessions: dict[str, UserData] = {}


def set_mood(session_id: str, mood: float) -> None:
    """Update mood for a live session (called by main.py's vision pipeline)."""
    userdata = _active_sessions.get(session_id)
    if userdata is None:
        logger.debug("set_mood: unknown session %s", session_id)
        return
    userdata.mood = max(0.0, min(1.0, float(mood)))


# ---------------------------------------------------------------------------
# Judge agent
# ---------------------------------------------------------------------------

class JudgeAgent(Agent):
    """Single-judge LiveKit Agent. Persona locked for the session's lifetime."""

    def __init__(self, judge_key: str, mood: float = 0.5) -> None:
        if judge_key not in VALID_JUDGES:
            raise ValueError(f"Unknown judge_key: {judge_key!r}")
        self.judge_key = judge_key
        instructions = judges.render_system_prompt(judge_key, mood)
        # TODO(integration): verify google.beta.realtime.RealtimeModel kwargs.
        # The Live API native-audio model owns STT+LLM+TTS in one socket.
        realtime_llm = google.beta.realtime.RealtimeModel(
            model=GEMINI_MODEL,
            voice=_JUDGES_EXPORT[judge_key]["gemini_voice"],
            language="en-US",
            temperature=0.8,
            instructions=instructions,
        )
        super().__init__(instructions=instructions, llm=realtime_llm)

    async def on_enter(self) -> None:
        """Send an opening line so the founder knows who they are pitching."""
        userdata: UserData = self.session.userdata
        judge_name = _JUDGES_EXPORT[self.judge_key]["name"]
        logger.info(
            "on_enter session=%s judge=%s", userdata.session_id, self.judge_key
        )
        self.session.generate_reply(
            instructions=(
                f"You are {judge_name}. Greet the founder in character with "
                "one short, sharp sentence and immediately ask the opening "
                "question from your persona. No preamble."
            )
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

server = AgentServer()


@server.rtc_session(agent_name="shark-tank-judge")
async def entrypoint(ctx: JobContext) -> None:
    """Per-room entry point. One judge per session, picked from attributes."""
    logger.info("entrypoint: connecting to room")
    await ctx.connect()
    participant = await ctx.wait_for_participant()

    judge_key = participant.attributes.get("judge_key", "cuban")
    if judge_key not in VALID_JUDGES:
        logger.warning("invalid judge_key=%r, defaulting to cuban", judge_key)
        judge_key = "cuban"

    userdata = UserData(ctx=ctx, judge_key=judge_key)
    _active_sessions[userdata.session_id] = userdata
    logger.info(
        "session=%s judge=%s voice=%s",
        userdata.session_id,
        judge_key,
        _JUDGES_EXPORT[judge_key]["gemini_voice"],
    )

    judge_agent = JudgeAgent(judge_key=judge_key, mood=userdata.mood)

    session = AgentSession[UserData](
        userdata=userdata,
        resume_false_interruption=False,
    )

    def _record(role: str, event: Any) -> None:
        text = getattr(event, "transcript", None) or getattr(event, "text", "")
        if not text or not text.strip():
            return
        userdata.transcript_history.append({
            "turn_idx": userdata.turn_index,
            "role": role,
            "text": text,
            "judge": userdata.judge_key,
            "mood": round(userdata.mood, 3),
            "ts": time.time(),
        })
        if role != "founder":
            userdata.turn_index += 1

    # TODO(integration): verify event names against installed livekit-agents.
    session.on("user_speech_committed", lambda e: _record("founder", e))
    session.on("agent_speech_committed", lambda e: _record(userdata.judge_key, e))

    avatar = lemonslice.AvatarSession(
        agent_image_url=DEFAULT_AVATAR_URLS[judge_key],
        agent_prompt=AVATAR_PROMPTS[judge_key],
    )
    await avatar.start(session, room=ctx.room)

    async def _upload_on_shutdown() -> None:
        payload = {
            "session_id": userdata.session_id,
            "judge": userdata.judge_key,
            "turns": userdata.transcript_history,
            "total_latency_ms": int((time.time() - userdata.start_ts) * 1000),
        }
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, cos.upload_session, userdata.session_id, payload
            )
            logger.info("session log uploaded id=%s", userdata.session_id)
        except Exception as exc:
            logger.exception("cos upload failed: %s", exc)
        finally:
            _active_sessions.pop(userdata.session_id, None)

    ctx.add_shutdown_callback(_upload_on_shutdown)

    await session.start(
        agent=judge_agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(delete_room_on_close=True),
    )


if __name__ == "__main__":
    cli.run_app(server)
