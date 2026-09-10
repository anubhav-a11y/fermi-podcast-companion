"""Deterministic post-ASR correction of domain proper nouns.

Whisper's `initial_prompt` only *biases* decoding; it does not guarantee a
spelling. Manual inspection of the first pass over this corpus found three
proper nouns mis-transcribed consistently:

    Goedel      -> "Girdle" (x7), "Gerdel" (x1)      E7
    Chargaff    -> "Schargaff"                        E3
    Bekenstein  -> "Beckenstein"                      E2
    Shannon     -> "Schannon", "Schazzan", "Schannan" E4

These are not cosmetic. Retrieval is the thing that breaks: BM25 matches on
surface tokens, so a learner asking about "Goedel" scores zero against a chunk
that says "Girdle", and the embedding of a nonsense token carries no useful
signal either. An answer-time prompt cannot repair this - the evidence never
gets retrieved in the first place.

So the fix belongs at ingest, and it is deliberately deterministic rather than
another LLM pass: the mapping is small, closed, and auditable, and a
word-boundary regex cannot invent a correction the way a generative pass can.
"""
from __future__ import annotations

import re

# wrong-spelling pattern -> canonical form. Case-insensitive, word-bounded.
GLOSSARY: dict[str, str] = {
    r"girdle": "Gödel",
    r"gerdel": "Gödel",
    r"goedel": "Gödel",
    r"schargaff": "Chargaff",
    r"chagaff": "Chargaff",
    r"beckenstein": "Bekenstein",
    r"schannon": "Shannon",
    r"schannan": "Shannon",
    r"schazzan": "Shannon",
    r"schallon": "Shannon",
    r"minkowsky": "Minkowski",
    r"schwarzchild": "Schwarzschild",
}

_COMPILED = [(re.compile(rf"\b{pat}\b", re.I), fix) for pat, fix in GLOSSARY.items()]


def correct_text(text: str) -> tuple[str, int]:
    """Return (corrected_text, number_of_substitutions)."""
    total = 0
    for rx, fix in _COMPILED:
        text, n = rx.subn(fix, text)
        total += n
    return text, total


def correct_segments(segments: list[dict]) -> int:
    """Correct `text` in place across ASR segments. Returns total fixes."""
    total = 0
    for seg in segments:
        seg["text"], n = correct_text(seg["text"])
        total += n
    return total
