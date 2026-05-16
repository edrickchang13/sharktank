"""CLI that runs one full Shark Tank pitch round end-to-end for local P1 validation."""

import argparse
import json
import sys
import uuid
from pathlib import Path

import judges

_ANSI = {"cuban": "\033[31m", "oleary": "\033[33m", "corcoran": "\033[32m"}
_RESET = "\033[0m"
_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _load_pipeline(mock: bool):
    if mock:
        import mock as pipeline_module
        return pipeline_module
    try:
        import pipeline as pipeline_module
    except Exception as exc:
        print(f"Failed to load real pipeline: {exc}", file=sys.stderr)
        print("Set up .env or use --mock", file=sys.stderr)
        sys.exit(1)
    return pipeline_module


def _color(judge_key: str, name: str) -> str:
    if not sys.stdout.isatty():
        return name
    return f"{_ANSI.get(judge_key, '')}{name}{_RESET}"


def _save_audio(session_id: str, turn_idx: int, judge_key: str, audio_bytes: bytes) -> Path:
    path = _OUTPUT_DIR / f"turn_{turn_idx:03d}_{judge_key}.mp3"
    path.write_bytes(audio_bytes)
    return path


def _try_upload(label: str, fn, *args) -> None:
    try:
        url = fn(*args)
        print(f"  {label} uploaded: {url}")
    except Exception as exc:
        print(f"  warning: {label} upload failed ({exc})", file=sys.stderr)


def run(turns: int, mood: float, mock: bool, no_cos: bool) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pipeline_module = _load_pipeline(mock)
    session_id = uuid.uuid4().hex[:8]
    history: list[dict] = []
    turn_records: list[dict] = []
    total_latency = 0

    print(f"Session {session_id} starting ({turns} turns, mood={mood}, mock={mock})")

    for turn_idx in range(turns):
        transcript = input(f"\nYou (turn {turn_idx + 1}/{turns}): ").strip()
        if not transcript:
            print("Empty transcript, skipping turn.")
            continue
        judge_key = judges.pick_next_judge(turn_idx, mood)
        try:
            result = pipeline_module.respond_to_pitch(judge_key, transcript, mood, history)
        except Exception as exc:
            print(f"Pipeline call failed: {exc}", file=sys.stderr)
            print("Set up .env or use --mock", file=sys.stderr)
            sys.exit(1)

        judge_name = judges.JUDGES[judge_key].name
        text = result["text"]
        latency = result.get("latency_ms", 0)
        total_latency += latency
        print(f"\n{_color(judge_key, judge_name)} ({latency} ms):")
        print(f"  {text}")

        audio_path = _save_audio(session_id, turn_idx, judge_key, result["audio_bytes"])
        print(f"  audio saved: {audio_path}")
        if not no_cos and not mock:
            _try_upload("audio", pipeline_module.log_turn_audio, session_id, turn_idx, judge_key, result["audio_bytes"])

        history.append({"role": "user", "content": transcript})
        history.append({"role": "assistant", "content": text})
        turn_records.append(
            {"transcript": transcript, "judge": judge_key, "text": text, "mood": mood, "latency_ms": latency}
        )

    payload = {
        "session_id": session_id,
        "mock_mode": mock,
        "total_latency_ms": total_latency,
        "turns": turn_records,
    }
    session_path = _OUTPUT_DIR / f"session_{session_id}.json"
    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nSession summary saved: {session_path}")
    if not no_cos and not mock:
        _try_upload("session", pipeline_module.log_session, session_id, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Shark Tank pitch round end-to-end.")
    parser.add_argument("--mock", action="store_true", help="Use mock pipeline (no Tencent calls)")
    parser.add_argument("--turns", type=int, default=3, help="Number of judge turns to simulate")
    parser.add_argument("--mood", type=float, default=0.6, help="Static mood value (0-1)")
    parser.add_argument("--no-cos", action="store_true", help="Skip COS uploads")
    args = parser.parse_args()
    run(turns=args.turns, mood=args.mood, mock=args.mock, no_cos=args.no_cos)


if __name__ == "__main__":
    main()
