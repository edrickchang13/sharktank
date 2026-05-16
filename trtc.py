# TRTC UserSig generation (server-side only).
# Reference: https://www.tencentcloud.com/document/product/647/35166
# The Python sample at https://github.com/tencentyun/tls-sig-api-v2-python
# implements this same algorithm.

import base64
import hashlib
import hmac
import json
import os
import time
import zlib
from typing import Union

from dotenv import load_dotenv

load_dotenv()

_MAX_EXPIRE_SECONDS = 90 * 86400


def _load_credentials() -> tuple[int, str]:
    sdk_app_id = os.environ.get("TRTC_SDK_APP_ID")
    secret_key = os.environ.get("TRTC_SECRET_KEY")
    missing = [name for name, val in (("TRTC_SDK_APP_ID", sdk_app_id), ("TRTC_SECRET_KEY", secret_key)) if not val]
    if missing:
        raise RuntimeError(f"Missing required TRTC env vars: {', '.join(missing)}")
    return int(sdk_app_id), secret_key


def generate_user_sig(user_id: str, expire_seconds: int = 86400) -> str:
    """Generate a TRTC UserSig token for a given user_id.

    Reads SDKAppID + SDKSecretKey from env (TRTC_SDK_APP_ID, TRTC_SECRET_KEY).
    Default expiry: 24 hours.
    """
    if not (expire_seconds > 0 and expire_seconds < _MAX_EXPIRE_SECONDS):
        raise ValueError(
            f"expire_seconds must be > 0 and < {_MAX_EXPIRE_SECONDS} (90 days); got {expire_seconds}"
        )
    sdk_app_id, secret_key = _load_credentials()
    current_time = int(time.time())
    sig_doc = {
        "TLS.ver": "2.0",
        "TLS.identifier": user_id,
        "TLS.sdkappid": sdk_app_id,
        "TLS.expire": expire_seconds,
        "TLS.time": current_time,
    }
    string_to_sign = (
        "TLS.identifier:" + user_id + "\n"
        + "TLS.sdkappid:" + str(sdk_app_id) + "\n"
        + "TLS.time:" + str(current_time) + "\n"
        + "TLS.expire:" + str(expire_seconds) + "\n"
    )
    sig = base64.b64encode(
        hmac.new(secret_key.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    sig_doc["TLS.sig"] = sig
    compressed = zlib.compress(json.dumps(sig_doc).encode())
    usersig = base64.b64encode(compressed).decode()
    return usersig.replace("+", "*").replace("/", "-").replace("=", "_")


def make_room_credentials(room_id: Union[int, str], user_id: str) -> dict:
    """Bundle everything the TRTC client SDK needs to join a room.

    Returns:
      {
        "sdk_app_id": int,
        "user_id": str,
        "user_sig": str,
        "room_id": int | str,
      }
    """
    sdk_app_id, _ = _load_credentials()
    return {
        "sdk_app_id": sdk_app_id,
        "user_id": user_id,
        "user_sig": generate_user_sig(user_id),
        "room_id": room_id,
    }
