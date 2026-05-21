# Shark Tank Pitch Simulator

A live pitch simulator where a user pitches a startup against three AI judges modeled on Mark Cuban, Kevin O'Leary, and Barbara Corcoran. The judges grill the founder over webcam and mic, read mood and confidence from the video feed, and adapt their grilling style in real time.

1st Place, Tencent Sprint Track, ACM x AIC Hack-A-Stack at SCU, May 16 2026 (6-hour sprint track).

## What this is

This repo is the P1 slice of a three-person build. Sponsor tracks: Tencent Cloud on the judge side, GetStream Vision Agents on the user side. After two rounds of stack changes, P1's scope settled on three things:

1. Generating and handing TRTC credentials to P2.
2. Defining the three judge system prompts and the turn-rotation logic.
3. Logging each session to Tencent COS (session JSON plus per-turn judge audio).

Runtime orchestration (webcam capture, voice activity detection, the LLM, the websocket to the browser) lives in Vision Agents, owned by P2. This repo holds no event loop. It provides modules P2 calls and credentials P2 consumes.

## Architecture

```
User webcam + mic
    |
    v
Vision Agents (P2)
    - tencent.Edge() WebRTC transport, using P1's TRTC creds
    - gemini.Realtime(model="gemini-2.5-flash-native-audio-preview-12-2025")
        - sole LLM, sole TTS, native 24kHz PCM audio output
        - voice swapped per active judge (Charon / Orus / Aoede)
        - reads webcam frames for mood scoring
    - smart-turn VAD
    - mood processor, webcam snapshots every ~3s
    - websocket to P3: { judge, text, audio }
    |
    | also calls cos.upload_audio() and cos.upload_session() (P1 module)
    v
P3 browser frontend
    - split-screen layout, webcam left, judge right
    - 6 pixel-art images, idle and talking per judge
    - audio playback plus image swap on each websocket message
    - rolling transcript overlay
    - live confidence bar driven by mood score
    - feedback end screen built from COS session data
```

## Modules in this repo

| File | What it does |
| - | - |
| `judges.py` | Defines the three judges as frozen dataclasses, each with a system prompt containing a `{mood_desc}` slot. `render_system_prompt(judge_key, mood)` fills that slot from a 0-1 mood float. `pick_next_judge(turn_index, mood)` chooses who speaks next: Cuban opens turn 0, Corcoran takes any turn where mood drops below 0.4, otherwise the rotation cycles O'Leary, Corcoran, Cuban. |
| `judges_export.json` | Serialized dump of the judge prompts (schema 2.0) for P2 to load into Vision Agents. Each judge entry carries its `gemini_voice` name. Also includes the mood-descriptor bands, the rotation rules, and the list of safe Gemini voices. |
| `trtc.py` | Generates TRTC `UserSig` tokens with pure stdlib HMAC-SHA256, server-side only, no Tencent SDK. `generate_user_sig(user_id, expire_seconds)` produces a signed, zlib-compressed, base64 token (default 24h expiry, capped at 90 days). `make_room_credentials(room_id, user_id)` bundles everything a TRTC client needs to join a room. |
| `cos.py` | Tencent COS client for session logging. `upload_session(session_id, data)` writes the full session log as JSON. `upload_audio(session_id, turn_idx, judge_key, audio_bytes)` writes one judge audio response. Both return a 1-hour presigned download URL. `list_session_keys(session_id)` lists all objects under a session. The client is lazily initialized once and reused under a lock. |
| `smoke_test.py` | 10 stdlib tests over `judges`, `trtc`, and `cos`: prompt rendering, mood-descriptor extremes, judge rotation, UserSig generation, env-var validation, expiry validation, the JSON export shape, and an em-dash check. Run with `python smoke_test.py`, no pytest needed. |
| `p2_reference/vision_agents_starter.py` | Runnable starter file P2 forks to wire Vision Agents, Gemini Live, and the COS callbacks together. |
| `CLAUDE.md` | Project tracker and decisions log, loaded automatically by Claude Code. |
| `archive/` | Obsolete modules from the pre-pivot stack. Kept for git history only, do not import. |

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in credentials
.venv/bin/python smoke_test.py   # expect 10 passed, 0 failed
```

`smoke_test.py` does not need any LLM or TTS credentials. It exercises the TRTC signer with fake keys and checks that `cos.py` raises cleanly when COS env vars are missing.

## Required env vars

Mirror the names in `.env.example` exactly.

| Var | Owner | Used for |
| - | - | - |
| `TENCENT_SECRET_ID` | P1 self | COS auth |
| `TENCENT_SECRET_KEY` | P1 self | COS auth |
| `TRTC_SDK_APP_ID` | P1 to P2 | `tencent.Edge()` WebRTC transport |
| `TRTC_SECRET_KEY` | P1 to P2 | UserSig signing for TRTC |
| `GOOGLE_API_KEY` | P1 to P2 | `gemini.Realtime()` native audio LLM and TTS |
| `GEMINI_MODEL` | P1 to P2 | Defaults to `gemini-2.5-flash-native-audio-preview-12-2025` |
| `COS_BUCKET` | P1 self | Session JSON and per-turn audio bucket |
| `COS_REGION` | P1 self | Defaults to `ap-guangzhou` |

`TRTC_SECRET_KEY` is the TRTC SDKSecretKey from console.trtc.io. It is not the same as the CAM `TENCENT_SECRET_KEY`. Two separate consoles, two separate credentials.

P2 supplies their own `STREAM_API_KEY` and `STREAM_API_SECRET` for Vision Agents. Those never live in this repo.

## Handoff to P2

P1 hands four things over the wall to P2:

- **TRTC credentials.** `TRTC_SDK_APP_ID` and `TRTC_SECRET_KEY` for the `tencent.Edge()` WebRTC transport.
- **Google Gemini API key.** `GOOGLE_API_KEY` from AI Studio, capable of driving `gemini.Realtime()` with native audio. The judge voices (Cuban = Charon, O'Leary = Orus, Corcoran = Aoede) are set in P2's Vision Agents init, not in env vars.
- **Judge system prompts.** Serialized as `judges_export.json`. P2 loads the prompt for the active judge into the Vision Agents `system_instruction` field. P1 does not execute these at runtime.
- **Live COS endpoints.** P2 calls `cos.upload_audio()` and `cos.upload_session()` directly from inside Vision Agents.

Credentials are never committed. P1 sends them to P2 over a secure channel (DM, Signal, 1Password share). P2 pastes them into their own gitignored `.env`. P2 can fork `p2_reference/vision_agents_starter.py` as a starting point.

## Archived files

| File | Why archived |
| - | - |
| `hunyuan.py` | Hunyuan dropped, Gemini Live is the sole LLM |
| `tts.py` | Tencent TTS dropped, Gemini Live produces audio natively |
| `ivh.py` | IVH dropped, P3 builds 2D pixel-art images instead (6 total) |
| `chunker.py` | Existed for the Tencent TTS 500-char limit, no longer needed |
| `pipeline.py` | Orchestration moved into Vision Agents (P2) |
| `mock.py`, `demo.py` | P1 no longer runs a pipeline, Vision Agents drives the loop |
| `feedback.py` | End screen moved to P3's browser frontend |

## Open questions

- Whether Vision Agents can hot-swap `agent.llm` mid-session so the active judge changes without tearing down the TRTC connection or the turn-detection state. If not, plan B is reconstructing the agent per judge change, costing 1-2 seconds of dead air.
- smart-turn VAD compatibility under `tencent.Edge()` on the `feat/tencent-rtc` branch is unverified. Fallback is `silero.VAD()`.
- Gemini Live emits 24kHz PCM. Open whether P3's frontend plays raw PCM through `AudioBufferSourceNode` directly, or whether the websocket layer transcodes to MP3 first. PCM keeps latency lower, MP3 plays trivially in `<audio>`.
- The P2-to-P3 websocket schema may need extra fields (`turn_idx`, `mood`, `session_id`) so P1's COS logging can stitch the session log together from one source of truth.
</content>
</invoke>
