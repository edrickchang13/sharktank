import random
import sys
from pathlib import Path

print("[mock.py] Using MOCK pipeline — Tencent services not wired.", file=sys.stderr)

_SILENT_MP3 = b'\xff\xfb\x90\x00' + b'\x00' * 56

_RESPONSES = {
    "cuban": [
        "What's your CAC? And don't give me a vague answer.",
        "Your unit economics don't add up. Show me the math.",
        "I've heard ten pitches like this. What's different?",
    ],
    "oleary": [
        "What's the valuation? Because that number sounds delusional.",
        "I'd do this as a royalty deal. Five percent in perpetuity. Take it or leave it.",
        "You're burning my time. Get to the money.",
    ],
    "corcoran": [
        "Tell me about you. Who's the person behind this pitch?",
        "I can see you're nervous. That's fine. Why did you start this?",
        "I trust my gut on people. Convince me you can execute.",
    ],
}

_HARSH_SUFFIX = {"cuban": " You're not ready.", "oleary": " Next."}

_BASE_DIR = Path(__file__).resolve().parent


def respond_to_pitch(judge_key: str, transcript: str, mood: float, history: list[dict] | None = None) -> dict:
    """Mock version of the full P1 pipeline.

    Returns:
      {
        "judge": str,           # judge_key
        "text": str,            # judge's response text
        "audio_bytes": bytes,   # MP3 bytes of the spoken response (silent mock audio)
        "image_path": str,      # static avatar path
        "latency_ms": int,      # fake latency to simulate real pipeline
      }
    """
    options = _RESPONSES.get(judge_key, _RESPONSES["cuban"])
    text = options[hash(transcript) % 3]
    if mood < 0.4 and judge_key in _HARSH_SUFFIX:
        text += _HARSH_SUFFIX[judge_key]
    image_path = str(_BASE_DIR / "assets" / "judges" / f"{judge_key}.png")
    return {
        "judge": judge_key,
        "text": text,
        "audio_bytes": _SILENT_MP3,
        "image_path": image_path,
        "latency_ms": random.randint(1500, 3500),
    }


def log_session(session_id: str, session_data: dict) -> str:
    """Mock COS upload. Returns a fake URL."""
    return f"mock://cos/sessions/{session_id}/session.json"
