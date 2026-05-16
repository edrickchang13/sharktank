# P1 to P2 Handoff Package

This file is the credential and config handoff from P1 (Tencent + ElevenLabs + COS) to P2 (Vision Agents on `feat/tencent-rtc` with Gemini Realtime). P1 owns the credentials and judge prompt content. P2 owns the live agent wiring on top of Vision Agents. Read this file, paste the env block, drop the judge prompts into Vision Agents `instructions`, and wire the rotation. Open questions are at the bottom.

## 1. Credentials

Paste this into your local `.env`. P1 fills the `<from P1>` placeholders before sharing.

```bash
# Tencent TRTC (WebRTC transport for tencent.Edge)
TRTC_SDK_APP_ID=<from P1>
TRTC_SECRET_KEY=<from P1>

# ElevenLabs (judge voices)
ELEVENLABS_API_KEY=<from P1>
ELEVENLABS_VOICE_CUBAN=<from P1>
ELEVENLABS_VOICE_OLEARY=<from P1>
ELEVENLABS_VOICE_CORCORAN=<from P1>

# Tencent COS (P1 still uploads session JSON + per-turn audio)
COS_BUCKET=<from P1>
COS_REGION=<from P1>
TENCENT_SECRET_ID=<from P1>
TENCENT_SECRET_KEY=<from P1>

# P2 obtains separately
GOOGLE_API_KEY=<P2 gets from Google AI Studio>
STREAM_API_KEY=<P2 gets from getstream.io>
STREAM_API_SECRET=<P2 gets from getstream.io>
```

Note: `TRTC_SECRET_KEY` is a different value than `TENCENT_SECRET_KEY`. They come from two separate consoles (`console.trtc.io` vs `console.cloud.tencent.com/cam`). Do not paste one in for the other.

## 2. Judge system prompts

These are the exact strings from `judges.py`. Preserve the `{mood_desc}` placeholder. P2 substitutes `{mood_desc}` at render time with one of the four descriptors below based on the latest mood float from the Vision Agents mood processor.

### Mood substitution mapping

| mood range | descriptor |
| - | - |
| `mood < 0.3` | `visibly nervous, voice shaky, avoiding eye contact` |
| `0.3 <= mood < 0.55` | `uncertain but holding together` |
| `0.55 <= mood < 0.8` | `composed and steady` |
| `mood >= 0.8` | `confident, maybe overconfident` |

The canonical mapping lives in `judges._mood_descriptor()`. If P2 wants to reuse it directly, import from there instead of copying the thresholds.

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

## 3. Judge rotation logic

Pulled from `judges.pick_next_judge(turn_index, mood)`. Same rules apply on P2's side:

| condition | active judge |
| - | - |
| `turn_index == 0` | Cuban |
| `mood < 0.4` | Corcoran (the recovery beat) |
| else, turn 1, 2, 3, 4, 5, 6... | O'Leary, Corcoran, Cuban, O'Leary, Corcoran, Cuban... |

The else branch rotates `[oleary, corcoran, cuban][(turn_index - 1) % 3]`. P2 can either import `pick_next_judge` from `judges.py` or re-implement it. The first option keeps the source of truth in one place.

## 4. What P1 still owns at runtime

P2 does not need to call Tencent COS directly. P1 exposes two functions for session logging that P2 calls after each turn. These live in `cos.py` and are also re-exported through `pipeline.py`.

```python
from pipeline import log_session, log_turn_audio

# After each turn:
log_turn_audio(session_id, turn_idx, judge_key, audio_bytes)

# At session end:
log_session(session_id, session_data)
```

Session JSON schema P2 should build and pass to `log_session`:

```json
{
  "session_id": "string",
  "mock_mode": false,
  "turns": [
    {
      "turn_idx": 0,
      "transcript": "string",
      "judge": "cuban",
      "response": "string",
      "mood": 0.62,
      "latency_ms": 1850
    }
  ],
  "total_latency_ms": 12450
}
```

## 5. Vision Agents wiring snippet

Reference shape only. P2 fills in the actual constructor signatures from the Vision Agents `feat/tencent-rtc` branch.

```python
from vision_agents import Agent
from vision_agents.plugins import tencent, gemini, elevenlabs, smart_turn
import os

JUDGE_PROMPTS = {
    "cuban": "...paste from section 2...",
    "oleary": "...paste from section 2...",
    "corcoran": "...paste from section 2...",
}

JUDGE_VOICES = {
    "cuban": os.environ["ELEVENLABS_VOICE_CUBAN"],
    "oleary": os.environ["ELEVENLABS_VOICE_OLEARY"],
    "corcoran": os.environ["ELEVENLABS_VOICE_CORCORAN"],
}

def render_prompt(judge_key: str, mood: float) -> str:
    return JUDGE_PROMPTS[judge_key].format(mood_desc=_mood_descriptor(mood))

agent = Agent(
    edge=tencent.Edge(
        app_id=os.environ["TRTC_SDK_APP_ID"],
        secret=os.environ["TRTC_SECRET_KEY"],
    ),
    llm=gemini.Realtime(
        fps=3,
        instructions=render_prompt("cuban", 0.6),
    ),
    tts=elevenlabs.TTS(voice_id=JUDGE_VOICES["cuban"]),
    turn_detection=smart_turn.VAD(),
)

# When the active judge changes:
# agent.llm.instructions = render_prompt(next_judge, current_mood)
# agent.tts.voice_id = JUDGE_VOICES[next_judge]
```

The websocket emit to P3 after each completed turn:

```json
{ "judge": "cuban", "text": "...", "audio": "<blob>" }
```

## 6. Open questions for P2

1. Does Vision Agents support hot-swapping `instructions` on the `gemini.Realtime` LLM mid-session, or does each judge change require tearing down the agent and spinning up a new one? If the latter, we need to budget a few hundred ms of dead air between judges and either bridge with a placeholder ack or pre-warm the next agent.
2. Will `smart_turn.VAD()` work cleanly under `tencent.Edge` transport on the `feat/tencent-rtc` branch? Confirm whether that branch has known issues with VAD callbacks or audio framing.
3. Confirm the websocket schema to P3. Current contract is `{ judge, text, audio }`. Do we want to add `mood`, `turn_idx`, and `session_id` so P3 can pass them back to P1's `log_turn_audio` and `log_session`, or will P2 handle COS logging directly and skip those fields on the wire?

## 7. Quick verification before the demo

- [ ] Paste `.env` and run any Vision Agents hello-world example to confirm Tencent transport handshakes
- [ ] Render one Cuban prompt with `mood=0.6`, send to Gemini Realtime, confirm response is 2 to 3 sentences
- [ ] Run TTS once per voice ID to confirm all three ElevenLabs voices play distinctly
- [ ] Call `pipeline.log_turn_audio` with a dummy 1-second MP3 to confirm COS upload works end to end
- [ ] Smoke test judge rotation with `turn_index` 0 to 5 across `mood` values 0.2, 0.5, 0.9
