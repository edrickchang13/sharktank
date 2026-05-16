"""Shark Tank FastAPI server.

Endpoints:
  GET  /              -> serves frontend/index.html
  GET  /assets/...    -> static assets (judge images)
  GET  /credentials   -> TRTC credentials for the browser user
  WS   /ws            -> websocket broadcast channel for judge events

Runs agent.run_agent() concurrently with the HTTP server via asyncio.gather().
"""

import asyncio
import uuid

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import agent as agent_mod
import trtc as trtc_mod

app = FastAPI()

app.mount("/assets", StaticFiles(directory="assets"), name="assets")

_ws_clients: list[WebSocket] = []


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


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass


async def main():
    agent_mod.set_broadcast(broadcast)

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
