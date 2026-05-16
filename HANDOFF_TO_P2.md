# Handoff to P2: Vision Agents Backend

This doc is P1's package for P2, who owns the Vision Agents backend (tencent.Edge transport, Gemini Live LLM, smart-turn VAD, websocket to the browser frontend).

The big change since the last revision: **ElevenLabs is gone**. Vision Agents' `gemini.Realtime()` plugin ships with `response_modalities=[Modality.AUDIO]` by default, so Gemini Live generates the judge audio natively. No separate TTS plugin, no extra API key, no character quotas to watch. We pick a Gemini prebuilt voice per judge and that is the whole TTS story.

That trims P1's credential handoff from 5 things to 3, plus the COS pieces P1 is still provisioning.

## 1. Credentials

Paste this into P2's `.env`. The three values from P1 are already filled in. The rest are placeholders P1 or P2 will fill once they exist.

```bash
# From P1
TRTC_SDK_APP_ID=70001204
TRTC_SECRET_KEY=5df6c3ae1016b0abc625c8e3885f08ded2b452f3dff264117209b5907f26a824
GOOGLE_API_KEY=AIzaSyDHou1lDFXiqNPD35c4S8A-lwEiZTx_sC8

# P1 still provisioning (COS for session logging)
TENCENT_SECRET_ID=<from P1>
TENCENT_SECRET_KEY=<from P1>
COS_BUCKET=<from P1>
COS_REGION=ap-guangzhou

# P2 obtains
STREAM_API_KEY=<P2 gets from getstream.io>
STREAM_API_SECRET=<P2 gets from getstream.io>
```

The TRTC values came from console.trtc.io. The Google key is a Gemini Live capable key from AI Studio. The Tencent CAM values for COS are a separate console from TRTC, that is why they are tracked apart.

## 2. Gemini voice mapping for the three judges

| Judge | Voice name | Personality fit |
| - | - | - |
| Cuban | Charon | deep, authoritative |
| O'Leary | Orus | crisp, sharp |
| Corcoran | Aoede | warm, female |

The default model is `gemini-2.5-flash-native-audio-preview-12-2025`. It supports all 30 Gemini Live voices, but 8 of those are the stable half-cascade set that ships across model variants: Aoede, Charon, Fenrir, Kore, Leda, Orus, Puck, Zephyr. The picks above all come from that stable set, so swapping models later does not force a re-cast.

## 3. Judge system prompts

These are the live strings in `judges.py`. The `{mood_desc}` placeholder gets substituted at runtime based on the live mood score from the vision processor. Preserve the placeholder verbatim if you are templating these into the Gemini config.

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

### mood_desc substitution rule

| mood range | substitution |
| - | - |
| mood < 0.3 | `visibly nervous, voice shaky, avoiding eye contact` |
| 0.3 <= mood < 0.55 | `uncertain but holding together` |
| 0.55 <= mood < 0.8 | `composed and steady` |
| mood >= 0.8 | `confident, maybe overconfident` |

P1 ships `judges.render_system_prompt(judge_key, mood)` which does this substitution. P2 can either import it or replicate the table.

## 4. Judge rotation logic

From `judges.pick_next_judge(turn_index, mood)`:

- Turn 0 always returns Cuban (he opens)
- If `mood < 0.4` at any later turn, return Corcoran (recovery beat, warmer)
- Otherwise rotate `O'Leary -> Corcoran -> Cuban` indexed by `(turn_index - 1) % 3`

P2 can call this directly or reimplement. The rotation keeps Cuban dominant early, Corcoran as the safety valve when the founder cracks, and O'Leary as the cold middle-late challenger.

## 5. Vision Agents wiring

Here is the real init code based on the Vision Agents + Gemini Live plugin shape. Each judge gets its own LLM instance because the voice and system instruction are baked into the `LiveConnectConfigDict` at construction time.

```python
from google.genai.types import (
    LiveConnectConfigDict, Modality, SpeechConfigDict,
    VoiceConfigDict, PrebuiltVoiceConfigDict,
)
from vision_agents import Agent
from vision_agents.plugins import gemini, tencent, smart_turn
import os

JUDGE_PROMPTS = {...}  # paste from judges_export.json
JUDGE_VOICES = {"cuban": "Charon", "oleary": "Orus", "corcoran": "Aoede"}

def make_llm_for_judge(judge_key: str) -> gemini.Realtime:
    return gemini.Realtime(
        model="gemini-2.5-flash-native-audio-preview-12-2025",
        config=LiveConnectConfigDict(
            response_modalities=[Modality.AUDIO],
            speech_config=SpeechConfigDict(
                voice_config=VoiceConfigDict(
                    prebuilt_voice_config=PrebuiltVoiceConfigDict(
                        voice_name=JUDGE_VOICES[judge_key]
                    )
                ),
                language_code="en-US",
            ),
            system_instruction=JUDGE_PROMPTS[judge_key],
        ),
        fps=3,
    )

agent = Agent(
    edge=tencent.Edge(
        app_id=int(os.environ["TRTC_SDK_APP_ID"]),
        secret=os.environ["TRTC_SECRET_KEY"],
    ),
    llm=make_llm_for_judge("cuban"),  # initial judge
    turn_detection=smart_turn.VAD(),
)

# On judge change: swap agent.llm = make_llm_for_judge(new_judge_key)
# Or if Vision Agents doesn't support hot-swap, recreate the agent.
```

The `system_instruction` already has `{mood_desc}` substituted before being passed in. If you want mood to evolve mid-session inside one judge's turn, you have to rebuild the LLM (the system_instruction is locked at construction). For this demo, swapping per-judge is enough.

## 6. COS session logging (P1 module, P2 calls)

P1 owns `cos.py`. P2 calls it from inside `on_turn_end` or right after the audio buffer is finalized for a turn.

```python
import cos

url = cos.upload_audio(session_id, turn_idx, judge_key, audio_bytes)
url = cos.upload_session(session_id, session_data)
```

Session JSON schema P3's end screen will read:

```json
{
  "session_id": "string",
  "turns": [
    {
      "turn_idx": 0,
      "transcript": "string (what the user said)",
      "judge": "cuban|oleary|corcoran",
      "response": "string (what the judge said)",
      "mood": 0.62,
      "latency_ms": 1840
    }
  ],
  "total_latency_ms": 14200
}
```

`upload_audio` returns a presigned URL for the per-turn audio blob, useful if P3's end screen wants to replay any individual exchange. `upload_session` writes the full transcript JSON and returns its URL too.

## 7. Websocket schema to P3

The frontend expects messages shaped like:

```json
{
  "judge": "cuban",
  "text": "What are your unit economics? In one sentence.",
  "audio": "<base64 PCM or MP3 blob>"
}
```

`text` is optional (P3 will overlay it as a rolling transcript if present). `audio` is whatever Gemini Live emits, see open question 3 below for format.

## 8. Open questions for P2

1. **Hot-swap llm mid-session.** Does `Agent` let us reassign `agent.llm = make_llm_for_judge(new_key)` without dropping the TRTC connection or the turn-detection state? If not, plan B is reconstructing the whole agent per judge change, which costs maybe 1-2 seconds of dead air. Test early.
2. **smart-turn VAD under tencent.Edge.** The `feat/tencent-rtc` branch is the right place to confirm smart-turn fires reliably with TRTC as the transport. If it does not, fall back to `silero.VAD()` or whatever the Vision Agents default is.
3. **Gemini audio output format.** Gemini Live native audio is 24kHz PCM. Confirm whether the websocket can ship raw PCM to P3 and have it played in the browser via `AudioBufferSourceNode`, or whether we need to transcode to MP3 server-side first. PCM keeps latency lower but MP3 plays trivially in `<audio>`.

Anything else surfaces, ping P1 in the team channel.
