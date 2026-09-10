"""Attribution table: which single mechanism earned which gain?

`improved` differs from `baseline` on six flags at once, so the headline
comparison cannot say which change did the work. Each `abl_*` preset flips
exactly one flag on top of `baseline`, so the delta in this table is
attributable to a single named mechanism.

Usage:  python scripts/ablation_table.py [--out runs/ablations.md]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"

# Ablations run with --no-judge, so they are compared against a --no-judge
# baseline and a --no-judge improved. Mixing judged and unjudged mean scores
# would inflate every delta, because the unjudged mean is computed over one
# fewer (and the hardest) metric.
ORDER = ["baseline_nojudge", "abl_hybrid", "abl_router", "abl_rewrite",
         "abl_episode_index", "abl_per_episode", "abl_abstention",
         "improved_nojudge"]

LABEL = {
    "baseline_nojudge": "baseline (naive RAG)",
    "abl_hybrid": "+ BM25 hybrid (RRF)",
    "abl_router": "+ LLM intent router",
    "abl_rewrite": "+ router + query rewriting",
    "abl_episode_index": "+ episode-level index",
    "abl_per_episode": "+ per-episode comparison",
    "abl_abstention": "+ abstention + citation repair",
    "improved_nojudge": "improved (all six)",
}

METRICS = ["citation_validity", "has_citation", "retrieval_recall",
           "abstention_correct", "must_mention", "intent_correct"]


def load(preset: str) -> dict | None:
    f = RUNS / preset / "summary.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


def pct(summary: dict, metric: str) -> str:
    m = (summary.get("metrics") or {}).get(metric)
    if not m or not m.get("n"):
        return "—"
    return f"{round(100 * m['pass_rate'])}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RUNS / "ablations.md"))
    a = ap.parse_args()

    rows = [(p, load(p)) for p in ORDER]
    have = [(p, s) for p, s in rows if s]
    if len(have) < 2:
        raise SystemExit("Need at least two runs. Try: make eval && make ablate")

    out = ["# Ablation — which mechanism earned which gain?", "",
           "`improved` differs from `baseline` on six flags at once, so the",
           "headline comparison cannot say which change earned the gain. Each",
           "`abl_*` preset below flips exactly one flag on top of `baseline`.",
           "",
           "All rows here are **`--no-judge`** runs, including the baseline and",
           "improved reference rows, so every mean score is computed over the",
           "same deterministic metrics. Do not compare these numbers with the",
           "judged ones in EVAL.md's headline table.", "",
           "| Preset | mean score | pass | " + " | ".join(f"`{m}`" for m in METRICS) + " |",
           "|---|---|---|" + "---|" * len(METRICS)]
    for p, s in have:
        cells = [pct(s, m) for m in METRICS]
        out.append(f"| {LABEL.get(p, p)} | {s['mean_case_score']:.3f} | "
                   f"{s['fully_passing_cases']}/{s['n_cases']} | "
                   + " | ".join(cells) + " |")

    base = (dict(have)["baseline_nojudge"]
            if any(p == "baseline_nojudge" for p, _ in have) else None)
    if base:
        out += ["", "## Delta vs baseline (mean case score)", "",
                "| Mechanism | Δ mean score |", "|---|---|"]
        for p, s in have:
            if p == "baseline_nojudge":
                continue
            d = s["mean_case_score"] - base["mean_case_score"]
            out.append(f"| {LABEL.get(p, p)} | {d:+.3f} |")

    text = "\n".join(out) + "\n"
    Path(a.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
