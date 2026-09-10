"""Repeatable evaluation runner.

    python -m eval.run --preset baseline
    python -m eval.run --preset improved

Each case runs through `Companion.ask()` — the same code path the CLI and UI
use, so the evaluation measures the shipped product and not a parallel
reimplementation. Multi-turn cases replay their `history` turns through the
same session first, which is the only honest way to test follow-ups.

Writes, per run:
    runs/<preset>/results.jsonl   one raw record per case (full inputs+outputs)
    runs/<preset>/summary.json    aggregate metrics
    runs/<preset>/trace.jsonl     the session trace for every case
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from src import config
from src.app import llm
from src.app.session import Companion
from eval import judges

DEFAULT_CASES = Path(__file__).parent / "cases.yaml"


def load_cases(path: Path, only: list[str] | None, types: list[str] | None) -> list[dict]:
    data = yaml.safe_load(path.read_text())
    cases = data["cases"] if isinstance(data, dict) else data
    if only:
        cases = [c for c in cases if c["id"] in only]
    if types:
        cases = [c for c in cases if c.get("type") in types]
    if not cases:
        raise SystemExit("No cases selected.")
    return cases


def run_case(case: dict, preset: config.Settings, trace_path: Path,
             use_judge: bool) -> dict:
    comp = Companion(settings=preset, trace_path=trace_path,
                     session_id=f"{preset.name}-{case['id']}")

    # Replay prior turns for multi-turn cases (their answers are real, not stubs).
    setup: list[dict] = []
    for prior in case.get("history", []):
        prev = comp.ask(prior)
        setup.append({"query": prior, "response": prev.text,
                      "intent": prev.intent,
                      "sources": [s["label"] for s in prev.sources]})

    t0 = time.time()
    ans = comp.ask(case["query"])
    elapsed = time.time() - t0

    record = {
        "case_id": case["id"],
        "case_type": case.get("type", "unspecified"),
        "preset": preset.name,
        "learner_input": case["query"],
        "setup_turns": setup,
        "router": ans.router,
        "retrieved": ans.sources,
        "confidence": ans.confidence,
        "response": ans.text,
        "citations": ans.citations,
        "invalid_citations": ans.invalid_citations,
        "abstained": ans.abstained,
        "abstain_reason": ans.abstain_reason,
        "elapsed_s": round(elapsed, 2),
    }
    record["metrics"] = judges.score_record(record, case, comp.corpus, use_judge)
    return record


def aggregate(records: list[dict]) -> dict:
    per_metric: dict[str, dict] = {}
    for m in judges.METRIC_ORDER:
        applicable = [r for r in records if r["metrics"][m].get("pass") is not None]
        if not applicable:
            per_metric[m] = {"n": 0, "pass_rate": None}
            continue
        passed = sum(1 for r in applicable if r["metrics"][m]["pass"])
        per_metric[m] = {"n": len(applicable), "passed": passed,
                         "pass_rate": round(passed / len(applicable), 3)}

    scores = [r["metrics"]["_summary"]["score"] for r in records
              if r["metrics"]["_summary"]["score"] is not None]
    helps = [r["metrics"]["_summary"]["helpfulness"] for r in records
             if r["metrics"]["_summary"]["helpfulness"] is not None]

    by_type: dict[str, list[float]] = {}
    for r in records:
        s = r["metrics"]["_summary"]["score"]
        if s is not None:
            by_type.setdefault(r["case_type"], []).append(s)

    return {
        "n_cases": len(records),
        "mean_case_score": round(sum(scores) / len(scores), 3) if scores else None,
        "mean_helpfulness": round(sum(helps) / len(helps), 2) if helps else None,
        "fully_passing_cases": sum(1 for r in records
                                   if r["metrics"]["_summary"]["score"] == 1.0),
        "metrics": per_metric,
        "by_case_type": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_type.items())},
        "failures": [
            {"case_id": r["case_id"], "failed": r["metrics"]["_summary"]["failed"],
             "note": r["metrics"]["groundedness"].get("note", "")}
            for r in records if r["metrics"]["_summary"]["failed"]
        ],
        "usage": llm.usage_report(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the evaluation suite.")
    ap.add_argument("--preset", default="improved", choices=sorted(config.PRESETS))
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--out", type=Path, default=None,
                    help="output dir (default runs/<preset>)")
    ap.add_argument("--only", nargs="*", help="run only these case ids")
    ap.add_argument("--types", nargs="*", help="run only these case types")
    ap.add_argument("--no-judge", action="store_true",
                    help="deterministic metrics only (free, no LLM judge calls)")
    a = ap.parse_args(argv)

    preset = config.get_preset(a.preset)
    out_dir = a.out or (config.RUN_DIR / preset.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    trace_path = out_dir / "trace.jsonl"
    for p in (results_path, trace_path):
        if p.exists():
            p.unlink()

    cases = load_cases(a.cases, a.only, a.types)
    print(f"Running {len(cases)} cases · preset={preset.name} · "
          f"llm={config.LLM_PROVIDER} · judge={'off' if a.no_judge else 'on'}\n")

    records = []
    for i, case in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {case['id']:<28s} ", end="", flush=True)
        try:
            rec = run_case(case, preset, trace_path, not a.no_judge)
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}")
            rec = {"case_id": case["id"], "case_type": case.get("type", ""),
                   "preset": preset.name, "learner_input": case["query"],
                   "error": f"{type(exc).__name__}: {exc}", "retrieved": [],
                   "citations": [], "invalid_citations": [], "abstained": False,
                   "abstain_reason": "", "response": "", "router": {},
                   "confidence": {},
                   "metrics": {m: {"pass": False} for m in judges.METRIC_ORDER}}
            rec["metrics"]["_summary"] = {"applicable": judges.METRIC_ORDER,
                                         "passed": [], "failed": judges.METRIC_ORDER,
                                         "score": 0.0, "helpfulness": None}
        else:
            s = rec["metrics"]["_summary"]
            flag = "ok  " if s["score"] == 1.0 else "FAIL"
            print(f"{flag} score={s['score']} intent={rec['router'].get('intent','?')}"
                  f"{' abstain' if rec['abstained'] else ''}"
                  f"{' failed=' + ','.join(s['failed']) if s['failed'] else ''}")
        records.append(rec)
        with open(results_path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    summary = aggregate(records)
    summary["preset"] = preset.name
    summary["settings"] = preset.to_dict()
    summary["cases_file"] = str(a.cases)
    summary["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*66}\nPreset: {preset.name}   cases: {summary['n_cases']}")
    print(f"mean case score : {summary['mean_case_score']}")
    print(f"fully passing   : {summary['fully_passing_cases']}/{summary['n_cases']}")
    print(f"mean helpfulness: {summary['mean_helpfulness']}")
    print("\nper-metric pass rate")
    for k, v in summary["metrics"].items():
        if v["pass_rate"] is not None:
            print(f"  {k:<20s} {v['pass_rate']:.0%}  ({v['passed']}/{v['n']})")
    if summary["failures"]:
        print("\nfailures")
        for f in summary["failures"]:
            print(f"  {f['case_id']:<28s} {', '.join(f['failed'])}")
    print(f"\nRaw records : {results_path}")
    print(f"Traces      : {trace_path}")
    print(f"Summary     : {out_dir / 'summary.json'}")
    print("Usage       :", summary["usage"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
