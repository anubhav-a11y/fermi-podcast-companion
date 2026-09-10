"""Baseline vs improved comparison, as markdown you can paste into EVAL.md.

    python -m eval.report                       # runs/baseline vs runs/improved
    python -m eval.report --a runs/x --b runs/y

Prints per-metric deltas AND a per-case table, because an aggregate that
improves can still hide regressions on individual cases — and the brief asks
specifically for what regressed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import config
from eval.judges import METRIC_ORDER


def load(run_dir: Path) -> tuple[dict, dict[str, dict]]:
    s = run_dir / "summary.json"
    r = run_dir / "results.jsonl"
    if not s.exists() or not r.exists():
        raise SystemExit(f"{run_dir} is missing summary.json or results.jsonl. "
                         f"Run: python -m eval.run --preset {run_dir.name}")
    records = {}
    for line in r.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            records[rec["case_id"]] = rec
    return json.loads(s.read_text()), records


def pct(v) -> str:
    return "—" if v is None else f"{v:.0%}"


def num(v) -> str:
    return "—" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)


def arrow(a, b) -> str:
    if a is None or b is None:
        return ""
    if b > a:
        return " ↑"
    if b < a:
        return " ↓ **regression**"
    return " ="


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare two evaluation runs.")
    ap.add_argument("--a", type=Path, default=config.RUN_DIR / "baseline")
    ap.add_argument("--b", type=Path, default=config.RUN_DIR / "improved")
    ap.add_argument("--out", type=Path, default=None, help="also write markdown here")
    args = ap.parse_args(argv)

    sa, ra = load(args.a)
    sb, rb = load(args.b)
    L: list[str] = []

    L.append(f"## {sa['preset']} vs {sb['preset']}\n")
    L.append(f"Cases: {sa['n_cases']} · judged {sa.get('timestamp','')} / "
             f"{sb.get('timestamp','')}\n")

    L.append("### Headline\n")
    L.append(f"| Measure | {sa['preset']} | {sb['preset']} | |")
    L.append("|---|---|---|---|")
    L.append(f"| Mean case score | {num(sa['mean_case_score'])} | "
             f"{num(sb['mean_case_score'])} |{arrow(sa['mean_case_score'], sb['mean_case_score'])} |")
    L.append(f"| Fully passing cases | {sa['fully_passing_cases']}/{sa['n_cases']} | "
             f"{sb['fully_passing_cases']}/{sb['n_cases']} |"
             f"{arrow(sa['fully_passing_cases'], sb['fully_passing_cases'])} |")
    L.append(f"| Mean helpfulness (1-5) | {num(sa['mean_helpfulness'])} | "
             f"{num(sb['mean_helpfulness'])} |{arrow(sa['mean_helpfulness'], sb['mean_helpfulness'])} |")

    L.append("\n### Per metric\n")
    L.append(f"| Metric | {sa['preset']} | {sb['preset']} | |")
    L.append("|---|---|---|---|")
    for m in METRIC_ORDER:
        va = sa["metrics"].get(m, {}).get("pass_rate")
        vb = sb["metrics"].get(m, {}).get("pass_rate")
        if va is None and vb is None:
            continue
        L.append(f"| `{m}` | {pct(va)} | {pct(vb)} |{arrow(va, vb)} |")

    L.append("\n### Per case type (mean score)\n")
    types = sorted(set(sa["by_case_type"]) | set(sb["by_case_type"]))
    L.append(f"| Case type | {sa['preset']} | {sb['preset']} | |")
    L.append("|---|---|---|---|")
    for t in types:
        va, vb = sa["by_case_type"].get(t), sb["by_case_type"].get(t)
        L.append(f"| {t} | {num(va)} | {num(vb)} |{arrow(va, vb)} |")

    L.append("\n### Per case\n")
    L.append(f"| Case | {sa['preset']} | {sb['preset']} | Change | Now failing |")
    L.append("|---|---|---|---|---|")
    improved_ids, regressed_ids = [], []
    for cid in sorted(set(ra) | set(rb)):
        A = ra.get(cid, {}).get("metrics", {}).get("_summary", {})
        B = rb.get(cid, {}).get("metrics", {}).get("_summary", {})
        va, vb = A.get("score"), B.get("score")
        change = ""
        if va is not None and vb is not None:
            if vb > va:
                change, _ = "improved ↑", improved_ids.append(cid)
            elif vb < va:
                change, _ = "**regressed ↓**", regressed_ids.append(cid)
            else:
                change = "same"
        L.append(f"| `{cid}` | {num(va)} | {num(vb)} | {change} | "
                 f"{', '.join(B.get('failed', [])) or '—'} |")

    L.append(f"\n**Improved:** {', '.join(f'`{c}`' for c in improved_ids) or 'none'}")
    L.append(f"\n**Regressed:** {', '.join(f'`{c}`' for c in regressed_ids) or 'none'}")

    still = sorted({f["case_id"] for f in sa["failures"]} &
                   {f["case_id"] for f in sb["failures"]})
    L.append(f"\n**Still failing in both:** "
             f"{', '.join(f'`{c}`' for c in still) or 'none'}")

    L.append("\n### Cost\n")
    L.append(f"- {sa['preset']}: {sa.get('usage')}")
    L.append(f"- {sb['preset']}: {sb.get('usage')}")

    md = "\n".join(L)
    print(md)
    if args.out:
        args.out.write_text(md)
        print(f"\n[written to {args.out}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
