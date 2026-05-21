# Shark Tank Simulator: Claude Project Context

This file is loaded automatically when Claude Code runs in this repo. Read it first.

## Operating directive

**Always run as many parallel agents as you can to implement features and resolve issues.** When a task can be decomposed into independent file writes, doc fetches, or research questions, spawn parallel Agent tool calls in a single message. Sequential execution is only acceptable when one task strictly depends on another's output.

Concretely:
- A request like "add module X and update Y and write tests" should fan out to 3 parallel agents
- Doc lookups, code generation for separate files, and research tasks always run in parallel
- The orchestrator (you) writes glue code and integration after agents return

## Live debug loop with Chrome MCP

When the user asks to test the website or debug a UI/runtime issue, do not just describe the steps. Take over and run the loop yourself:

1. **Start the local server** (or `ssh -L 8000:localhost:8000` to Abraham's DGX Spark if that is the testbed). Confirm it is listening before opening a browser.
2. **Open the page in Chrome via `mcp__Claude_in_Chrome__*`** — DOM aware, much faster than pixel clicking. Computer-use cannot click into Chrome (tier read), so use Chrome MCP for the actual interaction. Computer-use screenshots are still useful for visual verification.
3. **Read console + network errors** with `mcp__Claude_in_Chrome__read_console_messages` and `mcp__Claude_in_Chrome__read_network_requests`. These are the truth source for what is breaking.
4. **Capture findings in a tight scratchpad** in this conversation: error message, file:line, root cause hypothesis. Do not push to KB or commit yet.
5. **Fix in Claude Code** — open the relevant file, edit, save. Run `smoke_test.py` to confirm no regressions if the change touches `judges.py`, `trtc.py`, `cos.py`.
6. **Reload the page in Chrome MCP** and re-check console. Repeat from step 3.
7. **When the bug is fixed**, log a one-line entry in the CLAUDE.md decisions log with the timestamp and the root cause. Commit. Push only if the user said push.
8. **Stop the loop** when the user says stop, when the page renders the demo flow end to end, or when you hit something that genuinely requires the user (credentials, browser permissions they have to grant, hardware on Abraham's machine).

Guardrails:
- Do not click links the user did not ask you to follow. The page is trusted but third-party redirects are not.
- Do not modify Abraham's `agent.py` or `frontend/index.html` without flagging to the user first. He owns them.
- If the bug is in this repo's code (`cos.py`, `trtc.py`, `judges.py`, `judges_export.json`), fix directly.
- If the bug is in `requirements.txt`, `.gitignore`, or env handling, fix directly.
- Iteration cap: 8 rounds. If still broken after 8, write a status summary and ask the user for direction rather than grinding.

## Writing style

- No em-dashes anywhere in code, prompts, or docs
- Plain conversational tone for anything teammates will paste or read
- No Co-Authored-By trailers in commits
- Use commas, periods, parentheses, or split sentences instead of em-dashes

## Secrets policy (CRITICAL)

- **NEVER paste real credentials into any tracked file.** Not in README, not in HANDOFF docs, not in code comments, not in commit messages.
- Tracked files use placeholders only: `<from a secure channel>`, `<rotate via console>`, etc.
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
Vision Agents backend -- feat/tencent-rtc branch
    - tencent.Edge() WebRTC transport (this repo's TRTC creds)
    - gemini.Realtime(model="gemini-2.5-flash-native-audio-preview-12-2025", config=...)
      - sole LLM, native audio output via response_modalities=[Modality.AUDIO]
      - voice swapped per active judge: Cuban=Charon, OLeary=Orus, Corcoran=Aoede
    - smart-turn VAD
    - mood processor (snapshots every ~3s)
    - websocket to the browser frontend: { judge, text, audio }
    - on_turn_end calls cos.upload_audio + cos.upload_session (this repo's module)
    |
    v
Browser frontend
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
| Backend repo | Edrick (this repo) | TRTC creds handoff, Google Gemini API key handoff, COS session logging, judge prompts as deliverable |
| Vision Agents backend | Teammate | Full Vision Agents backend (tencent.Edge, gemini.Realtime with native audio, smart-turn, websocket) |
| Browser frontend | Teammate | Browser frontend, 6 pixel-art judge images, websocket client, end screen |

## Deliverables to the Vision Agents backend

1. **TRTC credentials**: `TRTC_SDK_APP_ID` + `TRTC_SECRET_KEY` from console.trtc.io
2. **Google Gemini API key**: `GOOGLE_API_KEY` from AI Studio (Gemini Live capable). Voice names (Charon/Orus/Aoede) are picked in the Vision Agents backend init, not in env.
3. **Judge system prompts**: delivered via `judges_export.json` for the Vision Agents backend to drop into the Vision Agents `instructions` field per active judge
4. **COS endpoints at runtime**: the Vision Agents backend calls `cos.upload_audio(session_id, turn_idx, judge_key, audio_bytes)` and `cos.upload_session(session_id, data)` directly from the Vision Agents callback

Credentials are sent via a secure channel (DM, Signal, 1Password) and never committed. Non-secret deliverables (judge prompts, rotation logic, COS schemas) live in `judges_export.json` and `reference/`.

## File map

### Live files (this repo owns)

| File | Purpose |
| - | - |
| `judges.py` | 3 judge prompts with `{mood_desc}` placeholder, `render_system_prompt`, `pick_next_judge` |
| `judges_export.json` | JSON dump of judge prompts for the Vision Agents backend to consume |
| `trtc.py` | Pure-stdlib UserSig generation, `generate_user_sig`, `make_room_credentials` |
| `cos.py` | Session JSON + per-turn audio upload with presigned URLs |
| `smoke_test.py` | 10 tests covering judges, trtc, cos, json export, writing style |
| `reference/vision_agents_starter.py` | Runnable starter file forked for the Vision Agents backend |
| `README.md` | Quickstart and architecture overview |
| `.env.example` | Required env vars (TRTC, Google Gemini, COS) |
| `requirements.txt` | 2 deps: cos-python-sdk-v5, python-dotenv |

### Archived (kept for git history, do not import)

| File | Why archived |
| - | - |
| `archive/hunyuan.py` | Hunyuan dropped, Gemini Live is sole LLM |
| `archive/tts.py` | Tencent TTS dropped, gemini.Realtime now emits audio natively (in the Vision Agents backend's domain) |
| `archive/ivh.py` | IVH dropped, 2D pixel images instead (the browser frontend owns this) |
| `archive/chunker.py` | Existed for Tencent TTS 500-char limit, no longer needed |
| `archive/pipeline.py` | Orchestration moved to Vision Agents |
| `archive/mock.py` | No longer needed, Vision Agents drives the loop |
| `archive/demo.py` | Same |
| `archive/feedback.py` | End screen moved to the browser frontend |

## Required env vars

See `.env.example`. Summary:

| Var | Source | Used by |
| - | - | - |
| `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | console.cloud.tencent.com/cam | COS only (Hunyuan and TTS dropped) |
| `TRTC_SDK_APP_ID` / `TRTC_SECRET_KEY` | console.trtc.io | Handoff to the Vision Agents backend for tencent.Edge() |
| `GOOGLE_API_KEY` | aistudio.google.com | Handoff to the Vision Agents backend for gemini.Realtime() (LLM + native audio) |
| `GEMINI_MODEL` | constant | Handoff to the Vision Agents backend, default `gemini-2.5-flash-native-audio-preview-12-2025` |
| `COS_BUCKET` / `COS_REGION` | COS console | This repo's session logging |

## Architecture decisions log (most recent first)

1. **22:40** Ran Chrome MCP debug loop against p2-agent branch in a git worktree. Four iterations. Findings: (a) Abraham's `requirements.txt` is missing `websockets` (or `uvicorn[standard]`) — frontend hits WS 404 and reconnect-loops every 2s without it. (b) `assets/judges/*.png` are 0-byte placeholders, browser shows broken-image icon until replaced; generated colored stand-ins as `main_stub` smoke test fixture. (c) Frontend has NO `getUserMedia` or `mood_frame` capture — mood is captured server-side via `cv2.VideoCapture(0)` in `agent.py`, meaning only the machine running `main.py` sees a webcam. (d) Local webcam panel is empty by design (TRTC is receive-only on the browser side, mic goes through WebRTC track to Gemini). (e) After clicking Join Pitch Room and granting clicks, TRTC and WS both go green, judge image swaps, transcript updates, confidence bar moves. End-to-end visible UI works with a stub backend.
2. **20:49** Vision Agents backend integration findings logged. `tencent.Edge()` unstable on feat/tencent-rtc, the Vision Agents backend uses `getstream.Edge()` as actual transport. `gemini.Realtime()` silently disables ElevenLabs and SmartTurn (Gemini owns STT/TTS/VAD). Stream SFU requires browser-first join (agent times out against empty room). `asyncio.run_in_executor(None, input)` fails under `uv run`. The Vision Agents backend polls Stream REST API for participant presence.
2. **20:00** Separate TTS plugin dropped. Vision Agents gemini.Realtime ships with response_modalities=[AUDIO] by default. Single API call produces both judge text and audio. Per-judge voice swap via voice_name param (Charon/Orus/Aoede).
3. **19:44** Hunyuan dropped entirely. Gemini Live becomes sole LLM. Judge prompts move to Vision Agents `instructions` field. This repo's scope reduces to creds handoff + COS logging.
4. **19:30** Tencent IVH dropped (needs purchased avatar key). HeyGen dropped. The browser frontend builds custom 2D pixel images (6 total). Tencent TTS dropped, replaced by an external TTS plugin (later dropped, see entry 2). Websocket schema locked: `{ judge, text, audio }`.
5. **18:43** Original 3-person split: this repo did all Tencent (IVH, TRTC, Hunyuan, TTS, COS), the Vision Agents backend did GetStream, the browser frontend did the OpenCV/pyaudio frontend.

## Known gotchas

- **uvicorn needs `websockets`**: bare uvicorn refuses WS upgrades, returns 404 on `GET /ws`. Install `websockets` or use `uvicorn[standard]`. Abraham's `requirements.txt` on p2-agent is missing this.
- **Mood capture is server-side**: `agent.py` uses `cv2.VideoCapture(0)` on the host running `main.py`. Browser does NOT send webcam frames. When the agent runs on DGX Spark and the user runs the browser on a Mac, the user's face is not visible to the mood model. Single-machine demos work, remote-agent demos do not get user mood.
- **Local-video panel in frontend is intentionally empty**: browser TRTC join is receive-only, no local publish. Mic goes through WebRTC audio track to Gemini Live. The "YOU" panel label is misleading; consider relabeling.
- **Judge images are 0-byte placeholders on p2-agent**: the browser frontend replaces with pixel art. For testing, generate temporary colored PNGs (see scripts in worktree).
- **Transport fallback**: `tencent.Edge()` unstable on feat/tencent-rtc as of May 16. Primary transport in practice is `getstream.Edge()` with Stream API key. Tencent creds still attempted first.
- **gemini.Realtime takes over STT/TTS/VAD**: do not add `smart_turn`, `elevenlabs`, or any STT/TTS plugin to the agent config. They get silently disabled. Gemini handles all voice internally with 24kHz PCM output.
- **Stream SFU join order**: browser must join the call first. Agent that joins first times out the room. The Vision Agents backend polls Stream REST API for participant presence and joins after.
- **No stdin under `uv run`**: `asyncio.run_in_executor(None, input)` raises EOFError. Use REST polling instead of input prompts.
- **Gemini Live audio format**: native audio outputs 24kHz PCM, not MP3. The browser frontend may need to handle PCM or the Vision Agents backend transcodes.
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
