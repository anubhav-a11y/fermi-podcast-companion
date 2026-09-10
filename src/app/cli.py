"""Terminal interface.  python -m src.app.cli   (or: make chat)"""

from __future__ import annotations

import argparse
import sys

from src import config
from src.app import llm
from src.app.session import Companion

HELP = """
Commands:
  :sources     show the passages behind the last answer, with timestamps
  :episodes    list the episode catalogue
  :reset       clear conversation history
  :usage       token usage this session
  :quit        exit
"""


def show_sources(ans) -> None:
    if not ans.sources:
        print("  (no sources retrieved)")
        return
    for i, s in enumerate(ans.sources, 1):
        print(f"\n  [{s['label']}] {s['episode_title']} "
              f"{config.fmt_ts(s['start_s'])}-{config.fmt_ts(s['end_s'])}  "
              f"dense={s['dense']:.3f} lex={s['lexical']:.3f}")
        body = s["text"]
        print(f"    {body[:400]}{'...' if len(body) > 400 else ''}")


def print_answer(ans) -> None:
    print("\n" + ans.text + "\n")
    tags = []
    if ans.abstained:
        tags.append(f"ABSTAINED ({ans.abstain_reason})")
    if ans.invalid_citations:
        tags.append(f"INVALID CITATIONS REMOVED: {', '.join(ans.invalid_citations)}")
    meta = (f"  intent={ans.intent} · cites={len(ans.citations)} · "
            f"sources={len(ans.sources)} · dense_max={ans.confidence.get('dense_max', 0):.2f}")
    if ans.standalone_query and ans.standalone_query.strip().lower() not in ("", ):
        meta += f"\n  searched as: {ans.standalone_query!r}"
    print(meta)
    for t in tags:
        print("  " + t)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fermi Podcast Companion (terminal).")
    ap.add_argument("--preset", default="improved", choices=sorted(config.PRESETS))
    ap.add_argument("-q", "--question", action="append",
                    help="ask and exit; repeat for a multi-turn scripted run")
    a = ap.parse_args(argv)

    comp = Companion(settings=config.get_preset(a.preset))
    print("\nFermi Podcast Companion")
    print(comp.banner())
    print(f"trace: {comp.trace_path}")

    if a.question:
        for q in a.question:
            print(f"\n> {q}")
            print_answer(comp.ask(q))
        return 0

    print(HELP)
    last = None
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in (":quit", ":q", ":exit"):
            break
        if q == ":reset":
            comp.reset()
            print("  history cleared")
            continue
        if q == ":usage":
            print(" ", llm.usage_report())
            continue
        if q == ":episodes":
            for e in comp.corpus.episodes:
                print(f"\n  {e['episode_id']}: {e['title']} "
                      f"({config.fmt_ts(e.get('duration_s', 0))})")
                print(f"    {e.get('summary', '')}")
                print(f"    topics: {', '.join(e.get('topics', [])[:10])}")
            continue
        if q == ":sources":
            if last:
                show_sources(last)
            else:
                print("  ask something first")
            continue

        last = comp.ask(q)
        print_answer(last)

    print(f"\nTrace written to {comp.trace_path}")
    print("Usage:", llm.usage_report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
