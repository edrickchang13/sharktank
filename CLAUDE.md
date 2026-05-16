# Shark Tank Simulator: Claude Project Context

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

## Secrets policy (CRITICAL)

- **NEVER paste real credentials into any tracked file.** Not in README, not in HANDOFF docs, not in code comments, not in commit messages.
- Tracked files use placeholders only: `<from P1 via secure channel>`, `<rotate via console>`, etc.
- Real values live ONLY in local `.env` which is gitignored.
- Credential handoff to teammates happens via DM / Signal / 1Password share, never via a tracked Markdown file.
- If a real secret lands in a tracked file by mistake: rotate the key immediately, then scrub. History scrub is cosmetic without rotation since GitHub indexes are scraped by bots.
- `.gitignore` blocks `.env*` (except `.env.example`), `*.pem`, `*.key`, `secrets/`, `credentials.json`, `service-account*.json`, and cloud-config dirs.

## What this project is

Shark Tank pitch simulator for ACM x AIC Hack-A-Stack at SCU, May 16 2026, 6-hour sprint track. User pitches their startup against 3 AI judge avatars modeled on Cuban, O'Leary, and Corcoran. Judges grill the user, read mood/confidence via webcam, and adapt grilling style.

Sponsor tracks: **Tencent Cloud** (TRTC transport, COS storage) + **GetStream Vision Agents** (the entire backend orchestration).

## Current stack (after three pivots)

```
User webcam + mic
    |
    v
Vision Agents (P2) -- feat/tencent-rtc branch
    - tencent.Edge() WebRTC transport (P1's TRTC creds)
    - gemini.Realtime(model="gemini-2.5-flash-native-audio-preview-12-2025", config=...)
      - sole LLM, native audio output via response_modalities=[Modality.AUDIO]
      - voice swapped per active judge: Cuban=Charon, OLeary=Orus, Corcoran=Aoede
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
| P1 | Edrick (this repo) | TRTC creds handoff, Google Gemini API key handoff, COS session logging, judge prompts as deliverable |
| P2 | Teammate | Full Vision Agents backend (tencent.Edge, gemini.Realtime with native audio, smart-turn, websocket) |
| P3 | Teammate | Browser frontend, 6 pixel-art judge images, websocket client, end screen |

## P1 deliverables to P2

1. **TRTC credentials**: `TRTC_SDK_APP_ID` + `TRTC_SECRET_KEY` from console.trtc.io
2. **Google Gemini API key**: `GOOGLE_API_KEY` from AI Studio (Gemini Live capable). Voice names (Charon/Orus/Aoede) are picked in P2's Vision Agents init, not in env.
3. **Judge system prompts**: delivered via `judges_export.json` for P2 to drop into Vision Agents `instructions` field per active judge
4. **COS endpoints at runtime**: P2 calls `cos.upload_audio(session_id, turn_idx, judge_key, audio_bytes)` and `cos.upload_session(session_id, data)` directly from the Vision Agents callback

Credentials are sent via a secure channel (DM, Signal, 1Password) and never committed. Non-secret deliverables (judge prompts, rotation logic, COS schemas) live in `judges_export.json` and `p2_reference/`.

## File map

### Live files (P1 owns)

| File | Purpose |
| - | - |
| `judges.py` | 3 judge prompts with `{mood_desc}` placeholder, `render_system_prompt`, `pick_next_judge` |
| `judges_export.json` | JSON dump of judge prompts for P2 to consume |
| `trtc.py` | Pure-stdlib UserSig generation, `generate_user_sig`, `make_room_credentials` |
| `cos.py` | Session JSON + per-turn audio upload with presigned URLs |
| `smoke_test.py` | 10 tests covering judges, trtc, cos, json export, writing style |
| `p2_reference/vision_agents_starter.py` | Runnable starter file P2 forks for the Vision Agents backend |
| `README.md` | Quickstart and architecture overview |
| `.env.example` | Required env vars (TRTC, Google Gemini, COS) |
| `requirements.txt` | 2 deps: cos-python-sdk-v5, python-dotenv |

### Archived (kept for git history, do not import)

| File | Why archived |
| - | - |
| `archive/hunyuan.py` | Hunyuan dropped, Gemini Live is sole LLM |
| `archive/tts.py` | Tencent TTS dropped, gemini.Realtime now emits audio natively (in P2's domain) |
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
| `GOOGLE_API_KEY` | aistudio.google.com | Handoff to P2 for gemini.Realtime() (LLM + native audio) |
| `GEMINI_MODEL` | constant | Handoff to P2, default `gemini-2.5-flash-native-audio-preview-12-2025` |
| `COS_BUCKET` / `COS_REGION` | COS console | P1 session logging |

## Architecture decisions log (most recent first)

1. **20:00** Separate TTS plugin dropped. Vision Agents gemini.Realtime ships with response_modalities=[AUDIO] by default. Single API call produces both judge text and audio. Per-judge voice swap via voice_name param (Charon/Orus/Aoede).
2. **19:44** Hunyuan dropped entirely. Gemini Live becomes sole LLM. Judge prompts move to Vision Agents `instructions` field. P1 scope reduces to creds handoff + COS logging.
3. **19:30** Tencent IVH dropped (needs purchased avatar key). HeyGen dropped. P3 builds custom 2D pixel images (6 total). Tencent TTS dropped, replaced by an external TTS plugin (later dropped, see entry 1). Websocket schema locked: `{ judge, text, audio }`.
4. **18:43** Original 3-person split: P1 = all Tencent (IVH, TRTC, Hunyuan, TTS, COS), P2 = GetStream, P3 = OpenCV/pyaudio frontend.

## Known gotchas

- **Gemini Live audio format**: native audio outputs 24kHz PCM, not MP3. P3 frontend may need to handle PCM or P2 transcodes.
- **Vision Agents agent.llm hot-swap**: unconfirmed whether Vision Agents supports reassigning `agent.llm` mid-session. May need agent reconstruction per judge change.
- **TRTC SDKSecretKey != CAM SecretKey**: two separate consoles, two separate credentials.
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
