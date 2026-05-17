"""Pitch Tank FastAPI server (LiveKit + LemonSlice stack).

Endpoints: GET / (index), GET /assets/* (static), GET /token (LiveKit JWT),
WS /ws (broadcast + mood Vision), POST /session_log (forwards to COS).
The LiveKit agent runs as a separate worker process, not in this server.
"""

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from livekit import api

import cos

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Prefer V2 because V1 (GOOGLE_API_KEY) was reported leaked and is now
# permanently 403'd by Google's reputation system. Mood Vision falls back to
# V1 only if V2 is unset (which won't work right now, but keeps the
# expression valid in case the user provisions a fresh V1 later).
_VISION_KEY: str = os.environ.get("GOOGLE_API_KEY_V2") or os.environ.get("GOOGLE_API_KEY", "")

app = FastAPI()
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

_ws_clients: list[WebSocket] = []


async def broadcast(msg: dict[str, Any]) -> None:
    """Send a JSON message to every connected websocket client."""
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            _ws_clients.remove(ws)
        except ValueError:
            pass


@app.get("/")
async def index() -> FileResponse:
    """Serve the frontend single-page app."""
    return FileResponse("frontend/index.html")


@app.get("/token")
async def get_token(room: str, judge_key: str, identity: str | None = None) -> JSONResponse:
    """Issue a LiveKit JWT for the room AND dispatch the judge agent to it.

    The worker registers with agent_name='shark-tank-judge' via
    AgentServer.rtc_session, which means it does NOT auto-accept rooms.
    We must explicitly create a dispatch when the founder requests a token
    so the agent worker spawns into the same room.
    """
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    url = os.environ.get("LIVEKIT_URL")
    if not key or not secret or not url:
        return JSONResponse({"error": "LIVEKIT_API_KEY/SECRET/URL must be set"}, status_code=500)
    ident = identity or ("founder-" + uuid.uuid4().hex[:8])
    try:
        token = (
            api.AccessToken(key, secret)
            .with_identity(ident)
            .with_name(ident)
            .with_grants(api.VideoGrants(
                room_join=True, room=room, can_publish=True, can_subscribe=True,
            ))
            .with_attributes({"judge_key": judge_key})
            .to_jwt()
        )
    except Exception as e:
        logger.error("token mint failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

    # Dispatch the judge agent to this room. LiveKit dedupes by (room,
    # agent_name), so re-issuing a token for the same room is safe.
    try:
        lkapi = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
        try:
            await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name="shark-tank-judge",
                    room=room,
                    metadata=json.dumps({"judge_key": judge_key}),
                )
            )
            logger.info("agent dispatched room=%s judge=%s", room, judge_key)
        finally:
            await lkapi.aclose()
    except Exception as e:
        logger.warning("agent dispatch failed for room=%s: %s", room, e)

    return JSONResponse({"token": token, "url": url, "ws_url": url, "identity": ident, "room": room})


@app.post("/broadcast")
async def broadcast_endpoint(request: Request) -> JSONResponse:
    """Worker container pushes transcript + speaking events here; web fans
    them out to every browser via the existing WS broadcast channel.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"bad json: {e}"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "object required"}, status_code=400)
    await broadcast(payload)
    return JSONResponse({"ok": True})


@app.post("/session_log")
async def session_log(request: Request) -> JSONResponse:
    """Receive a session log from the agent and upload to COS."""
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"bad json: {e}"}, status_code=400)
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    try:
        loop = asyncio.get_running_loop()
        url = await loop.run_in_executor(None, cos.upload_session, session_id, payload)
    except Exception as e:
        logger.error("session_log upload failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"url": url})


# gemini-2.5-flash has separate free-tier quota from gemini-2.0-flash.
_MOOD_MODEL = os.environ.get("MOOD_MODEL", "gemini-2.5-flash")
_MOOD_MIN_INTERVAL_S = float(os.environ.get("MOOD_MIN_INTERVAL_S", "8.0"))
_MOOD_BACKOFF_S = float(os.environ.get("MOOD_BACKOFF_S", "30.0"))
_mood_last_call_ts: float = 0.0
_mood_backoff_until: float = 0.0


def _judge_for_mood(mood: float) -> str:
    """Pick the judge whose energy best matches the founder's current state.

    Nervous founders (mood < 0.4) get Barbara: warm, softens, asks about you.
    Steady founders (0.4 to 0.7) get Cuban: middle ground, demands numbers.
    Confident founders (mood > 0.7) get O'Leary: cold press, valuation attack.
    """
    if mood < 0.4:
        return "corcoran"
    if mood > 0.7:
        return "oleary"
    return "cuban"


def _analyze_frame(jpeg_bytes: bytes) -> tuple[float, str]:
    """Sync Gemini Vision call. Runs in executor; raises on failure."""
    b64 = base64.b64encode(jpeg_bytes).decode()
    client = genai.Client(api_key=_VISION_KEY)
    resp = client.models.generate_content(
        model=_MOOD_MODEL,
        contents=[{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                {"text": (
                    "You are analyzing a startup founder during a Shark Tank pitch. "
                    "Return a JSON object with two fields and nothing else: "
                    "{\"confidence\": float in [0.0, 1.0] where 0 is panic and 1 is "
                    "calm dominance, \"scene\": short one-sentence description noting "
                    "any visible objects, gestures, facial expression, or body language}"
                )},
            ]
        }]
    )
    text = (resp.text or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    data: dict[str, Any] = json.loads(match.group(0)) if match else {}
    conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    scene = str(data.get("scene", ""))[:200]
    return conf, scene


async def _handle_mood_frame(image_b64: str) -> None:
    global _mood_last_call_ts, _mood_backoff_until
    now = time.monotonic()
    if now < _mood_backoff_until:
        return
    if now - _mood_last_call_ts < _MOOD_MIN_INTERVAL_S:
        return
    try:
        jpeg = base64.b64decode(image_b64)
    except Exception as e:
        logger.warning("[ws mood] bad base64: %s", e)
        return
    _mood_last_call_ts = now
    loop = asyncio.get_running_loop()
    try:
        conf, scene = await loop.run_in_executor(None, _analyze_frame, jpeg)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            _mood_backoff_until = time.monotonic() + _MOOD_BACKOFF_S
            logger.warning("[ws mood] 429 quota hit, pausing for %.0fs", _MOOD_BACKOFF_S)
        else:
            logger.warning("[ws mood] gemini failed: %s", msg[:200])
        return
    await broadcast({
        "type": "mood_update",
        "mood": conf,
        "scene": scene,
        "target_judge": _judge_for_mood(conf),
    })


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """Browser broadcast channel; accepts mood_frame inbound messages."""
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "mood_frame" and isinstance(msg.get("image"), str):
                asyncio.create_task(_handle_mood_frame(msg["image"]))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("[ws] %s", e)
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
