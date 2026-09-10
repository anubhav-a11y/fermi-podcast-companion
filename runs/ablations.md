# Ablation — which mechanism earned which gain?

`improved` differs from `baseline` on six flags at once, so the
headline comparison cannot say which change earned the gain. Each
`abl_*` preset below flips exactly one flag on top of `baseline`.

All rows here are **`--no-judge`** runs, including the baseline and
improved reference rows, so every mean score is computed over the
same deterministic metrics. Do not compare these numbers with the
judged ones in EVAL.md's headline table.

| Preset | mean score | pass | `citation_validity` | `has_citation` | `retrieval_recall` | `abstention_correct` | `must_mention` | `intent_correct` |
|---|---|---|---|---|---|---|---|---|
| baseline (naive RAG) | 0.821 | 7/17 | 82% | 82% | 92% | 100% | 100% | 40% |
| + BM25 hybrid (RRF) | 0.813 | 8/17 | 82% | 88% | 85% | 94% | 100% | 40% |
| + LLM intent router | 1.000 | 17/17 | 100% | 100% | 100% | 100% | 100% | 100% |
| + router + query rewriting | 0.978 | 15/17 | 94% | 100% | 100% | 94% | 100% | 100% |
| + episode-level index | 0.834 | 8/17 | 88% | 94% | 92% | 94% | 90% | 40% |
| + per-episode comparison | 0.834 | 7/17 | 88% | 88% | 92% | 100% | 90% | 40% |
| + abstention + citation repair | 0.832 | 7/17 | 94% | 100% | 92% | 82% | 90% | 40% |
| improved (all six) | 1.000 | 17/17 | 100% | 100% | 100% | 100% | 100% | 100% |

## Delta vs baseline (mean case score)

| Mechanism | Δ mean score |
|---|---|
| + BM25 hybrid (RRF) | -0.008 |
| + LLM intent router | +0.179 |
| + router + query rewriting | +0.157 |
| + episode-level index | +0.013 |
| + per-episode comparison | +0.013 |
| + abstention + citation repair | +0.011 |
| improved (all six) | +0.179 |
