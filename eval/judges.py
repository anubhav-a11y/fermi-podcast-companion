"""Scoring for the evaluation harness.

Deterministic first, LLM second. The metrics that decide whether the product
is *trustworthy* are all computed with code, not with a model judging itself:

  citation_validity   every emitted [E# @ mm:ss] must match a passage actually
                      retrieved this turn, and that timestamp must exist in the
                      transcript. Catches fabricated evidence.
  retrieval_recall    did a gold time range appear in the retrieved set?
                      Separates "retrieval missed it" from "generation fumbled
                      it" — you cannot fix the right thing without this split.
  abstention_correct  refuses out-of-scope questions AND does not refuse
                      in-scope ones. Both directions, or you can score 100%
                      by refusing everything.
  must_mention        required substrings/synonyms appear in the answer.

Only groundedness and helpfulness use an LLM judge, and groundedness sees
ONLY the cited passages — so it is checking support, not recalling physics.
"""

from __future__ import annotations

import json
import re

from src.app import llm

GROUND_SYSTEM = """You verify whether an answer is supported by evidence.
TASK: JUDGE

You get PASSAGES (verbatim podcast transcript excerpts) and an ANSWER.
Judge ONLY whether each factual claim in the ANSWER is supported by the
PASSAGES. Your own knowledge of physics is irrelevant — a true statement
that is not in the passages is UNSUPPORTED.

Ignore: sentences explicitly prefixed "Background (not from the episodes):",
questions back to the learner, and pure connective phrasing.

Reply with JSON only:
{"grounded": true|false,
 "unsupported_claims": ["<verbatim claim>", ...],
 "helpfulness": 1-5,
 "reason": "<=25 words"}

helpfulness: 5 = directly answers, concrete, well pitched to a learner;
3 = correct but vague or padded; 1 = evasive or off-topic."""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


# ------------------------------------------------------------- deterministic
def citation_validity(record: dict, corpus) -> dict:
    """All emitted citations valid AND resolvable to a real transcript span."""
    retrieved = {s["label"]: s for s in record["retrieved"]}
    emitted = record["citations"] + record["invalid_citations"]
    bad_unretrieved = list(record["invalid_citations"])
    bad_unresolvable = []
    for label in record["citations"]:
        src = retrieved.get(label)
        if not src:
            bad_unresolvable.append(label)
            continue
        chunk = corpus.by_id.get(src["chunk_id"])
        if chunk is None or abs(chunk["start_s"] - src["start_s"]) > 1.0:
            bad_unresolvable.append(label)
    ok = not bad_unretrieved and not bad_unresolvable
    return {
        "pass": bool(ok),
        "n_emitted": len(emitted),
        "invalid": bad_unretrieved + bad_unresolvable,
    }


def has_citation(record: dict, case: dict) -> dict:
    """Non-abstaining substantive answers must cite something."""
    needs = not record["abstained"] and case.get("type") != "out_of_scope"
    return {"pass": (not needs) or len(record["citations"]) > 0,
            "n": len(record["citations"]), "required": needs}


def retrieval_recall(record: dict, case: dict) -> dict:
    """Gold = expected episodes and/or expected time ranges (seconds)."""
    exp_eps = case.get("expect_episodes") or []
    exp_ranges = case.get("expect_time_ranges") or []
    if not exp_eps and not exp_ranges:
        return {"pass": None, "note": "no gold specified"}

    got_eps = {s["episode_id"] for s in record["retrieved"]}
    ep_ok = (not exp_eps) or bool(set(exp_eps) & got_eps)

    range_ok = not exp_ranges
    matched = []
    for lo, hi in exp_ranges:
        for s in record["retrieved"]:
            if s["start_s"] < hi and s["end_s"] > lo:   # any overlap
                range_ok = True
                matched.append(f"{s['label']} ({lo}-{hi})")
                break
    return {"pass": bool(ep_ok and range_ok),
            "episodes_retrieved": sorted(got_eps),
            "episodes_expected": exp_eps,
            "ranges_matched": matched}


def abstention_correct(record: dict, case: dict) -> dict:
    should = bool(case.get("should_abstain", False))
    did = bool(record["abstained"])
    return {"pass": should == did, "should_abstain": should, "did_abstain": did}


def must_mention(record: dict, case: dict) -> dict:
    """Each entry may be a string, or a list of acceptable synonyms."""
    reqs = case.get("must_mention") or []
    if not reqs:
        return {"pass": None, "note": "none specified"}
    text = _norm(record["response"])
    missing = []
    for req in reqs:
        alts = [req] if isinstance(req, str) else list(req)
        if not any(_norm(a) in text for a in alts):
            missing.append(alts[0])
    return {"pass": not missing, "missing": missing}


def must_not_mention(record: dict, case: dict) -> dict:
    reqs = case.get("must_not_mention") or []
    if not reqs:
        return {"pass": None}
    text = _norm(record["response"])
    present = [r for r in reqs if _norm(r) in text]
    return {"pass": not present, "present": present}


def intent_correct(record: dict, case: dict) -> dict:
    exp = case.get("expect_intent")
    if not exp:
        return {"pass": None}
    got = record["router"].get("intent")
    return {"pass": got == exp, "expected": exp, "got": got}


# ---------------------------------------------------------------- llm judge
def groundedness(record: dict, corpus) -> dict:
    """Judge sees only the CITED passages (or, if abstaining, nothing to check)."""
    if record["abstained"]:
        return {"pass": True, "helpfulness": None, "note": "abstained; nothing to ground",
                "unsupported_claims": []}
    cited = [s for s in record["retrieved"] if s["label"] in record["citations"]]
    if not cited:
        return {"pass": False, "helpfulness": None,
                "note": "answer cited nothing; cannot be verified",
                "unsupported_claims": ["<entire answer uncited>"]}

    passages = "\n\n".join(f"[{s['label']}]\n{s['text']}" for s in cited)
    user = (f"PASSAGES:\n{passages}\n\nLEARNER QUESTION:\n{record['learner_input']}"
            f"\n\nANSWER:\n{record['response']}")
    try:
        data = llm.json_chat(GROUND_SYSTEM, [{"role": "user", "content": user}],
                             max_tokens=500, temperature=0.0)
    except Exception as exc:
        return {"pass": None, "helpfulness": None, "note": f"judge error: {exc}"}
    if not data:
        return {"pass": None, "helpfulness": None, "note": "judge output unparseable"}
    return {
        "pass": bool(data.get("grounded")),
        "helpfulness": data.get("helpfulness"),
        "unsupported_claims": data.get("unsupported_claims", []),
        "note": str(data.get("reason", ""))[:160],
    }


# ------------------------------------------------------------------- rollup
METRIC_ORDER = ["citation_validity", "has_citation", "retrieval_recall",
                "abstention_correct", "must_mention", "must_not_mention",
                "intent_correct", "groundedness"]


def score_record(record: dict, case: dict, corpus, use_llm_judge: bool) -> dict:
    m = {
        "citation_validity": citation_validity(record, corpus),
        "has_citation": has_citation(record, case),
        "retrieval_recall": retrieval_recall(record, case),
        "abstention_correct": abstention_correct(record, case),
        "must_mention": must_mention(record, case),
        "must_not_mention": must_not_mention(record, case),
        "intent_correct": intent_correct(record, case),
    }
    m["groundedness"] = (groundedness(record, corpus) if use_llm_judge
                         else {"pass": None, "helpfulness": None, "note": "judge disabled"})

    applicable = [k for k in METRIC_ORDER if m[k].get("pass") is not None]
    passed = [k for k in applicable if m[k]["pass"]]
    m["_summary"] = {
        "applicable": applicable,
        "passed": passed,
        "failed": [k for k in applicable if not m[k]["pass"]],
        "score": round(len(passed) / len(applicable), 3) if applicable else None,
        "helpfulness": m["groundedness"].get("helpfulness"),
    }
    return m
