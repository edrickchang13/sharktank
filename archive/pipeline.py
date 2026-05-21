"""End-to-end pipeline: transcript + mood -> judge text + audio + render.

Drop-in replacement for `mock.respond_to_pitch`. Swap the import in the frontend
once real Tencent credentials are in place.
"""

import time

import chunker
import cos
import hunyuan
import ivh


def respond_to_pitch(
    judge_key: str,
    transcript: str,
    mood: float,
    history: list[dict] | None = None,
    render_mode: ivh.RenderMode = ivh.RenderMode.STATIC,
) -> dict:
    """Run the full pipeline for one turn.

    Returns the same shape as mock.respond_to_pitch so the frontend can swap
    imports without other changes:
      {judge, text, audio_bytes, image_path, latency_ms}
    """
    start = time.monotonic()
    text = hunyuan.chat(judge_key, transcript, mood, history)
    audio_bytes = chunker.synthesize_long(text, judge_key)
    render = ivh.render_judge(judge_key, audio_bytes, mode=render_mode)
    latency_ms = int((time.monotonic() - start) * 1000)
    return {
        "judge": judge_key,
        "text": text,
        "audio_bytes": audio_bytes,
        "image_path": render.get("image_path", ""),
        "video_url": render.get("video_url", ""),
        "latency_ms": latency_ms,
    }


def log_session(session_id: str, session_data: dict) -> str:
    """Persist the full session log to COS and return the presigned URL."""
    return cos.upload_session(session_id, session_data)


def log_turn_audio(
    session_id: str,
    turn_idx: int,
    judge_key: str,
    audio_bytes: bytes,
) -> str:
    """Persist one turn's audio to COS and return the presigned URL."""
    return cos.upload_audio(session_id, turn_idx, judge_key, audio_bytes)
