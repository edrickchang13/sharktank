# IVH (Tencent AI Digital Human) integration status:
# - Default mode is STATIC (headshot + audio). This works without IVH activation.
# - IVH mode is stubbed. Activation requires contacting Tencent pre-sales.
# - See https://www.tencentcloud.com/document/product/1211 once activated.

import os
from enum import Enum
from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "judges"

_AVATAR_IDS = {
    "cuban": os.environ.get("IVH_AVATAR_CUBAN"),
    "oleary": os.environ.get("IVH_AVATAR_OLEARY"),
    "corcoran": os.environ.get("IVH_AVATAR_CORCORAN"),
}


class RenderMode(str, Enum):
    STATIC = "static"
    IVH = "ivh"


def get_static_image_path(judge_key: str) -> str:
    """Return the path to the static headshot for a judge.
    Path: assets/judges/{judge_key}.png
    Caller must ensure the file exists.
    """
    return str(_ASSETS_DIR / f"{judge_key}.png")


def _render_static(judge_key: str, audio_bytes: bytes) -> dict:
    return {
        "mode": RenderMode.STATIC.value,
        "image_path": get_static_image_path(judge_key),
        "audio_bytes": audio_bytes,
    }


def _render_ivh(judge_key: str, audio_bytes: bytes) -> dict:
    # TODO(IVH activation): once Tencent pre-sales confirms access:
    #   1. Confirm SDK package name (likely `tencentcloud-sdk-python` ivh submodule).
    #   2. Wire region + SecretId/SecretKey from env (TENCENTCLOUD_SECRET_ID/KEY).
    #   3. Pick API: real-time streaming vs. async broadcast (we want async for pitch playback).
    #      Endpoint base: ivh.tencentcloudapi.com — see product doc 1211.
    #   4. Use _AVATAR_IDS[judge_key] as the AvatarId; upload audio_bytes, poll job, return video URL.
    avatar_id = _AVATAR_IDS.get(judge_key)
    raise NotImplementedError(
        f"IVH activation pending - using static mode (judge={judge_key}, avatar_id={avatar_id})"
    )


def render_judge(
    judge_key: str,
    audio_bytes: bytes,
    mode: RenderMode = RenderMode.STATIC,
) -> dict:
    """Render a judge's avatar with the given audio.

    Returns a dict:
      - For STATIC: {"mode": "static", "image_path": "...", "audio_bytes": b"..."}
      - For IVH:    {"mode": "ivh", "video_url": "..."}

    The frontend (P3) reads .mode to decide how to render.
    """
    if mode == RenderMode.STATIC:
        return _render_static(judge_key, audio_bytes)
    if mode == RenderMode.IVH:
        return _render_ivh(judge_key, audio_bytes)
    raise ValueError(f"Unknown render mode: {mode}")
