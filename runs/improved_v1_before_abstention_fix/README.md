# improved, first run — kept as evidence, not as the headline result

This is the raw output of the first full `--preset improved` run. It is
preserved because it is where two regressions were found by hand, both of
which drove code and label changes:

1. `route_beginner_order` regressed from a correct answer (baseline) to a
   false refusal. Diagnosis: the retrieval-confidence abstention gate was
   applied to `episode_routing` turns, which are answered from episode
   cards, not from 60-second content chunks, and therefore score near zero
   against every chunk (best dense score 0.27 against a 0.30 threshold).
   Fix: `src/app/answer.py` exempts routing turns from the retrieval gate,
   leaving the LLM's semantic gate to catch genuine out-of-scope routing
   questions. Verified: `oos_plate_tectonics` still abstains correctly.

2. `qa_base_pairing` was scored as a retrieval miss for finding the *better*
   passage. The gold range marked Chargaff's numerical observation (8:59)
   rather than where the pairing rule is actually derived (19:11-20:43).
   The gold label was wrong, not the system. Fix: `eval/cases.yaml`.

The headline baseline-vs-improved comparison in EVAL.md uses the later runs
in `runs/baseline/` and `runs/improved/`, produced after both fixes and with
identical gold labels on both sides.
