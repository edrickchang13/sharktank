# Shark Tank Simulator — Claude Project Context

This file is loaded automatically when Claude Code runs in this repo. Read it first.

## Operating directive

**Always run as many parallel agents as you can to implement features and resolve issues.** When a task can be decomposed into independent file writes, doc fetches, or research questions, spawn parallel Agent tool calls in a single message. Sequential execution is only acceptable when one task strictly depends on another's output.

Concretely:
- A request like "add module X and update Y and write tests" should fan out to 3 parallel agents
- Doc lookups, code generation for separate files, and research tasks always run in parallel
- The orchestrator (you) writes glue code and integration after agents return

## Writing style

- No em-dashes anywhere in code, prompts, or docs
- Plain conversational tone for anything teammates will paste or read
- No Co-Authored-By trailers in commits
- Use commas, periods, parentheses, or split sentences instead of em-dashes

## What this project is

Shark Tank pitch simulator for ACM x AIC Hack-A-Stack at SCU, May 16 2026, 6-hour sprint track. User pitches their startup against 3 AI judge avatars modeled on Cuban, O'Leary, and Corcoran. Judges grill the user, read mood/confidence via webcam, and adapt grilling style.

Sponsor tracks: **Tencent Cloud** (TRTC transport, COS storage) + **GetStream Vision Agents** (the entire backend orchestration).

## Current stack (after two pivots)

```
User webcam + mic
    |
    v
Vision Agents (P2) -- feat/tencent-rtc branch
    - tencent.Edge() WebRTC transport (P1's TRTC creds)
    - gemini.Realtime(fps=3) -- sole LLM, reads webcam, generates judge responses
    - elevenlabs.TTS(voice_id) -- swapped per active judge (P1's voice IDs)
    - smart-turn VAD
    - mood processor (snapshots every ~3s)
    - websocket to P3: { judge, text, audio }
    - on_turn_end calls cos.upload_audio + cos.upload_session (P1 module)
    |
    v
P3 browser frontend
    - split-screen layout (webcam left, judge right)
    - 6 pixel-art images (idle + talking per judge)
    - audio play + image swap on websocket message
    - rolling transcript overlay
    - live confidence bar (from get_mood)
    - feedback end screen from COS data
```

## Team (final scope)

| Role | Owner | Scope |
| - | - | - |
| P1 | Edrick (this repo) | TRTC creds handoff, ElevenLabs creds handoff, COS session logging, judge prompts as deliverable |
| P2 | Teammate | Full Vision Agents backend (tencent.Edge, gemini.Realtime, elevenlabs.TTS, smart-turn, websocket) |
| P3 | Teammate | Browser frontend, 6 pixel-art judge images, websocket client, end screen |

## P1 deliverables to P2

1. **TRTC credentials**: `TRTC_SDK_APP_ID` + `TRTC_SECRET_KEY` from console.trtc.io
2. **ElevenLabs credentials**: `ELEVENLABS_API_KEY` + 3 voice IDs (Cuban/O'Leary/Corcoran)
3. **Judge system prompts**: delivered via `judges_export.json` for P2 to drop into Vision Agents `instructions` field per active judge
4. **COS endpoints at runtime**: P2 calls `cos.upload_audio(session_id, turn_idx, judge_key, audio_bytes)` and `cos.upload_session(session_id, data)` directly from the Vision Agents callback

The full handoff doc is in `HANDOFF_TO_P2.md`.

## File map

### Live files (P1 owns)

| File | Purpose |
| - | - |
| `judges.py` | 3 judge prompts with `{mood_desc}` placeholder, `render_system_prompt`, `pick_next_judge` |
| `judges_export.json` | JSON dump of judge prompts for P2 to consume |
| `trtc.py` | Pure-stdlib UserSig generation, `generate_user_sig`, `make_room_credentials` |
| `cos.py` | Session JSON + per-turn audio upload with presigned URLs |
| `smoke_test.py` | 10 tests covering judges, trtc, cos, json export, writing style |
| `HANDOFF_TO_P2.md` | Credential and config handoff package |
| `README.md` | Quickstart and architecture overview |
| `.env.example` | Required env vars with prefilled voice IDs |
| `requirements.txt` | 2 deps: cos-python-sdk-v5, python-dotenv |

### Archived (kept for git history, do not import)

| File | Why archived |
| - | - |
| `archive/hunyuan.py` | Hunyuan dropped, Gemini Live is sole LLM |
| `archive/tts.py` | Tencent TTS replaced by ElevenLabs (in P2's domain) |
| `archive/ivh.py` | IVH dropped, 2D pixel images instead (P3 owns) |
| `archive/chunker.py` | Existed for Tencent TTS 500-char limit, no longer needed |
| `archive/pipeline.py` | Orchestration moved to Vision Agents |
| `archive/mock.py` | No longer needed, Vision Agents drives the loop |
| `archive/demo.py` | Same |
| `archive/feedback.py` | End screen moved to P3 browser frontend |

## Required env vars

See `.env.example`. Summary:

| Var | Source | Used by |
| - | - | - |
| `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | console.cloud.tencent.com/cam | COS only (Hunyuan and TTS dropped) |
| `TRTC_SDK_APP_ID` / `TRTC_SECRET_KEY` | console.trtc.io | Handoff to P2 for tencent.Edge() |
| `ELEVENLABS_API_KEY` | elevenlabs.io dashboard | Handoff to P2 for elevenlabs.TTS() |
| `ELEVENLABS_VOICE_CUBAN` / `_OLEARY` / `_CORCORAN` | ElevenLabs voice library | Handoff to P2, prefilled with Brian/Bill/Alice |
| `COS_BUCKET` / `COS_REGION` | COS console | P1 session logging |

## Architecture decisions log (most recent first)

1. **19:44** Hunyuan dropped entirely. Gemini Live becomes sole LLM. Judge prompts move to Vision Agents `instructions` field. P1 scope reduces to creds handoff + COS logging.
2. **19:30** Tencent IVH dropped (needs purchased avatar key). HeyGen dropped. P3 builds custom 2D pixel images (6 total). Tencent TTS dropped, ElevenLabs replaces it. Websocket schema locked: `{ judge, text, audio }`.
3. **18:43** Original 3-person split: P1 = all Tencent (IVH, TRTC, Hunyuan, TTS, COS), P2 = GetStream, P3 = OpenCV/pyaudio frontend.

## Known gotchas

- **ElevenLabs free tier**: 10,000 chars/month. Roughly 15-17 judge turns. Bump to Starter ($5/30k chars) if demoing more.
- **ElevenLabs commercial use**: requires Starter+. Free tier is non-commercial.
- **ElevenLabs voice ID sunset**: default voice IDs deprecate Dec 31 2026, fine for the demo.
- **TRTC SDKSecretKey != CAM SecretKey**: two separate consoles, two separate credentials.
- **Vision Agents instructions hot-swap**: unconfirmed whether Vision Agents supports changing `instructions` mid-session. May need a fresh agent per judge change.
- **smart-turn VAD under tencent.Edge**: unconfirmed compatibility on the feat/tencent-rtc branch.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# fill in credentials in .env
.venv/bin/python smoke_test.py  # expect 10 passed, 0 failed
```

## Quality bar

- All live modules pass `smoke_test.py`
- Every module under 120 lines
- Type annotations on public function signatures
- One docstring per public function, no chatty internals
- No em-dashes anywhere

## Git workflow

- Commits authored locally with `Edrick Chang <matxhedog2@gmail.com>`
- No Co-Authored-By trailer
- Push to `edrickchang13/sharktank` requires explicit in-chat approval
- Conventional commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`
