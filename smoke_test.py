"""Smoke test for the Shark Tank simulator.

Verifies that module interfaces are wired correctly without needing real
Tencent credentials. Runnable as `python smoke_test.py` or `pytest smoke_test.py`.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Callable

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def test_imports() -> None:
    import cos  # noqa: F401
    import hunyuan  # noqa: F401
    import ivh  # noqa: F401
    import judges  # noqa: F401
    import mock  # noqa: F401
    import pipeline  # noqa: F401
    import tts  # noqa: F401


def test_mock_response_shape() -> None:
    import mock

    resp = mock.respond_to_pitch("cuban", "We make AI tools for cats", 0.7)
    for key in ("judge", "text", "audio_bytes", "image_path", "latency_ms"):
        assert key in resp, f"missing key: {key}"
    assert isinstance(resp["text"], str), f"text is {type(resp['text'])}"
    assert isinstance(resp["audio_bytes"], bytes), f"audio_bytes is {type(resp['audio_bytes'])}"
    assert isinstance(resp["latency_ms"], int), f"latency_ms is {type(resp['latency_ms'])}"
    assert resp["text"], "text is empty"
    # MP3 sync byte: 0xFF followed by 0xE0-0xFF (frame sync 11 bits set).
    assert resp["audio_bytes"][:1] == b"\xff", f"not MP3 sync: {resp['audio_bytes'][:4]!r}"
    assert resp["audio_bytes"][1] & 0xE0 == 0xE0, f"not MP3 sync: {resp['audio_bytes'][:4]!r}"


def test_mock_low_mood_harsher() -> None:
    import mock

    text_low = mock.respond_to_pitch("cuban", "same text", 0.2)["text"]
    text_high = mock.respond_to_pitch("cuban", "same text", 0.8)["text"]
    assert len(text_low) > len(text_high), f"low={text_low!r} high={text_high!r}"
    assert text_low.endswith("You're not ready."), f"low={text_low!r}"


def test_mock_judges_distinct() -> None:
    import mock

    texts = {
        k: mock.respond_to_pitch(k, "identical transcript here", 0.6)["text"]
        for k in ("cuban", "oleary", "corcoran")
    }
    assert len(set(texts.values())) == 3, f"not distinct: {texts}"


def test_render_system_prompt_all() -> None:
    import judges

    for key in ("cuban", "oleary", "corcoran"):
        for mood in (0.1, 0.5, 0.9):
            prompt = judges.render_system_prompt(key, mood)
            assert isinstance(prompt, str) and prompt, f"{key}@{mood} empty"
    assert "nervous" in judges.render_system_prompt("cuban", 0.1)
    assert "confident" in judges.render_system_prompt("cuban", 0.9)


def test_pick_next_judge() -> None:
    import judges

    assert judges.pick_next_judge(0, 0.2) == "cuban"
    assert judges.pick_next_judge(0, 0.8) == "cuban"
    assert judges.pick_next_judge(1, 0.2) == "corcoran"
    assert judges.pick_next_judge(5, 0.2) == "corcoran"
    seen = {judges.pick_next_judge(i, 0.8) for i in range(1, 7)}
    assert "cuban" in seen and "oleary" in seen and "corcoran" in seen, f"seen={seen}"


def test_ivh_static_mode() -> None:
    import ivh

    result = ivh.render_judge("cuban", b"fake audio", mode=ivh.RenderMode.STATIC)
    assert result["mode"] == "static", f"mode={result['mode']}"
    assert result["image_path"].endswith("cuban.png"), f"path={result['image_path']}"
    assert result["audio_bytes"] == b"fake audio"


def test_ivh_mode_not_implemented() -> None:
    import ivh

    try:
        ivh.render_judge("cuban", b"x", mode=ivh.RenderMode.IVH)
    except NotImplementedError as exc:
        assert "activation pending" in str(exc), f"msg={exc}"
        return
    raise AssertionError("expected NotImplementedError")


def test_pipeline_env_missing() -> None:
    import pipeline

    if os.path.exists(os.path.join(os.path.dirname(__file__), ".env")):
        print(f"  {GREEN}SKIP{RESET} (.env present)")
        return
    saved = {k: os.environ.pop(k, None) for k in ("TENCENT_SECRET_ID", "TENCENT_SECRET_KEY")}
    # Reset cached clients so env check runs fresh.
    import hunyuan
    import tts as tts_mod
    hunyuan._client = None
    tts_mod._client = None
    try:
        try:
            pipeline.respond_to_pitch("cuban", "pitch", 0.5)
        except RuntimeError as exc:
            assert "TENCENT_SECRET" in str(exc), f"msg={exc}"
            return
        raise AssertionError("expected RuntimeError")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


TESTS: list[Callable[[], None]] = [
    test_imports,
    test_mock_response_shape,
    test_mock_low_mood_harsher,
    test_mock_judges_distinct,
    test_render_system_prompt_all,
    test_pick_next_judge,
    test_ivh_static_mode,
    test_ivh_mode_not_implemented,
    test_pipeline_env_missing,
]


def _run() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    failures = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"{GREEN}PASS{RESET} {name}")
        except Exception as exc:
            failures += 1
            tb = traceback.extract_tb(exc.__traceback__)
            line = tb[-1].lineno if tb else "?"
            print(f"{RED}FAIL{RESET} {name} (line {line}): {type(exc).__name__}: {exc}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(_run())
