# Shark Tank Pitch Simulator

Built at ACM x AIC Hack-A-Stack at SCU, May 16 2026, 6-hour sprint track. Sponsor tracks: Tencent Cloud (judge side) and GetStream Vision Agents (user side). After two rounds of stack changes, P1's scope shrank to credentials handoff and Tencent COS session logging. Runtime orchestration now lives in Vision Agents (P2).

## What this is

A live pitch simulator where a user pitches a startup against three AI judges (Cuban, O'Leary, Corcoran). Vision Agents owns the realtime loop: webcam capture, VAD, Gemini Live as the sole LLM, ElevenLabs TTS, and a websocket out to the browser frontend. P1's repo holds the credentials, the COS logging module, and the judge system prompts that P2 drops into Vision Agents.

## Stack diagram

```
User webcam + mic
    |
    v
Vision Agents (P2)
    - tencent.Edge() WebRTC transport (using P1's TRTC creds)
    - gemini.Realtime(fps=3)  sole LLM, reads webcam, judges respond
    - elevenlabs.TTS(voice_id) swapped per active judge (P1's voice IDs)
    - smart-turn VAD
    - mood processor (webcam snapshots every ~3s)
    - websocket to P3: { judge, text, audio }
    |
    | also calls: cos.upload_audio() + cos.upload_session() (P1 module)
    v
P3 browser frontend
    - split-screen layout
    - 6 pixel-art images (idle + talking per judge)
    - audio play + image swap logic
    - rolling transcript overlay
    - confidence bar (live mood)
    - feedback end screen from COS data
```

## P1's deliverables

P1 hands four things over the wall to P2:

- **TRTC credentials**: `TRTC_SDK_APP_ID` plus `TRTC_SECRET_KEY` for `tencent.Edge()` WebRTC transport.
- **ElevenLabs config**: `ELEVENLABS_API_KEY` plus the three voice IDs (`ELEVENLABS_VOICE_CUBAN`, `ELEVENLABS_VOICE_OLEARY`, `ELEVENLABS_VOICE_CORCORAN`) for `elevenlabs.TTS()`.
- **Judge system prompts**: serialized as `judges_export.json` for P2 to load directly into Vision Agents' `instructions` field. P1 does not execute these at runtime.
- **Live COS endpoints**: the `cos.py` module exposes session JSON and per-turn audio uploads with presigned URLs. P2 calls these from inside Vision Agents.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # then fill in
.venv/bin/python smoke_test.py
```

`smoke_test.py` verifies that `trtc.py`, `cos.py`, and `judges.py` still wire together cleanly. It does not need any LLM or TTS credentials, only Tencent Cloud + TRTC keys.

## Required env vars

Mirror the names in `.env.example` exactly.

| Var | Owner | Used for |
| - | - | - |
| `TENCENT_SECRET_ID` | P1 self | COS auth |
| `TENCENT_SECRET_KEY` | P1 self | COS auth |
| `TRTC_SDK_APP_ID` | P1 -> P2 | `tencent.Edge()` WebRTC transport |
| `TRTC_SECRET_KEY` | P1 -> P2 | UserSig signing for TRTC |
| `ELEVENLABS_API_KEY` | P1 -> P2 | `elevenlabs.TTS()` |
| `ELEVENLABS_VOICE_CUBAN` | P1 -> P2 | Cuban voice (default Brian, deep confident male) |
| `ELEVENLABS_VOICE_OLEARY` | P1 -> P2 | O'Leary voice (default Bill, dry authoritative) |
| `ELEVENLABS_VOICE_CORCORAN` | P1 -> P2 | Corcoran voice (default Alice, confident female) |
| `COS_BUCKET` | P1 self | Session JSON + per-turn audio bucket |
| `COS_REGION` | P1 self | Defaults to `ap-guangzhou` |

P2 provides their own `GOOGLE_API_KEY` (for `gemini.Realtime()`) and `STREAM_API_KEY` plus `STREAM_API_SECRET` (for Vision Agents itself). Those do not live in this repo.

## Handoff to P2

The full credential package, the three judge prompts, and the cos.py call signatures are bundled in [`HANDOFF_TO_P2.md`](./HANDOFF_TO_P2.md). The JSON form of the prompts lives in [`judges_export.json`](./judges_export.json). Read those two files first when wiring P1 into Vision Agents.

## Live files in this repo

- `judges.py` is the source of truth for the three judge system prompts.
- `judges_export.json` is the JSON dump P2 consumes.
- `trtc.py` generates UserSig with pure stdlib HMAC-SHA256, server-side only.
- `cos.py` handles session JSON and per-turn audio upload, plus presigned URLs.
- `smoke_test.py` checks that trtc, cos, and judges still load and behave.
- `HANDOFF_TO_P2.md` is the credential and config handoff package.
- `CLAUDE.md` is the project tracker, loaded automatically by Claude Code.
- `archive/` holds obsolete modules from the pre-pivot stack. Kept for git history only.

## What was archived and why

| File | Why archived |
| - | - |
| `hunyuan.py` | Hunyuan dropped, Gemini Live is the sole LLM |
| `tts.py` | Tencent TTS replaced by ElevenLabs |
| `ivh.py` | IVH dropped, 2D pixel-art images replace avatars (P3 builds 6 total: idle + talking per judge) |
| `chunker.py` | Existed for Tencent TTS 500-char limit, no longer needed |
| `pipeline.py` | Orchestration moved into Vision Agents (P2) |
| `mock.py` / `demo.py` | P1 no longer runs a pipeline, Vision Agents drives the loop |
| `feedback.py` | End screen moved to P3's browser frontend |

## Risks and open questions

- Does Vision Agents support hot-swapping the `instructions` field mid-session so the active judge can change without tearing down the connection? If not, the rotation logic moves into Gemini's own prompt and we lose per-judge isolation.
- smart-turn VAD compatibility under `tencent.Edge()` is unverified. Vision Agents docs cover the GetStream transport path more thoroughly than the Tencent one.
- The P2 to P3 websocket schema may need extra fields (`turn_idx`, `mood`, `session_id`) so P1's COS logging can stitch the session log together without a second source of truth.
