"""Step 2 of ingest: segments -> retrieval chunks.

Design choices worth defending in the product note:

* ~60 s windows. Short enough that a citation points the learner at a
  precise spot in the audio; long enough that a spoken explanation is not
  cut in half. ASR segments alone (2-8 s) are far too small to answer with.
* Break on sentence boundaries where possible, so chunks don't end mid-clause.
* One segment of overlap, so an idea that straddles a boundary is retrievable
  from either side.
* Timestamps are carried through untouched. They are the product's evidence
  trail and its audio-seek target.

Output: artifacts/chunks.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from src import config

SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s*$")


def _ends_sentence(text: str) -> bool:
    return bool(SENTENCE_END.search(text.strip()))


def chunk_episode(ep: dict, target: float, min_s: float, max_s: float,
                  overlap: int) -> list[dict]:
    segs = ep["segments"]
    chunks: list[dict] = []
    i = 0
    while i < len(segs):
        start = segs[i]["start"]
        parts: list[str] = []
        j = i
        while j < len(segs):
            parts.append(segs[j]["text"])
            span = segs[j]["end"] - start
            if span >= max_s:
                break
            if span >= target and _ends_sentence(segs[j]["text"]):
                break
            j += 1
        j = min(j, len(segs) - 1)
        end = segs[j]["end"]

        text = " ".join(p.strip() for p in parts).strip()
        text = re.sub(r"\s+", " ", text)
        if text and (end - start >= min_s or j == len(segs) - 1):
            chunks.append({
                "chunk_id": f"{ep['episode_id']}-c{len(chunks):04d}",
                "episode_id": ep["episode_id"],
                "episode_title": ep["title"],
                "start_s": round(start, 2),
                "end_s": round(end, 2),
                "segment_range": [i, j],
                "text": text,
                "context": "",  # filled by enrich.py
            })

        step = max(1, (j + 1) - overlap)
        i = max(i + 1, step)
    return chunks


def run(transcripts: Path, out_json: Path) -> list[dict]:
    if not transcripts.exists():
        raise SystemExit(f"{transcripts} missing. Run: make transcribe")
    data = json.loads(transcripts.read_text())
    all_chunks: list[dict] = []
    for ep in data["episodes"]:
        cs = chunk_episode(ep, config.CHUNK_TARGET_S, config.CHUNK_MIN_S,
                           config.CHUNK_MAX_S, config.CHUNK_OVERLAP_SEGMENTS)
        spans = [c["end_s"] - c["start_s"] for c in cs] or [0]
        print(f"{ep['episode_id']} {ep['title'][:44]:44s} "
              f"{len(cs):4d} chunks  mean {sum(spans)/len(spans):5.1f}s")
        all_chunks.extend(cs)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"chunks": all_chunks}, indent=2))
    print(f"\nWrote {out_json} — {len(all_chunks)} chunks total")
    return all_chunks


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chunk transcripts for retrieval.")
    ap.add_argument("--transcripts", type=Path, default=config.TRANSCRIPTS_JSON)
    ap.add_argument("--out", type=Path, default=config.CHUNKS_JSON)
    a = ap.parse_args(argv)
    run(a.transcripts, a.out)


if __name__ == "__main__":
    sys.exit(main())
