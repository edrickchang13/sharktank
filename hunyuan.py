import os

from dotenv import load_dotenv
from tencentcloud.common.credential import Credential
from tencentcloud.hunyuan.v20230901 import hunyuan_client
from tencentcloud.hunyuan.v20230901.models import ChatCompletionsRequest

from judges import render_system_prompt

load_dotenv()

_client = None
_model = None


def _get_client():
    global _client, _model
    if _client is not None:
        return _client, _model

    secret_id = os.environ.get("TENCENT_SECRET_ID")
    secret_key = os.environ.get("TENCENT_SECRET_KEY")
    if not secret_id or not secret_key:
        missing = []
        if not secret_id:
            missing.append("TENCENT_SECRET_ID")
        if not secret_key:
            missing.append("TENCENT_SECRET_KEY")
        raise RuntimeError(
            "Hunyuan client not configured. Set these env vars: "
            + ", ".join(missing)
        )

    region = os.environ.get("TENCENT_REGION", "ap-guangzhou")
    _model = os.environ.get("HUNYUAN_MODEL", "hunyuan-lite")
    cred = Credential(secret_id, secret_key)
    _client = hunyuan_client.HunyuanClient(cred, region)
    return _client, _model


def _convert_history(history):
    if not history:
        return []
    converted = []
    for msg in history:
        role = msg.get("role") or msg.get("Role")
        content = msg.get("content") or msg.get("Content")
        if role and content:
            converted.append({"Role": role, "Content": content})
    return converted


def chat(judge_key: str, transcript: str, mood: float, history: list[dict] | None = None) -> str:
    """Send a pitch transcript to a judge and get their response.

    judge_key: 'cuban' | 'oleary' | 'corcoran'
    transcript: what the user just pitched
    mood: 0-1 confidence float from GetStream
    history: optional prior [{role, content}] messages this session
    Returns: the judge's response text (2-3 sentences typically)
    """
    client, model = _get_client()
    system_text = render_system_prompt(judge_key, mood)

    messages = [{"Role": "system", "Content": system_text}]
    messages.extend(_convert_history(history))
    messages.append({"Role": "user", "Content": transcript})

    request = ChatCompletionsRequest()
    request.Model = model
    request.Messages = messages

    response = client.ChatCompletions(request)
    return response.Choices[0].Message.Content
