# P1 to P2 Handoff: Shark Tank Simulator

This is the credentials and architecture handoff for P2 of our ACM x AIC Hack-A-Stack project (Shark Tank pitch simulator). Current stack: Vision Agents on the `feat/tencent-rtc` branch with `tencent.Edge()` WebRTC transport, `gemini.Realtime` for native audio output (model `gemini-2.5-flash-native-audio-preview-12-2025`), smart-turn VAD, Tencent COS session logging from P1, and 2D pixel-art judge images on the P3 frontend. You own the entire Vision Agents backend and the websocket to P3.

## Credentials policy (READ THIS FIRST)

- All 6 credential values are sent to you via secure channel (DM, Signal, or 1Password share).
- NEVER paste real values into this file, into commits, into chat, or into any tracked file.
- You receive values out-of-band and paste them into your local `.env` only.
- `.env` is gitignored. If a real key lands in a tracked file by mistake, rotate the key first, then scrub.

## .env template

```env
# Values sent via secure channel by P1, paste here:
TRTC_SDK_APP_ID=<paste from secure DM>
TRTC_SECRET_KEY=<paste from secure DM>
GOOGLE_API_KEY=<paste from secure DM>
GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-12-2025

# COS session logging (cos.py reads these directly)
TENCENT_SECRET_ID=<paste from secure DM>
TENCENT_SECRET_KEY=<paste from secure DM>
COS_BUCKET=<paste from secure DM>
COS_REGION=<paste from secure DM, currently na-siliconvalley>

# You obtain these separately from getstream.io
STREAM_API_KEY=<P2 gets from getstream.io>
STREAM_API_SECRET=<P2 gets from getstream.io>
```

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

Lifted from `p2_reference/vision_agents_starter.py`. Fork that file. Two key pieces:

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
    return Agent(
        edge=make_edge(),
        llm=make_llm_for_judge(session.current_judge, session.mood),
        turn_detection=smart_turn.VAD(),
    )
```

The full starter file at `p2_reference/vision_agents_starter.py` includes the `Session` class, `on_turn_end` callback, `on_session_end` callback, mood helpers, and a smoke `main()`.

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

## Websocket message format (P2 to P3)

```json
{"judge": "cuban|oleary|corcoran", "text": "...", "audio": "<bytes or base64>"}
```

## Open questions to verify at integration

1. Does Vision Agents support hot-swapping `agent.llm` mid-session for judge changes, or does each judge change require reconstructing the Agent? Starter file assumes hot-swap works, with a fallback comment.
2. smart-turn VAD compatibility under `tencent.Edge()` on the `feat/tencent-rtc` branch is unconfirmed.
3. Gemini native audio outputs 24kHz PCM. Does P3's frontend handle PCM directly, or do you need to transcode to MP3 client-side before websocket emit? Confirm with P3.

## Quickstart

```bash
git clone https://github.com/edrickchang13/sharktank
cd sharktank
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# .venv/bin/pip install vision-agents[tencent,gemini,smart-turn] google-genai httpx
cp .env.example .env
# paste the 8 secret values from P1's secure DM into .env
.venv/bin/python smoke_test.py  # expect 10 passed
.venv/bin/python p2_reference/vision_agents_starter.py  # smoke run (needs vision-agents installed)
```

## File map

- `p2_reference/vision_agents_starter.py`: fork this as your starting point
- `p2_reference/judges_export.json`: voice mapping plus full prompts in JSON
- `cos.py`: call `upload_audio`, `upload_session`, `list_session_keys` from your callbacks
- `judges.py`: source of truth for prompts, mood descriptor, and rotation logic
- `trtc.py`: only if you need UserSig generation outside Vision Agents
