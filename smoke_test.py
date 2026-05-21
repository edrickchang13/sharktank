"""Smoke test for the Shark Tank simulator (live modules only).

Tests this repo's scope: judges, trtc, cos. Archived modules (hunyuan,
tts, ivh, chunker, pipeline, mock, demo, feedback) are intentionally not
imported. Runnable as `python smoke_test.py` — pure stdlib, no pytest.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Callable

_USE_COLOR = sys.stdout.isatty()
GREEN = "\033[92m" if _USE_COLOR else ""
RED = "\033[91m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""

_REPO_ROOT = Path(__file__).resolve().parent
_TRTC_VARS = ("TRTC_SDK_APP_ID", "TRTC_SECRET_KEY")
_COS_VARS = ("TENCENT_SECRET_ID", "TENCENT_SECRET_KEY", "COS_BUCKET")


def _save_env(keys: tuple[str, ...]) -> dict[str, str | None]:
    return {k: os.environ.get(k) for k in keys}


def _restore_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _set_trtc_env() -> None:
    os.environ["TRTC_SDK_APP_ID"] = "1400000000"
    os.environ["TRTC_SECRET_KEY"] = "fakekey"


def test_imports() -> None:
    import cos  # noqa: F401
    import judges  # noqa: F401
    import trtc  # noqa: F401


def test_render_system_prompt_all_judges() -> None:
    import judges
    for key in ("cuban", "oleary", "corcoran"):
        prompt = judges.render_system_prompt(key, 0.5)
        assert isinstance(prompt, str) and prompt, f"{key}: empty"
        assert "{mood_desc}" not in prompt, f"{key}: placeholder not substituted"


def test_mood_descriptor_extremes() -> None:
    import judges
    assert "nervous" in judges.render_system_prompt("cuban", 0.1)
    assert "confident" in judges.render_system_prompt("cuban", 0.9)


def test_pick_next_judge() -> None:
    import judges
    assert judges.pick_next_judge(0, 0.5) == "cuban"
    assert judges.pick_next_judge(1, 0.2) == "corcoran"
    assert judges.pick_next_judge(1, 0.8) == "oleary"


def test_trtc_user_sig_generation() -> None:
    import trtc
    saved = _save_env(_TRTC_VARS)
    try:
        _set_trtc_env()
        sig = trtc.generate_user_sig("user_001")
        assert isinstance(sig, str) and len(sig) >= 100, f"sig len={len(sig)}"
        creds = trtc.make_room_credentials("room_42", "user_001")
        for k in ("sdk_app_id", "user_id", "user_sig", "room_id"):
            assert k in creds, f"missing key: {k}"
    finally:
        _restore_env(saved)


def test_trtc_env_missing() -> None:
    import trtc
    saved = _save_env(_TRTC_VARS)
    try:
        for k in _TRTC_VARS:
            os.environ.pop(k, None)
        try:
            trtc.generate_user_sig("user")
        except RuntimeError:
            return
        raise AssertionError("expected RuntimeError")
    finally:
        _restore_env(saved)


def test_trtc_expire_validation() -> None:
    import trtc
    saved = _save_env(_TRTC_VARS)
    try:
        _set_trtc_env()
        for bad in (0, 100 * 86400):
            try:
                trtc.generate_user_sig("user", expire_seconds=bad)
            except ValueError:
                continue
            raise AssertionError(f"expected ValueError for expire_seconds={bad}")
    finally:
        _restore_env(saved)


def test_cos_env_missing() -> None:
    import cos
    saved = _save_env(_COS_VARS)
    try:
        for k in _COS_VARS:
            os.environ.pop(k, None)
        cos._client = None
        cos._bucket = None
        try:
            cos.upload_session("test", {})
        except RuntimeError as exc:
            msg = str(exc)
            for var in _COS_VARS:
                assert var in msg, f"missing {var} in error: {msg}"
            return
        raise AssertionError("expected RuntimeError")
    finally:
        _restore_env(saved)
        cos._client = None
        cos._bucket = None


def test_judges_export_json_valid() -> None:
    data = json.loads((_REPO_ROOT / "judges_export.json").read_text())
    for key in ("schema_version", "exported_at", "judges", "mood_descriptors", "rotation"):
        assert key in data, f"missing top-level key: {key}"
    j = data["judges"]
    assert set(j.keys()) == {"cuban", "oleary", "corcoran"}, f"judges={set(j.keys())}"
    for key, entry in j.items():
        prompt = entry.get("system_prompt", "")
        assert prompt, f"{key}: empty system_prompt"
        assert "{mood_desc}" in prompt, f"{key}: missing {{mood_desc}}"


def test_no_em_dashes_in_judges() -> None:
    text = (_REPO_ROOT / "judges.py").read_text()
    assert "—" not in text, "judges.py contains an em-dash"


TESTS: list[Callable[[], None]] = [
    test_imports, test_render_system_prompt_all_judges, test_mood_descriptor_extremes,
    test_pick_next_judge, test_trtc_user_sig_generation, test_trtc_env_missing,
    test_trtc_expire_validation, test_cos_env_missing, test_judges_export_json_valid,
    test_no_em_dashes_in_judges,
]


def _run() -> int:
    sys.path.insert(0, str(_REPO_ROOT))
    passed = failed = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"{GREEN}PASS{RESET} {name}")
            passed += 1
        except Exception as exc:
            failed += 1
            tb = traceback.extract_tb(exc.__traceback__)
            line = tb[-1].lineno if tb else "?"
            print(f"{RED}FAIL{RESET} {name} (line {line}): {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run())
