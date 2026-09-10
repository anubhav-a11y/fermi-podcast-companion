# Build log — what was done, in order, and why

`README.md` is the guide to *running* this. This file is the record of how
it was built and what changed along the way, including the things that went
wrong. Numbers cited here are reproduced in [EVAL.md](EVAL.md).

---

## 1. Transcribe (Groq `whisper-large-v3-turbo`, ~12s per episode)

7 files, 4h44m, 1,204 segments. Local `faster-whisper` also works and needs
no key, but on CPU it runs near real time — hours, not minutes.

## 2. Read the transcript before building anything on it

This is the step that pays. Reading E7 by hand found **Gödel transcribed as
"Girdle" seven times**, which no amount of prompt engineering at answer time
can repair: BM25 scores surface tokens, so a query for "Gödel" scores zero
against a chunk that says "Girdle".

The scaffold's `JARGON_PROMPT` was primed for condensed matter — "cuprate",
"Cooper pair", "Bardeen-Cooper-Schrieffer" — none of which appear in this
corpus. Wrong vocabulary is worse than none, because `initial_prompt` biases
decoding *toward* the words it lists.

## 3. Four ASR prompt configurations, measured

| Prompt style | Loops | Spurious `Sch*` | Gödel | Prompt echoed |
|---|---|---|---|---|
| dense list, wrong domain | 0 | 5 | 1/12 | no |
| dense list, correct domain | 12 | 14 | 12/12 | no |
| minimal `Names: A, B, C` | 2 | 1 | 12/12 | **yes** |
| **one natural sentence** ✅ | 0 | 2 | 12/12 | no |

Fixing the vocabulary fixed Gödel and broke other things: a 12-segment
repetition loop of `"Rokihel."`, and `Schwarzschild` bleeding a `Sch-`
prefix across unrelated words. A bare name list stopped the bleed but
Whisper started transcribing the prompt itself during quiet passages.

A single natural sentence carrying the same proper nouns avoided both.
`initial_prompt` is a decoding bias, not a glossary — it behaves best when
it reads like the audio.

Residual errors (`Schannon`, `Schargaff`, `Beckenstein`) go to a
deterministic word-boundary pass, `src/ingest/glossary.py`. Closed regex
table, not another LLM call: a substitution table cannot invent a fix.
12 errors fixed by prompt, 5 by glossary, 0 remain.

## 4. Chunk → enrich → index

326 chunks at ~66s, sentence-aligned, one segment of overlap. Each chunk
gets an LLM-written context header (Anthropic's contextual retrieval); each
episode gets a card with summary, topics and outline, which is what routing
questions search. Embeddings: `all-MiniLM-L6-v2` locally.

Enrichment **checkpoints after every episode**, because an early run died on
a 429 with the whole pass unwritten and ten minutes of completed LLM work
thrown away.

## 5. Label the eval set by hand

17 cases, every gold timestamp read off the real transcript. The scaffold's
placeholders were not merely empty, they were wrong for this corpus: one
out-of-scope case asked whether the episodes cover "general relativity and
black hole thermodynamics", which are E6 and E2. Each refusal topic here was
grepped against the full transcript to confirm zero hits.

## 6. Baseline, then read the failures

`locate_photo51` scored 0.167. Turn 1 answered correctly citing
`[E3 @ 11:04]`; turn 2 — *"take me to the part of the audio that supports
that"* — retrieved only Turing and Shannon chunks, because the pronoun was
never resolved. The index was fine; the query had no subject in it.

## 7. Improve, measure, find the regressions

Intent routing + query rewriting + episode index + per-episode comparison.
Mean 0.841 → 0.954, `intent_correct` 40% → 100%.

The first improved run was not clean. `route_beginner_order` regressed to a
*false refusal* — the confidence gate was judging routing questions on chunk
scores, and routing questions score near zero against chunks by
construction. And `qa_base_pairing` was penalised for retrieving the
*better* passage, because my gold range marked Chargaff's observation rather
than where the pairing rule is derived. First was a code bug, second was my
label. Both raw runs kept in `runs/*_v1*`.

## 8. Ablate, to find out what actually earned the gain

The router alone accounts for **the entire** deterministic improvement
(+0.179, same as all six flags). BM25 hybrid slightly *hurts*. Abstention
alone makes refusal *worse* (100% → 82%). See `runs/ablations.md`.

## 9. Drive the product by hand

Found a bug the 17-case suite missed: after a comparison turn (21 passages)
then a clarification, "take me to the audio" truncated evidence to the top 3
by rank, dropping the passages the previous answer had cited — so citation
repair stripped them and the product asked the learner for transcripts.
Fixed in `src/app/session.py` by ordering reused evidence by what was
actually cited.

## 10. Quantify how much of the result is judge noise

Four runs per preset. Deterministic metrics: identical every time. LLM
judge groundedness: swings up to three cases on unchanged code, and the
baseline/improved ranges overlap. Reported as noise rather than as a
finding.

---

## Reproducing

```bash
make smoke      # offline fixture, no keys, no audio — proves the plumbing
make ingest     # transcribe → chunk → enrich → index
make eval       # baseline + improved + comparison
make ablate     # per-mechanism attribution
make run        # Streamlit UI with click-to-play citations
```
