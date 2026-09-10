"""Skim the transcript to sanity-check ASR quality before building on it.

    python scripts/peek.py                 # sample each episode
    python scripts/peek.py --episode E2 --start 600 --window 180
    python scripts/peek.py --grep decoherence

Read the output. If names and jargon are mangled, fix that here (bigger
Whisper model, or extend JARGON_PROMPT in src/config.py) rather than trying
to paper over it downstream — every later stage inherits these errors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inspect transcripts.")
    ap.add_argument("--episode")
    ap.add_argument("--start", type=float, default=0.0, help="seconds")
    ap.add_argument("--window", type=float, default=120.0, help="seconds to show")
    ap.add_argument("--grep", help="show every segment matching this pattern")
    a = ap.parse_args(argv)

    if not config.TRANSCRIPTS_JSON.exists():
        raise SystemExit(f"{config.TRANSCRIPTS_JSON} missing. Run: make transcribe")
    eps = json.loads(config.TRANSCRIPTS_JSON.read_text())["episodes"]

    if a.grep:
        pat = re.compile(a.grep, re.I)
        n = 0
        for ep in eps:
            for s in ep["segments"]:
                if pat.search(s["text"]):
                    print(f"{ep['episode_id']} [{config.fmt_ts(s['start'])}] {s['text']}")
                    n += 1
        print(f"\n{n} matches for {a.grep!r}")
        return 0

    for ep in eps:
        if a.episode and ep["episode_id"] != a.episode:
            continue
        words = sum(len(s["text"].split()) for s in ep["segments"])
        print("=" * 76)
        print(f"{ep['episode_id']}  {ep['title']}")
        print(f"  {config.fmt_ts(ep['duration_s'])} · {len(ep['segments'])} segments · "
              f"{words} words · {words/max(ep['duration_s']/60,1):.0f} wpm · "
              f"asr={ep.get('asr_model','?')}")
        print("=" * 76)
        lo = a.start
        hi = a.start + a.window
        shown = 0
        for s in ep["segments"]:
            if s["start"] >= lo and s["start"] < hi:
                print(f"[{config.fmt_ts(s['start'])}] {s['text']}")
                shown += 1
        if not shown:
            print("(no segments in that window)")
        print()

    print("Checklist: are speaker turns coherent? is jargon spelled right?")
    print("are there repeated/looping lines? any long gaps where speech was dropped?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
