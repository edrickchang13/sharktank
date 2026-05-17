# Pitch Tank: Claude Project Context

This file is loaded automatically when Claude Code runs in this repo. Read it first.

## ABSOLUTE SECRETS RULE (READ THIS FIRST)

**NEVER echo, print, paste, log, or commit any API key, secret key, JWT, or credential VALUE. Anywhere. Not in chat. Not in commit messages. Not in tracked files. Not in comments. Not in error messages. Not even partially.**

When you need to talk about a credential, refer to it by its environment variable NAME only:
- ALLOWED: `GOOGLE_API_KEY` is set, `TRTC_SECRET_KEY` got rotated, `.env` has 7 of 8 vars filled
- ALLOWED: prefix-only verification (`prefix: AIza`, `len=39`, `starts with AKID`)
- FORBIDDEN: `GOOGLE_API_KEY=AIzaSyXxxx...` (full value, even leaked/dead ones)
- FORBIDDEN: pasting `<some-token>` style placeholders that contain real key fragments
- FORBIDDEN: `curl -H "Authorization: Bearer eyJ..."` with a real token
- FORBIDDEN: writing the key into a doc the user might paste to a teammate

Patterns to detect and refuse:
- Anything matching `AIza[0-9A-Za-z_-]{30,}` (Google API key)
- Anything matching `AKID[0-9A-Za-z_-]{20,}` (Tencent CAM SecretId)
- Anything matching `sk-[a-zA-Z0-9_-]{20,}` (OpenAI / Anthropic style)
- Anything matching `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.` (JWT)
- 32-128 char hex strings appearing next to `_key`, `_secret`, `_token`

If the user pastes a key in chat, ALWAYS:
1. Treat it as compromised the moment it lands in chat
2. Tell them to rotate immediately
3. Save it to `.env` (gitignored) via a Write tool call, NEVER echo the value back in your response or in a Bash `--env` argument
4. Confirm with prefix-only or length-only verification

When verifying env state, use this pattern:
```python
keys = ['GOOGLE_API_KEY', 'LIVEKIT_API_KEY', ...]
for k in keys:
    v = os.environ.get(k, '')
    print(f'  {k}: {("SET (len=" + str(len(v)) + ")") if v else "EMPTY"}')
```
This shows whether each is set without leaking the value.

When writing commit messages or docs:
- Talk about WHAT changed and WHY, not WHICH key
- Never include the literal key in a commit body, even to document rotation
- For handoff docs (sharing to teammates): use `<from P1 via secure channel>` placeholders only

If you find a leaked value already in tracked content or history:
1. Stop everything else
2. Tell the user the EXACT commit hashes containing the leak
3. Ask them to rotate the key
4. Then offer `git filter-repo` history scrub + force-push

`.gitignore` already blocks `.env*` (except `.env.example`), `*.pem`, `*.key`, `*.p12`, `*.pfx`, `secrets/`, `credentials.json`, `service-account*.json`, `.aws/`, `.gcp/`, `.azure/`. Real values live ONLY in local `.env`. Handoff to teammates happens via DM / Signal / 1Password, never through this repo.

## Operating directive

**Always run as many parallel agents as you can to implement features and resolve issues.** When a task can be decomposed into independent file writes, doc fetches, or research questions, spawn parallel Agent tool calls in a single message. Sequential execution is only acceptable when one task strictly depends on another's output.

Concretely:
- A request like "add module X and update Y and write tests" should fan out to 3 parallel agents
- Doc lookups, code generation for separate files, and research tasks always run in parallel
- The orchestrator (you) writes glue code and integration after agents return

## Live debug loop with Chrome MCP

When the user asks to test the website or debug a UI/runtime issue, do not just describe the steps. Take over and run the loop yourself:

1. Start the local server (`docker compose up -d --build` for the two-service stack: `sharktank-web` + `sharktank-worker`). Confirm the worker registered with LiveKit before opening a browser.
2. Open the page in Chrome via `mcp__Claude_in_Chrome__*`. DOM aware, fast. Computer-use is read-tier on browsers, so use Chrome MCP for clicks and JS eval.
3. Read console + network errors with `mcp__Claude_in_Chrome__read_console_messages` and `mcp__Claude_in_Chrome__read_network_requests`. These are the truth source.
4. Capture findings tightly in chat: error message, file:line, root cause hypothesis. Do not push to KB or commit yet.
5. Fix in Claude Code, save. Run `python -c "import ast; ast.parse(open('main.py').read())"` on edited Python files to catch syntax errors before rebuilding.
6. Reload Chrome and re-check console. Repeat from step 3.
7. When the bug is fixed, log a one-line entry in the decisions log below. Commit. Push only if the user said push.
8. Stop the loop when the user says stop, when the demo flow works end to end, or when you hit something that genuinely requires the user (credentials, browser permissions, hardware).

Iteration cap: 8 rounds. If still broken after 8, write a status summary and ask the user for direction rather than grinding.

## Writing style

- No em-dashes anywhere in code, prompts, or docs
- Plain conversational tone for anything teammates will paste or read
- No Co-Authored-By trailers in commits
- Use commas, periods, parentheses, or split sentences instead of em-dashes

## What this project is

Pitch Tank, a Shark Tank-style pitch simulator for ACM x AIC Hack-A-Stack at SCU, May 16 2026, 6-hour sprint track. User pitches their startup against AI judge avatars modeled on Cuban, O'Leary, and Corcoran. One judge per LiveKit session (picked from the founder's `judge_key` participant attribute). Judge speaks via Gemini Live native audio. Optional LemonSlice avatar provides a talking-head video track.

## Current stack

```
Browser (livekit-client UMD)
    -> Room.connect to LiveKit Cloud
    -> publishes mic + camera + optional screen share
    -> WebSocket to FastAPI /ws for mood frames + speaking/transcript fanout

FastAPI web service (main.py)
    -> GET / serves frontend/index.html
    -> GET /token mints JWT AND dispatches the judge agent via
       LiveKitAPI.agent_dispatch.create_dispatch(agent_name="shark-tank-judge")
    -> POST /session_log forwards to Tencent COS
    -> WS /ws: receives mood_frame, calls Gemini Vision, broadcasts mood_update

LiveKit Agent worker (agent.py)
    -> AgentServer.rtc_session(agent_name="shark-tank-judge")
    -> entrypoint: read participant.attributes.judge_key, build JudgeAgent
       with google.beta.realtime.RealtimeModel (audio-only)
    -> if LEMONSLICE_API_KEY: lemonslice.AvatarSession on top
    -> on shutdown: upload transcript history to COS
```

## Team

| Role | Owner | Scope |
| - | - | - |
| P1 | Edrick (this repo) | TRTC creds (now unused), Google + LiveKit + LemonSlice + COS keys, judge prompts, deployment |
| P2 | Abraham | Original Vision Agents / TRTC backend (now superseded by the LiveKit pivot on this branch) |
| P3 | Teammate | Browser frontend polish, 2D pixel art, end screen |

## File map

| File | Purpose |
| - | - |
| `agent.py` | LiveKit Agent worker. `python agent.py start` runs the dispatched worker |
| `main.py` | FastAPI web service. Token issuance + dispatch + WS + COS forwarding |
| `judges.py` | 3 judge prompts with `{mood_desc}` placeholder, `render_system_prompt`, `pick_next_judge` |
| `judges_export.json` | JSON dump (Cuban/O'Leary/Corcoran with Gemini voice mappings) |
| `cos.py` | Tencent COS upload helpers (thread-safe lazy init, presigned URLs) |
| `frontend/index.html` | LiveKit-based single-page client with sentence-level transcript |
| `Dockerfile` | Single image; CMD overridden per service in docker-compose |
| `docker-compose.yml` | Two services: `web` and `worker` sharing the same image and `.env` |
| `Makefile` | Common commands (`make up`, `make logs`, `make down`) |
| `requirements.txt` | livekit-agents + lemonslice plugin + fastapi + cos-python-sdk-v5 + google-genai |
| `archive/` | Pre-pivot artifacts kept for git history only |

## Required env vars

All live in `.env` only. Never tracked.

| Var | Source | Used by |
| - | - | - |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` / `LIVEKIT_URL` | LiveKit Cloud dashboard | Both services (token mint + worker registration + dispatch) |
| `GOOGLE_API_KEY` | aistudio.google.com | Web mood vision + agent's Gemini Live session |
| `GOOGLE_API_KEY_V2` | aistudio.google.com (separate project recommended) | Agent's Gemini Live; web mood falls back to V1 if unset |
| `GEMINI_MODEL` | constant | Default `gemini-2.5-flash-native-audio-preview-12-2025` |
| `LEMONSLICE_API_KEY` | lemonslice.com dashboard | Optional. Agent runs audio-only if empty |
| `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | console.cloud.tencent.com/cam | COS only |
| `COS_BUCKET` / `COS_REGION` | COS console | Session logging |

## Architecture decisions log (most recent first)

1. **2026-05-16 late** Full pivot to LiveKit Agents + LemonSlice. vision-agents and Tencent TRTC dropped from runtime. Frontend migrated to `livekit-client` UMD. `/token` endpoint now dispatches the agent worker explicitly. LemonSlice avatar made optional.
2. **2026-05-16** Found that vision-agents has two parallel event systems: internal `_output` Stream (consumed by realtime_flow) and public PluginBaseEvent classes (defined but never emitted). All `@agent.subscribe` handlers were dead code. Workaround: monkey-patch LLM emit methods. Pivot to LiveKit superseded this.
3. **2026-05-16** Browser publish bug found and fixed: previous code only subscribed to TRTC, never published mic+webcam. Gemini received silence. Now superseded by LiveKit's `setMicrophoneEnabled` / `setCameraEnabled`.
4. **2026-05-16** Dropped ElevenLabs. Gemini Live native audio handles TTS via `voice_config` in `LiveConnectConfigDict` (vision-agents) or `voice=` (livekit.plugins.google).
5. **2026-05-16** Dropped Hunyuan and Tencent TTS. Gemini Live is the sole LLM.
6. **2026-05-16** Dropped Tencent IVH (paid avatar key required). LemonSlice picked up that role on LiveKit.

## Known gotchas

- **LiveKit dispatch is NOT auto**: workers using `AgentServer.rtc_session(agent_name=...)` require explicit dispatch via `LiveKitAPI.agent_dispatch.create_dispatch`. The `/token` endpoint must call this or the founder joins an empty room.
- **livekit-client global is `LivekitClient`** (lowercase k in `kit`), exposed by the UMD bundle. CDN-wise, `cdn.jsdelivr.net` returns the file directly; `unpkg.com` redirects and sometimes breaks browser loads.
- **`tencent.Edge()` and `vision_agents` are gone** from the runtime path. `archive/` keeps the old code for reference only.
- **Gemini Live audio is 24kHz PCM**, but LiveKit transcodes for the browser, so no special handling needed.
- **Browser autoplay policy**: audio plays after the founder clicks Join (user gesture satisfied).
- **One judge per LiveKit session**: changing judge requires ending the room and starting a new session. The frontend's `?judge=cuban|oleary|corcoran` query param picks the persona.

## Quickstart

```bash
cp .env.example .env
# Fill LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL, GOOGLE_API_KEY,
# TENCENT_SECRET_ID, TENCENT_SECRET_KEY, COS_BUCKET, COS_REGION.
# LEMONSLICE_API_KEY is optional.

docker compose up -d --build
docker compose logs -f worker  # verify "registered worker" appears

# Open in browser
open "http://localhost:8000/?room=demo&judge=cuban"
```

## Quality bar

- Every module under 400 lines
- Type annotations on public function signatures
- No em-dashes anywhere
- No real key values anywhere except local `.env`

## Git workflow

- Commits authored locally with `Edrick Chang <matxhedog2@gmail.com>`
- No Co-Authored-By trailer
- Push to `edrickchang13/sharktank` requires explicit in-chat approval
- Conventional commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`
