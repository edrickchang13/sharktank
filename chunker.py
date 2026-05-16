import re

import tts

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_COMMA_SPLIT = re.compile(r"(?<=,)\s+")
_WHITESPACE_SPLIT = re.compile(r"\s+")


def _hard_cut(text, max_chars):
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _split_oversized(piece, max_chars):
    for splitter in (_COMMA_SPLIT, _WHITESPACE_SPLIT):
        parts = splitter.split(piece)
        if len(parts) > 1 and all(len(p) <= max_chars for p in parts):
            return _pack(parts, max_chars)
    return _hard_cut(piece, max_chars)


def _pack(pieces, max_chars):
    chunks, current = [], ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized(piece, max_chars))
            continue
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def split_for_tts(text: str, max_chars: int = 480) -> list[str]:
    """Split text into chunks each <= max_chars, respecting sentence boundaries.

    Splits on sentence terminators (. ! ?) first. If a single sentence exceeds
    max_chars, falls back to splitting on commas, then whitespace, then hard
    char cuts as a last resort. Default max_chars is 480 (buffer under 500).
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    return _pack(_SENTENCE_SPLIT.split(text), max_chars)


def synthesize_long(text: str, judge_key: str) -> bytes:
    """Synthesize text of any length by chunking and concatenating MP3 frames.

    Calls tts.synthesize_for_judge per chunk and concatenates the raw bytes.
    Naive MP3 concatenation works for the hackathon — modern decoders handle
    sequential MP3 frames fine. Returns one bytes blob playable as one stream.
    """
    chunks = split_for_tts(text)
    if not chunks:
        return b""
    return b"".join(tts.synthesize_for_judge(c, judge_key) for c in chunks)


if __name__ == "__main__":
    # Quick sanity check, no Tencent calls
    short = "What's your CAC? Show me the numbers."
    long_text = "What's your CAC and LTV? " * 30  # ~720 chars
    huge_sentence = "x" * 1000

    assert split_for_tts(short) == [short]
    long_chunks = split_for_tts(long_text)
    assert all(
        len(c) <= 480 for c in long_chunks
    ), f"chunk too long: {[len(c) for c in long_chunks]}"
    assert len(long_chunks) > 1
    huge_chunks = split_for_tts(huge_sentence)
    assert all(len(c) <= 480 for c in huge_chunks)
    print(
        f"PASS: short=1 chunk, long={len(long_chunks)} chunks, huge={len(huge_chunks)} chunks"
    )
