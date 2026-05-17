"""Pitch Tank judge agent (LiveKit Agents + LemonSlice avatar).

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

# Prefer GOOGLE_API_KEY_V2 for the agent's Gemini Live session. The original
# GOOGLE_API_KEY was reported to Google as leaked (see web logs:
# "Your API key was reported as leaked, please use another API key") and is
# now permanently blocked. Set GOOGLE_API_KEY to V2's value BEFORE the
# google.genai SDK imports so livekit.plugins.google picks up the right key.
load_dotenv(".env")
_AGENT_KEY = os.environ.get("GOOGLE_API_KEY_V2") or os.environ.get("GOOGLE_API_KEY", "")
if _AGENT_KEY:
    os.environ["GOOGLE_API_KEY"] = _AGENT_KEY

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

# Prepended to every judge's system prompt so the founder gets an
# uninterrupted 60 second opening. Best-effort: Gemini Live may still
# interject. The browser is the authoritative timer; the agent observes
# the protocol via a `pitch_complete` LiveKit data message on expiry.
PITCH_PREAMBLE = (
    "Pitch Tank session protocol: the founder gets 60 seconds for an "
    "uninterrupted opening pitch. During this period, you MUST listen "
    "silently and not generate any audio response. After they finish "
    "their opening or 60 seconds elapse, ask your first sharp question. "
    "If you receive a message that includes 'pitch_complete', the silent "
    "phase has ended and you may start questioning.\n\n"
)


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
        # Prepend the pitch-phase preamble so the judge stays silent for the
        # first 60 seconds. The persona body still controls everything else.
        persona = judges.render_system_prompt(judge_key, mood)
        instructions = PITCH_PREAMBLE + persona
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

    # Observe 60s pitch protocol. Browser publishes pitch_complete on the
    # LiveKit data channel; PITCH_PREAMBLE tells the model to wait for it.
    # TODO(verify): event name + handler signature on livekit-agents 1.5.x.
    def _on_data_received(data_packet: Any) -> None:
        """Log on pitch_complete; ignore other room data."""
        try:
            raw = getattr(data_packet, "data", None)
            if raw is None:
                return
            if json.loads(raw.decode()).get("type") == "pitch_complete":
                logger.info("[pitch_phase] pitch_complete received, judge can engage")
        except Exception:
            logger.debug("pitch data parse failed", exc_info=True)

    try:
        ctx.room.on("data_received", _on_data_received)
    except Exception as exc:
        logger.warning("failed to register data_received handler: %s", exc)

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

    def _record_text(role: str, text: str) -> None:
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
        speaker = "founder" if role == "founder" else userdata.judge_key
        asyncio.create_task(_push_to_browser({
            "type": "transcript",
            "judge": speaker,
            "text": text,
            "mood": round(userdata.mood, 3),
            "turn_idx": userdata.turn_index,
            "mode": "final",
        }))
        if role != "founder":
            userdata.turn_index += 1

    def _on_user_input_transcribed(event: Any) -> None:
        if not getattr(event, "is_final", False):
            return
        _record_text("founder", str(getattr(event, "transcript", "") or ""))

    def _extract_item_text(item: Any) -> str:
        for attr in ("text_content", "content", "text"):
            val = getattr(item, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if val is None:
                continue
            if isinstance(val, list):
                parts: list[str] = []
                for p in val:
                    if isinstance(p, str):
                        parts.append(p)
                    else:
                        t = getattr(p, "text", None)
                        if isinstance(t, str):
                            parts.append(t)
                return " ".join(parts).strip()
            if isinstance(val, str):
                return val.strip()
        return ""

    def _on_conversation_item_added(event: Any) -> None:
        item = getattr(event, "item", None)
        if item is None:
            return
        if getattr(item, "role", None) != "assistant":
            return
        _record_text(userdata.judge_key, _extract_item_text(item))

    # Event names verified for livekit-agents 1.5.9.
    session.on("user_input_transcribed", _on_user_input_transcribed)
    session.on("conversation_item_added", _on_conversation_item_added)

    # LemonSlice is OPTIONAL. If the API key is not set, run audio-only and
    # let the browser show the pixel-art placeholder for the active judge.
    # The frontend reads speaking_start / speaking_end over WS to animate
    # idle <-> talking even without a real avatar video track.
    if os.environ.get("LEMONSLICE_API_KEY"):
        try:
            avatar = lemonslice.AvatarSession(
                agent_image_url=DEFAULT_AVATAR_URLS[judge_key],
                agent_prompt=AVATAR_PROMPTS[judge_key],
            )
            await avatar.start(session, room=ctx.room)
            logger.info("lemonslice avatar started judge=%s", judge_key)
        except Exception as exc:
            logger.warning(
                "lemonslice failed (running audio-only): %s", exc
            )
    else:
        logger.info(
            "LEMONSLICE_API_KEY not set, running audio-only judge=%s",
            judge_key,
        )

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
