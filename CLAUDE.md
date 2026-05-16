# Shark Tank Simulator — Claude Project Context

This file is loaded automatically when Claude Code runs in this repo. Read it first.

## Operating directive

**Always run as many parallel agents as you can to implement features and resolve issues.** When a task can be decomposed into independent file writes, doc fetches, or research questions, spawn parallel Agent tool calls in a single message. Sequential execution is only acceptable when one task strictly depends on another's output.

Concretely:
- A request like "add module X and update Y and write tests" should fan out to 3 parallel agents
- Doc lookups, code generation for separate files, and research tasks always run in parallel
- The orchestrator (you) writes glue code (pipeline.py, integrations) after agents return

## What this project is

Shark Tank pitch simulator for ACM x AIC Hack-A-Stack at SCU, May 16 2026, 6-hour sprint track. User pitches their startup against 3 AI judge avatars modeled on Cuban, O'Leary, and Corcoran. Judges grill the user, read mood/confidence via webcam, and adapt grilling style.

Sponsor tracks: **Tencent Cloud** (judge side) + **GetStream Vision Agents** (user side).

## Team

| Role | Owner | Scope |
| - | - | - |
| P1 | Edrick (this repo) | All Tencent Cloud — Hunyuan, TTS, IVH, TRTC, COS |
| P2 | Teammate | GetStream Vision Agent — webcam, VAD, ASR, mood snapshots |
| P3 | Teammate | OpenCV/pyaudio frontend with stub interfaces |

## Architecture

```
User webcam + mic
    |
    v
GetStream Vision Agent (P2)
    - mood snapshots every ~3s -> float 0-1
    - VAD detects turn end
    - ASR transcribes pitch
    |
    | on_turn_end(transcript) callback
    | get_mood() -> float
    v
pipeline.respond_to_pitch(judge_key, transcript, mood, history)  (P1)
    |
    +-> hunyuan.chat()  -> judge response text
    +-> chunker.synthesize_long() -> MP3 audio bytes (TTS under the hood)
    +-> ivh.render_judge() -> {image_path | video_url} + audio
    +-> cos.upload_audio() (per turn, async-safe)
    |
    v
P3 frontend
    - display_judge(name, text) -> swaps headshot, shows text bubble, plays audio
    - end of session: feedback.generate_report() -> markdown end screen
```

## File map

| File | Purpose | Status |
| - | - | - |
| `judges.py` | Cuban/O'Leary/Corcoran system prompts with mood injection. `render_system_prompt(judge_key, mood)` + `pick_next_judge(turn_idx, mood)` + `JUDGES` dict | Done |
| `hunyuan.py` | Hunyuan ChatCompletions client. `chat(judge_key, transcript, mood, history) -> str` | Done |
| `tts.py` | TextToVoice client. `synthesize_for_judge(text, judge_key) -> bytes` + `synthesize(text, voice_id)` | Done |
| `chunker.py` | Safety: splits long Hunyuan responses on sentence/comma/whitespace so each chunk stays under TTS 500-char limit. `synthesize_long(text, judge_key) -> bytes` | Done |
| `ivh.py` | Digital Human renderer with `STATIC` (headshot + audio) fallback. `IVH` mode stubbed pending activation | Done (IVH mode pending) |
| `cos.py` | Session JSON + per-turn audio uploads with presigned URLs | Done |
| `trtc.py` | Pure-stdlib UserSig generation. `generate_user_sig()` + `make_room_credentials()` | Done |
| `pipeline.py` | Orchestrator. `respond_to_pitch()` + `log_session()` + `log_turn_audio()`. Drop-in replacement for mock | Done |
| `mock.py` | Mock pipeline for P3 unblock. Same signature, hardcoded responses, silent MP3, no Tencent calls | Done |
| `demo.py` | CLI runner. `python demo.py --mock --turns 3` for end-to-end test | Done |
| `feedback.py` | Post-pitch report generator. `generate_report()` + `format_markdown()`. Rule-based, no LLM | Done |
| `smoke_test.py` | Interface verification. 9 tests, runs against mock + ivh static. All passing | Done |
| `assets/judges/` | Placeholder headshots (`cuban.png`, `oleary.png`, `corcoran.png`) — swap with real images | Placeholder |

## Interfaces locked

**P1 -> P3** (P3 imports from `pipeline.py` once env is wired, or from `mock.py` until then):
```python
def respond_to_pitch(judge_key: str, transcript: str, mood: float, history: list[dict] | None = None) -> dict:
    # Returns: {judge, text, audio_bytes, image_path, video_url, latency_ms}

def log_session(session_id: str, session_data: dict) -> str:
    # Returns: presigned download URL

def log_turn_audio(session_id: str, turn_idx: int, judge_key: str, audio_bytes: bytes) -> str:
```

**P2 -> P1** (P2 calls these on P1's pipeline):
- `on_turn_end(transcript: str)` — fired when VAD detects silence. Triggers a `respond_to_pitch` call.
- `get_mood() -> float` — most recent mood snapshot 0-1. P1 reads this when building each turn.

## Environment

```bash
# Create venv (already done in .venv/)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Copy and fill credentials
cp .env.example .env
# Edit .env with values from Tencent Cloud console + console.trtc.io

# Run smoke tests (no credentials needed — uses mock)
.venv/bin/python smoke_test.py

# Run demo end-to-end with mock
.venv/bin/python demo.py --mock --turns 3 --mood 0.6 --no-cos

# Run demo against real Tencent (requires .env)
.venv/bin/python demo.py --turns 3 --mood 0.6
```

## Required env vars

See `.env.example`. Summary:

| Var | Source | Notes |
| - | - | - |
| `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | https://console.cloud.tencent.com/cam | Used by Hunyuan, TTS, COS |
| `TENCENT_REGION` | default `ap-guangzhou` | Hunyuan + TTS region |
| `HUNYUAN_MODEL` | default `hunyuan-lite` | Cheapest, fast enough for hackathon |
| `TTS_VOICE_CUBAN` / `_OLEARY` / `_CORCORAN` | Tencent TTS voice catalog | Pre-filled: 501008, 101050, 501009 — audition in console before locking |
| `IVH_AVATAR_CUBAN` / `_OLEARY` / `_CORCORAN` | IVH console | Optional — pipeline runs in STATIC mode without these |
| `TRTC_SDK_APP_ID` / `TRTC_SECRET_KEY` | https://console.trtc.io | Separate account from main Tencent Cloud |
| `COS_BUCKET` / `COS_REGION` | COS console | Create one bucket, default region `ap-guangzhou` |

## Known gotchas

- **IVH activation is slow.** May need to contact Tencent pre-sales for API access. The pipeline runs in STATIC mode (headshot + audio) without IVH — that's the safety net.
- **TTS 500-char limit.** Hunyuan is prompted for 2-3 sentence responses but may overshoot. `chunker.synthesize_long` splits responses safely.
- **TRTC SDKSecretKey != CAM SecretKey.** Two separate consoles, two separate credentials.
- **Voice catalog has no personality descriptors.** Audition each voice in the console before locking.
- **Hunyuan API uses `{Role, Content}` (capitalized).** `hunyuan._convert_history` normalizes from OpenAI-style `{role, content}`.
- **Pipeline latency 2-4s end-to-end.** Masked by VAD turn-taking and idle judge animations on the frontend.

## Quality bar

- All new modules pass `smoke_test.py`
- Every module under 120 lines, files focused on one concern
- Type annotations on public function signatures
- One docstring per public function, no chatty internals
- Mock and real pipelines share the same return shape so P3 can swap with one line change

## Git workflow

- Commits authored locally with `Edrick Chang <matxhedog2@gmail.com>`
- No Co-Authored-By trailer
- Push to remote (`edrickchang13/sharktank` on GitHub) requires explicit in-chat approval
- Use conventional commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
