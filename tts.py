import base64
import os
import uuid

from dotenv import load_dotenv
from tencentcloud.common.credential import Credential
from tencentcloud.tts.v20190823 import models, tts_client

load_dotenv()

_REQUIRED_ENV = ("TENCENT_SECRET_ID", "TENCENT_SECRET_KEY")
_JUDGE_ENV = {
    "cuban": "TTS_VOICE_CUBAN",
    "oleary": "TTS_VOICE_OLEARY",
    "corcoran": "TTS_VOICE_CORCORAN",
}
_MAX_LEN = 500

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
    if missing:
        raise RuntimeError("set: " + ", ".join(_REQUIRED_ENV))
    cred = Credential(os.getenv("TENCENT_SECRET_ID"), os.getenv("TENCENT_SECRET_KEY"))
    region = os.getenv("TENCENT_REGION", "ap-guangzhou")
    _client = tts_client.TtsClient(cred, region)
    return _client


def synthesize(text, voice_id):
    """Synthesize text to MP3 audio bytes using the given voice ID.

    Returns raw MP3 bytes (already base64-decoded).
    """
    if len(text) > _MAX_LEN:
        raise ValueError(
            f"text length {len(text)} exceeds max {_MAX_LEN}; caller must chunk"
        )
    client = _get_client()
    req = models.TextToVoiceRequest()
    req.Text = text
    req.SessionId = uuid.uuid4().hex
    req.VoiceType = int(voice_id)
    req.Codec = "mp3"
    req.SampleRate = 16000
    req.PrimaryLanguage = 2
    resp = client.TextToVoice(req)
    return base64.b64decode(resp.Audio)


def synthesize_for_judge(text, judge_key):
    """Look up the env-configured voice for a judge and synthesize."""
    key = judge_key.lower()
    if key not in _JUDGE_ENV:
        raise KeyError(
            f"unknown judge '{judge_key}'; expected one of {list(_JUDGE_ENV)}"
        )
    env_name = _JUDGE_ENV[key]
    raw = os.getenv(env_name)
    if not raw:
        raise KeyError(f"set: {env_name}")
    return synthesize(text, int(raw))
