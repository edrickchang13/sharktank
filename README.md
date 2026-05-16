# Shark Tank Pitch Simulator

Built at ACM x AIC Hack-A-Stack, May 16 2026, 6-hour sprint. Sponsor tracks: Tencent Cloud and GetStream.

## What this is

A live pitch simulator where you stand in front of your webcam and three AI judge avatars (Mark Cuban, Kevin O'Leary, Barbara Corcoran) grill you in real time. GetStream's vision agent reads your face for confidence and feeds a mood score to a Tencent Hunyuan LLM, which generates each judge's response in character. Tencent TTS speaks the line in a distinct voice per judge, and Tencent IVH (or a static headshot fallback) animates the avatar. Sessions log to Tencent COS for replay.

## Architecture

```
+---------------+      webcam + mic         +-------------------------+
|  User (P3 UI) | ------------------------> |  GetStream Vision (P2)  |
| OpenCV/pyaudio|                           |  VAD, ASR, mood score   |
+---------------+                           +-----------+-------------+
        ^                                               |
        |                                               | on_turn_end(transcript)
        |                                               | get_mood() -> float
        |                                               v
        |                                  +------------------------------+
        |                                  | pipeline.respond_to_pitch    |
        |                                  | (P1 orchestrator)            |
        |                                  +--------------+---------------+
        |                                                 |
        |          +--------------------+-----------------+--------------------+
        |          v                    v                                     v
        |   +------------+      +---------------+                      +-------------+
        |   |  Hunyuan   | ---> |     TTS       | ----audio bytes----> |     IVH     |
        |   |  (text)    |      |  (mp3 bytes)  |                      | (or STATIC) |
        |   +------------+      +---------------+                      +------+------+
        |                                                                     |
        |                              +--------------+                       |
        |                              |     COS      | <----session log------+
        |                              | (session log)|                       |
        |                              +--------------+                       |
        |                                                                     |
        +---------------- {text, audio_bytes, image_path, ...} ---------------+
```

## Quickstart with mock (P3 can unblock immediately)

```bash
pip install -r requirements.txt
python -c "from mock import respond_to_pitch; print(respond_to_pitch('cuban', 'We do AI for cats', 0.7))"
```

The mock returns the same shape as the real pipeline (`{judge, text, audio_bytes, image_path, latency_ms}`) with a silent MP3 stub. P3 can wire the frontend against this, then flip the import when Tencent keys land.

## Real pipeline setup

1. Copy the env template:
   ```bash
   cp .env.example .env
   ```
2. Get Tencent CAM keys at https://console.cloud.tencent.com/cam. The same `TENCENT_SECRET_ID` and `TENCENT_SECRET_KEY` are used by Hunyuan, TTS, and COS.
3. Activate each Tencent service in the console (see gotchas table below). For IVH, open a pre-sales ticket as early as possible since approval can take hours.
4. Get TRTC credentials from https://console.trtc.io. This is a separate console from Tencent Cloud proper. Free tier is 10k minutes per month.
5. Pick 3 voice IDs from the Tencent TTS voice catalog at https://www.tencentcloud.com/document/product/1154 and plug them into `TTS_VOICE_CUBAN`, `TTS_VOICE_OLEARY`, `TTS_VOICE_CORCORAN`.
6. Create a COS bucket in `ap-guangzhou` and set `COS_BUCKET`.
7. In P3's frontend, swap the import:
   ```python
   # from mock import respond_to_pitch
   from pipeline import respond_to_pitch
   ```

## Service activation gotchas

| Service | Activation | Notes |
|---|---|---|
| Hunyuan | Instant | `hunyuan-lite` is cheapest and fastest. Use it for the hackathon. |
| TTS | Instant | Pick voice IDs from the catalog and plug into env. No personality descriptors in the catalog, may need to audition by ear. |
| IVH | Slow, may need pre-sales contact | Falls back to static headshots + audio playback. Already wired in `ivh.py`. |
| COS | Instant | Create one bucket in `ap-guangzhou`. |
| TRTC | Instant, separate account on trtc.io | Free tier 10k min/month. |

## TRTC MCP server

Tencent ships an MCP server at `@tencent-rtc/mcp` that handles UserSig generation. Add it so Claude Code can mint test credentials directly:

```bash
claude mcp add tencent-rtc -e SDKAPPID=YOUR_ID -e SECRETKEY=YOUR_KEY
```

## Interfaces P1 exposes to P3

```python
# pipeline.py

def respond_to_pitch(
    judge_key: str,                  # 'cuban' | 'oleary' | 'corcoran'
    transcript: str,                 # what the user just said
    mood: float,                     # 0-1 from GetStream, 0 = nervous, 1 = confident
    history: list[dict] | None = None,
    render_mode: ivh.RenderMode = ivh.RenderMode.STATIC,
) -> dict:
    """
    Returns:
      {
        "judge":       str,    # echoed judge_key
        "text":        str,    # 2-3 sentence response
        "audio_bytes": bytes,  # MP3 of the spoken response
        "image_path":  str,    # path to static headshot (STATIC mode)
        "video_url":   str,    # populated only in IVH mode
        "latency_ms":  int,    # end-to-end pipeline latency
      }
    """

def log_session(session_id: str, session_data: dict) -> str:
    """Persist the full session log to COS. Returns a presigned URL (1hr)."""

def log_turn_audio(
    session_id: str,
    turn_idx: int,
    judge_key: str,
    audio_bytes: bytes,
) -> str:
    """Persist one turn's audio to COS. Returns a presigned URL."""
```

`mock.respond_to_pitch` and `mock.log_session` have the same signatures.

## What P1 needs from P2

GetStream vision agent should expose two things:

```python
on_turn_end(transcript: str) -> None
    # Fires when VAD detects the user finished speaking.
    # transcript is the ASR output for that utterance.
    # P1 picks the next judge and calls respond_to_pitch.

get_mood() -> float
    # Current confidence reading, 0 = very nervous, 1 = overconfident.
    # P1 reads this right before calling Hunyuan so the judge adapts.
```

Judge selection lives in `judges.pick_next_judge(turn_index, mood)`. Cuban opens, Barbara picks up if the founder is below 0.4 mood, otherwise it rotates.

## Risks and fallbacks

- **IVH activation slow.** Pre-sales approval is the long pole. We default `render_mode` to `RenderMode.STATIC`, which returns a headshot path plus audio bytes. The frontend renders that as a still image with audio playback. Demo still works, just less flashy. Flip to `RenderMode.IVH` only once activation is confirmed.
- **End-to-end latency 2-4s.** Hunyuan + TTS + IVH stack up. Mask the gap with VAD turn-taking (don't fire until the user clearly stops) and idle judge animations on the frontend (subtle blink/breath loops on the headshot).
- **TTS voice catalog has 380+ voices but no personality descriptors.** Plan to spend 20 minutes auditioning to pick three voices that read as Cuban (gruff, fast), O'Leary (cold, clipped), Corcoran (warm, sharp). Once chosen, the IDs go in `.env` and never change.
- **Hunyuan response shape.** Judge prompts cap at 2-3 sentences each. If a response comes back too long, truncate at the first sentence boundary past 200 chars rather than re-prompt, since re-prompting blows the latency budget.

## Files

- `judges.py` — judge personalities, mood-adapted system prompts, turn rotation
- `hunyuan.py` — `chat(judge_key, transcript, mood, history)` -> text
- `tts.py` — `synthesize_for_judge(text, judge_key)` -> MP3 bytes
- `ivh.py` — `render_judge(judge_key, audio_bytes, mode)` with STATIC fallback
- `cos.py` — session and per-turn audio upload, presigned URLs
- `pipeline.py` — `respond_to_pitch()` orchestrator
- `mock.py` — stand-in for P3 development
- `.env.example` — required env vars
