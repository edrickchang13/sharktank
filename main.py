"""Shark Tank FastAPI server.

Endpoints:
  GET  /              -> serves frontend/index.html
  GET  /assets/...    -> static assets (judge images)
  GET  /credentials   -> TRTC credentials for the browser user
  WS   /ws            -> websocket broadcast channel for judge events

The websocket also accepts inbound mood frames from the browser:
  {"type": "mood_frame", "image": "<base64 jpeg>"}
Each frame is sent to Gemini Vision in a thread executor, the result updates
``agent_mod.session.mood`` and is broadcast back as a ``mood_update`` event.

Runs agent.run_agent() concurrently with the HTTP server via asyncio.gather().
"""

import asyncio
import base64
import json
import os
import re
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai

import agent as agent_mod
import trtc as trtc_mod

app = FastAPI()

app.mount("/assets", StaticFiles(directory="assets"), name="assets")

_ws_clients: list[WebSocket] = []
_session: agent_mod.Session | None = None


def set_session(session: agent_mod.Session) -> None:
    """Called by agent_mod once the live Session is constructed."""
    global _session
    _session = session


async def broadcast(msg: dict) -> None:
    dead = []
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
async def index():
    return FileResponse("frontend/index.html")


@app.get("/credentials")
async def get_credentials(room_id: int):
    user_id = "founder-" + uuid.uuid4().hex[:8]
    try:
        creds = trtc_mod.make_room_credentials(room_id=room_id, user_id=user_id)
        return JSONResponse(creds)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _analyze_frame(jpeg_bytes: bytes) -> tuple[float, str]:
    """Sync Gemini Vision call. Runs in executor; raises on failure."""
    b64 = base64.b64encode(jpeg_bytes).decode()
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    resp = client.models.generate_content(
        model="gemini-2.0-flash",
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
    try:
        jpeg = base64.b64decode(image_b64)
    except Exception as e:
        print(f"[ws mood] bad base64: {e}", flush=True)
        return

    loop = asyncio.get_running_loop()
    try:
        conf, scene = await loop.run_in_executor(None, _analyze_frame, jpeg)
    except Exception as e:
        print(f"[ws mood] gemini failed: {e}", flush=True)
        return

    if _session is not None:
        _session.mood = conf

    await broadcast({"type": "mood_update", "mood": conf, "scene": scene})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
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
        print(f"[ws] {e}", flush=True)
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass


async def main():
    agent_mod.set_broadcast(broadcast)
    agent_mod.set_session_hook(set_session)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await asyncio.gather(server.serve(), agent_mod.run_agent())


if __name__ == "__main__":
    asyncio.run(main())
