"""Stub main.py for frontend-only debugging.

Skips the vision-agents import (which needs Python 3.12 + cloned va-tencent)
and instead runs a fake agent loop that emits canned websocket messages so
the frontend's WS handlers, autoplay logic, and TRTC join flow can be
exercised end-to-end without the real LLM.

Usage:
  /Users/edrickchang/sharktank/.venv/bin/python main_stub.py
"""

import asyncio
import json
import time
import uuid

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import trtc as trtc_mod

load_dotenv()

app = FastAPI()
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

_ws_clients: list[WebSocket] = []
_session_id = uuid.uuid4().hex[:8]
_room_id = int(_session_id, 16)


async def broadcast(msg: dict) -> None:
    dead = []
    payload = json.dumps(msg)
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
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
        return JSONResponse({"error": str(e), "type": type(e).__name__}, status_code=500)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    print(f"[ws] client connected, total={len(_ws_clients)}", flush=True)

    # On first connect, emit the room_ready payload so the frontend can
    # mirror what the real agent does
    founder_user_id = "founder-" + uuid.uuid4().hex[:8]
    try:
        creds = trtc_mod.make_room_credentials(room_id=_room_id, user_id=founder_user_id)
        await websocket.send_text(json.dumps({
            "type": "room_ready",
            "room_id": _room_id,
            "sdk_app_id": creds["sdk_app_id"],
            "user_id": creds["user_id"],
            "user_sig": creds["user_sig"],
        }))
    except Exception as e:
        await websocket.send_text(json.dumps({"type": "error", "error": str(e)}))

    try:
        while True:
            text = await websocket.receive_text()
            # Echo mood frame ack so frontend's stream isn't a black hole
            try:
                msg = json.loads(text)
                if msg.get("type") == "mood_frame":
                    fake_mood = 0.55 + 0.1 * (time.monotonic() % 5) / 5
                    await broadcast({
                        "type": "mood_update",
                        "mood": round(fake_mood, 3),
                    })
            except Exception:
                pass
    except (WebSocketDisconnect, Exception) as e:
        print(f"[ws] client disconnected: {type(e).__name__}", flush=True)
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass


async def fake_agent_loop() -> None:
    """Emit canned judge messages every 8s to exercise frontend WS handlers."""
    await asyncio.sleep(5)
    canned = [
        ("cuban", "What's your CAC? I don't see how you scale past pilot."),
        ("oleary", "Your valuation is delusional. Royalty deal, five percent, take it or leave it."),
        ("corcoran", "Tell me about you. Who hurt you that made you start this?"),
    ]
    turn_idx = 0
    while True:
        for judge, text in canned:
            await broadcast({
                "type": "judge",
                "judge": judge,
                "mood": 0.6,
                "turn_idx": turn_idx,
            })
            await asyncio.sleep(0.5)
            await broadcast({
                "type": "transcript",
                "judge": judge,
                "text": text,
                "mood": 0.6,
                "turn_idx": turn_idx,
            })
            turn_idx += 1
            await asyncio.sleep(8)


async def main():
    print(f"\nSession: {_session_id}", flush=True)
    print(f"TRTC Room ID: {_room_id}", flush=True)
    print(f"\nOpen the frontend:\n  http://localhost:8000/?room_id={_room_id}\n", flush=True)

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(server.serve(), fake_agent_loop())


if __name__ == "__main__":
    asyncio.run(main())
