# Backend Handoff: Shark Tank Simulator

This is the credentials and architecture handoff for the Vision Agents backend of our ACM x AIC Hack-A-Stack project (Shark Tank pitch simulator). Current stack: Vision Agents with `getstream.Edge()` as the primary WebRTC transport (tencent.Edge is unstable on feat/tencent-rtc today), `gemini.Realtime` handling LLM plus native audio plus VAD (model `gemini-2.5-flash-native-audio-preview-12-2025`), Tencent COS session logging from this repo, and 2D pixel-art judge images on the browser frontend. You own the entire Vision Agents backend and the websocket to the browser frontend.

## Credentials policy (READ THIS FIRST)

- This repo's credentials (TRTC pair, Google API key, Tencent pair, COS bucket/region) are sent via secure channel (DM, Signal, or 1Password share). Stream creds you fetch from getstream.io.
- NEVER paste real values into this file, into commits, into chat, or into any tracked file.
- You receive values out-of-band and paste them into your local `.env` only.
- `.env` is gitignored. If a real key lands in a tracked file by mistake, rotate the key first, then scrub.

## .env template

```env
# From secure channel
TRTC_SDK_APP_ID=<from secure channel>
TRTC_SECRET_KEY=<from secure channel>
STREAM_API_KEY=<obtain from getstream.io>     # PRIMARY transport, used by getstream.Edge()
STREAM_API_SECRET=<obtain from getstream.io>
GOOGLE_API_KEY=<from secure channel>              # Gemini Live, sole LLM+TTS+VAD
GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-12-2025

# For cos.py session logging
TENCENT_SECRET_ID=<from secure channel>
TENCENT_SECRET_KEY=<from secure channel>
COS_BUCKET=<from secure channel>
COS_REGION=<from secure channel, currently na-siliconvalley>
```

## Integration Findings (May 16)

The Vision Agents backend has built agent.py and proven the wiring. Key learnings to apply:

- **Transport**: `tencent.Edge()` is unstable on feat/tencent-rtc today. Use `getstream.Edge()` as primary, keep tencent as a try-first with fallback. This repo's TRTC creds are still useful if tencent.Edge stabilizes during the demo.
- **No smart-turn, no ElevenLabs**: `gemini.Realtime()` takes over STT/TTS/VAD. Do not add smart_turn or elevenlabs to the agent config; they get silently disabled.
- **Join order**: Browser opens the call URL first. Then agent polls Stream REST API to detect the participant and joins after. Agent-first join times out the SFU.
- **No stdin under `uv run`**: do not use `input()` or `run_in_executor(None, input)` in the agent. Use REST polling.

## Gemini Live voice mapping

| Judge | Voice name | Personality fit |
| - | - | - |
| Cuban | Charon | deep, authoritative |
| O'Leary | Orus | crisp, sharp |
| Corcoran | Aoede | warm, female |

Stable half-cascade voices across Gemini model variants: Aoede, Charon, Fenrir, Kore, Leda, Orus, Puck, Zephyr. Stick to these 8.

## Three judge system prompts

Prompts are loaded from `judges_export.json`. The `{mood_desc}` placeholder is filled at render time. Verbatim from `judges.py`:

### Cuban

```
You are Mark Cuban on Shark Tank. You are an aggressive, numbers-first investor who calls out BS immediately. You hate fluff. You demand concrete numbers: CAC, LTV, revenue, margins, unit economics. If a founder cannot answer a numbers question in one sentence, you say so. You use short, punchy sentences. You never compliment without a follow-up challenge.

The founder pitching you is currently {mood_desc}. Adapt accordingly: if they are nervous, push harder on numbers to see if they crack. If they are confident, dig for the weakest assumption.

Respond in 2-3 sentences max. No preambles. No 'great pitch'. Get to the question.
```

### O'Leary

```
You are Kevin O'Leary (Mr. Wonderful) on Shark Tank. You are cold, transactional, and obsessed with royalties and getting your money back. You see every deal as a debt instrument first. You say things like 'you're dead to me' when a founder rejects your terms. You ask about valuation, dilution, royalty structures, and exit paths.

The founder pitching you is currently {mood_desc}. If they are nervous, get colder and more transactional to rattle them further. If they are confident, attack their valuation as delusional.

Respond in 2-3 sentences max. Always end with a hard question about money or terms. No warmth.
```

### Corcoran

```
You are Barbara Corcoran on Shark Tank. You invest in people, not just businesses. You ask about the founder's story, their grit, who hurt them, why they really started this. You read people fast and trust your gut. You are warm but sharp, you will call out someone who seems entitled or untested.

The founder pitching you is currently {mood_desc}. If they are nervous, soften your tone and ask something personal to draw them out. If they are confident, test whether the confidence is earned or performative.

Respond in 2-3 sentences max. Ask one question that gets at who they really are.
```

### Mood substitution table

| Mood range | `{mood_desc}` string |
| - | - |
| mood < 0.3 | visibly nervous, voice shaky, avoiding eye contact |
| mood < 0.55 | uncertain but holding together |
| mood < 0.8 | composed and steady |
| mood >= 0.8 | confident, maybe overconfident |

## Judge rotation logic

- Turn 0: Cuban always opens
- mood < 0.4: Corcoran (recovery beat for the demo)
- Else rotate: O'Leary, Corcoran, Cuban

## Vision Agents wiring snippet

Lifted from `reference/vision_agents_starter.py`. Fork that file. Two key pieces:

```python
def make_llm_for_judge(judge_key: str, mood: float) -> "gemini.Realtime":
    voice = JUDGES[judge_key]["gemini_voice"]
    instructions = render_system_prompt(judge_key, mood)
    return gemini.Realtime(
        model=GEMINI_MODEL,
        config=LiveConnectConfigDict(
                response_modalities=[Modality.AUDIO],
                speech_config=SpeechConfigDict(
                    voice_config=VoiceConfigDict(
                        prebuilt_voice_config=PrebuiltVoiceConfigDict(voice_name=voice)
                    ),
                    language_code="en-US",
                ),
                system_instruction=instructions,
        ),
        fps=3,
    )


def build_agent(session: Session) -> "Agent":
    # Try tencent first, fall back to getstream. tencent.Edge is unstable
    # on feat/tencent-rtc, so getstream.Edge is the primary transport in practice.
    try:
        edge = tencent.Edge()
    except Exception:
        edge = getstream.Edge()
    return Agent(
        edge=edge,
        llm=make_llm_for_judge(session.current_judge, session.mood),
    )
```

**Gotcha**: do not pass `turn_detection=smart_turn.VAD()` or wire ElevenLabs as a TTS plugin. `gemini.Realtime()` handles STT, TTS, and VAD internally and will silently disable both if you try.

### Runtime lifecycle

Stream SFU rejects an agent join when the room has zero participants, so order matters:

1. The browser frontend opens the call URL in the browser and joins the call.
2. The agent polls the Stream REST API for the call's participant list.
3. Once the founder is detected, the agent joins and Gemini Live starts streaming audio.

Do not block the agent on stdin. `asyncio.run_in_executor(None, input)` raises `EOFError` under `uv run` because stdin is not a tty. Drive the loop off the REST poll instead.

### Frontend join URL

The browser frontend builds a URL of this shape (verified during testing):

```
https://getstream.io/video/demos/join/{call_id}?api_key={key}&token={jwt}&skip_lobby=true&user_name=Founder
```

Example `call_id` used during testing: `sharktank-dev`. The JWT is generated server-side with `STREAM_API_SECRET`.

The full starter file at `reference/vision_agents_starter.py` includes the `Session` class, `on_turn_end` callback, `on_session_end` callback, mood helpers, and a smoke `main()`.

## COS endpoints to call at runtime

```python
import cos
url = cos.upload_audio(session_id, turn_idx, judge_key, audio_bytes_24khz_pcm_or_mp3)
url = cos.upload_session(session_id, session_data_dict)
keys = cos.list_session_keys(session_id)
```

Session JSON shape uploaded at end of run:

```json
{
  "session_id": "abc12345",
  "turns": [
    {"turn_idx": 0, "transcript": "...", "judge": "cuban", "response": "...", "mood": 0.6, "latency_ms": 2400}
  ],
  "total_latency_ms": 12000
}
```

## Websocket message format (backend to frontend)

```json
{"judge": "cuban|oleary|corcoran", "text": "...", "audio": "<bytes or base64>"}
```

## Open questions to verify at integration

1. Does Vision Agents support hot-swapping `agent.llm` mid-session for judge changes, or does each judge change require reconstructing the Agent? Research left this unconfirmed and the backend findings don't speak to it yet. Mid-session swap is being investigated; for now plan on agent reconstruction per judge change.
2. smart-turn relevance: RESOLVED. `gemini.Realtime()` internalizes VAD, the smart-turn slot is unused.
3. Gemini native audio outputs 24kHz PCM. Does the browser frontend handle PCM directly, or do you need to transcode to MP3 client-side before websocket emit? This is not yet reported on, the browser frontend to confirm during integration.

## Quickstart

```bash
git clone https://github.com/edrickchang13/sharktank
cd sharktank
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# .venv/bin/pip install vision-agents[getstream,gemini] google-genai httpx
cp .env.example .env
# paste the secure-DM values into .env, then add your STREAM_API_KEY and STREAM_API_SECRET
.venv/bin/python smoke_test.py  # expect 10 passed
.venv/bin/python reference/vision_agents_starter.py  # smoke run (needs vision-agents installed)
```

## File map

- `reference/vision_agents_starter.py`: fork this as your starting point
- `reference/judges_export.json`: voice mapping plus full prompts in JSON
- `cos.py`: call `upload_audio`, `upload_session`, `list_session_keys` from your callbacks
- `judges.py`: source of truth for prompts, mood descriptor, and rotation logic
- `trtc.py`: only if you need UserSig generation outside Vision Agents
