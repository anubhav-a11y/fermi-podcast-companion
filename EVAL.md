# Evaluation

> All numbers below come from `runs/baseline/` and `runs/improved/` in this
> repository, produced by `make eval` against the seven supplied episodes.
> Reproduce with `make eval`; regenerate the tables with `make report`.
>
> Model: `anthropic/claude-haiku-4.5` via OpenRouter for routing, answering
> and judging. Embeddings: `all-MiniLM-L6-v2` locally. ASR:
> `whisper-large-v3-turbo` via Groq.

---

## What success means

The product's job is not to sound knowledgeable about physics. It is to
answer from the supplied audio and let the learner verify it. So the success
criteria are about faithfulness first and helpfulness second.

| Metric | How | Target |
|---|---|---|
| `citation_validity` | deterministic | **100%** — every emitted `[E# @ mm:ss]` must match a passage actually retrieved this turn and resolve to a real transcript span |
| `has_citation` | deterministic | 100% of substantive answers cite something |
| `retrieval_recall` | deterministic | ≥80% — a gold episode/time range appears in the retrieved set |
| `abstention_correct` | deterministic | **100%** — refuses out-of-scope questions *and* does not refuse in-scope ones |
| `intent_correct` | deterministic | ≥85% routed to the right strategy |
| `must_mention` / `must_not_mention` | deterministic | required concepts present, banned phrasings absent |
| `groundedness` | LLM judge, cited passages only | ≥90% |
| `helpfulness` | LLM judge, 1–5 | ≥4.0 mean |

`citation_validity` and `abstention_correct` are the two that matter most.
A fabricated timestamp or a confident answer about material the collection
never covers are both fatal to the product's only real promise, in a way
that a vague answer is not.

Two deliberate design points in the metric set:

- **Retrieval recall is separated from groundedness.** Without that split
  you cannot tell "retrieval missed it" from "generation fumbled it", and
  you will fix the wrong component.
- **Abstention is scored in both directions.** Refusing everything would
  score 100% on out-of-scope cases alone. The suite therefore also asserts
  that in-scope cases are *not* refused.

## The evaluation set

`eval/cases.yaml` — 17 cases spanning all seven episodes and all five
intents:

| Type | n | What it probes |
|---|---|---|
| `passage_qa` | 5 | content questions across E1, E2, E3, E4, E7 |
| `episode_routing` | 3 | which-episode questions, incl. one spanning two episodes |
| `cross_episode_compare` | 3 | synthesis without blending episodes into one voice |
| `clarify_previous` | 2 | multi-turn: simplification, and pronoun resolution |
| `locate_audio` | 1 | multi-turn: "take me to the part that supports that" |
| `out_of_scope` | 3 | must refuse rather than answer from general knowledge |

Four are multi-turn — their prior turns are replayed through the same
session, because a follow-up tested in isolation is not a follow-up.

Every gold label was read off the actual transcript. Two points about the
labels are worth stating, because both cost real time to get right:

**"Out of scope" is not "not physics."** The collection spans molecular
biology (E3), information theory (E4), machine learning (E5) and
mathematical logic (E7). The scaffold's original refusal case asked whether
the episodes cover "general relativity and black hole thermodynamics" —
which are E6 and E2. Every refusal topic here (superconductivity, the Higgs
boson, plate tectonics) was grepped against the full transcript and returns
zero hits, so a confident answer is a fabrication rather than a retrieval
miss. Two candidate topics were rejected this way: CRISPR (mentioned once in
E3 at 41:24) and protein folding (E3 at 38:07).

**Two gold labels were wrong and were corrected against the transcript.**
See "Corrections to the eval itself" below. Both were found because the
system disagreed with the label and the system turned out to be right.

## Upstream of the metrics: ASR quality

Nothing downstream can be better than the transcript, and no answer-time
prompt repairs a word the recogniser never produced. Before writing any
cases I read the transcript by hand and measured four `initial_prompt`
configurations for Whisper (`whisper-large-v3-turbo` via Groq, same audio,
same decode settings):

| Prompt style | Repetition loops | Spurious `Sch*` tokens | "Gödel" correct | Prompt echoed into transcript |
|---|---|---|---|---|
| v1 dense list, wrong domain (scaffold default) | 0 | 5 | 1/12 | no |
| v2 dense list, correct domain | **12** | **14** | 12/12 | no |
| v3 minimal `Names: A, B, C` list | 2 | 1 | 12/12 | **yes** |
| **v4 one natural sentence** ✅ | **0** | **2** | 12/12 | no |

The scaffold shipped a prompt full of condensed-matter vocabulary
("cuprate", "Cooper pair", "Bardeen-Cooper-Schrieffer") that appears nowhere
in this corpus, and Gödel came back as **"Girdle" seven times**. That is not
cosmetic: BM25 scores surface tokens, so a learner asking about Gödel scores
zero against a chunk that says Girdle, and the embedding of a nonsense token
carries no signal either.

Fixing the vocabulary (v2) fixed Gödel and made everything else worse — a
12-segment repetition loop of the non-word `"Rokihel."` in E6, and the
`Schwarzschild` in the prompt bleeding a `Sch-` prefix across unrelated
words ("Schannon", "Schallity"). Trimming to a bare name list (v3) removed
the bleed but Whisper began **transcribing the prompt itself** during quiet
passages, inflating "Minkowski" to 55 false occurrences.

The configuration that worked is a single natural sentence carrying the same
proper nouns, reading like a sample of the audio rather than a glossary. The
lesson generalises: `initial_prompt` is a *decoding bias*, not a lookup
table, and it behaves best when it looks like the thing being decoded.

The last few errors — `Schannon`/`Schazzan` → Shannon, `Schargaff`/`Chagaff`
→ Chargaff, `Beckenstein` → Bekenstein — are handled by a deterministic
word-boundary pass (`src/ingest/glossary.py`) applied before chunking. It is
deliberately a closed, auditable regex table rather than another LLM pass: a
substitution table cannot invent a correction. Twelve errors were fixed by
the prompt, five by the glossary; the shipped corpus has zero occurrences of
any of them.

## The runner

```bash
make eval    # = eval.run --preset baseline, then --preset improved, then report
```

Each case goes through `Companion.ask()`, the same entry point the CLI and
UI use, so the evaluation measures the shipped product. Per run it writes:

- `runs/<preset>/results.jsonl` — one record per case with the learner
  input, rewritten query, router decision, every retrieved passage with
  timestamps and scores, the response, citations, and per-metric verdicts.
- `runs/<preset>/summary.json` — aggregates and the token bill.
- `runs/<preset>/trace.jsonl` — the session trace.

## Baseline vs improved

Both are feature-flag presets in `src/config.py`, so one ingest pass
produces both numbers reproducibly.

| Flag | baseline | improved |
|---|---|---|
| dense + BM25 hybrid (RRF) | dense only | on |
| conversational query rewriting | off | on |
| episode-level index for routing | off | on |
| per-episode retrieval for comparison | off | on |
| abstention gates | off | on |
| post-hoc citation repair | off | on |

The baseline is deliberately a competent naive RAG system — one index, top-k
chunks, answer. That is what most first attempts look like, so it is the
honest thing to measure against.

---

# Results

## Headline

`make eval` over all 17 cases, identical gold labels on both sides.

| Measure | baseline | improved | |
|---|---|---|---|
| Mean case score | 0.841 | **0.954** | ↑ |
| Fully passing cases | 8/17 | **12/17** | ↑ |
| Mean helpfulness (1–5) | 4.58 | 4.50 | ≈ (judge noise — see below) |

| Metric | baseline | improved | target | |
|---|---|---|---|---|
| `citation_validity` | 94% | **100%** | 100% | ↑ met |
| `has_citation` | 88% | **100%** | 100% | ↑ met |
| `retrieval_recall` | 92% | **100%** | ≥80% | ↑ met |
| `abstention_correct` | 100% | **100%** | 100% | = met |
| `must_mention` | 100% | 100% | — | = |
| `must_not_mention` | 100% | 100% | — | = |
| `intent_correct` | 40% | **100%** | ≥85% | ↑ met |
| `groundedness` | 76% | 71% | ≥90% | **missed — and not measurable at this n** |

Seven of the eight metrics are deterministic and every one of them is at
100% for `improved`. The eighth, `groundedness`, is an LLM judge, and the
next section explains why I do not believe its 76% → 71% "regression".

By case type (mean score):

| Case type | baseline | improved | |
|---|---|---|---|
| `locate_audio` | 0.167 | **1.000** | ↑ |
| `clarify_previous` | 0.785 | **0.928** | ↑ |
| `cross_episode_compare` | 0.885 | **0.944** | ↑ |
| `episode_routing` | 0.706 | **0.889** | ↑ |
| `out_of_scope` | 0.933 | **1.000** | ↑ |
| `passage_qa` | 1.000 | 1.000 | = |

`passage_qa` is flat, and that is the expected result rather than a
disappointment: plain content questions are the one shape naive chunk RAG
already handles. Everything the improvement targets is a question shape the
baseline was structurally unable to serve.

## How much of this is judge noise?

Running the identical suite repeatedly across development gave this spread.
`intent_correct` is deterministic; `groundedness` is the LLM judge.

| Preset | runs | mean case score | `groundedness` | `intent_correct` |
|---|---|---|---|---|
| baseline | 4 | 0.782 – 0.841 | 10–13 / 17 (59–76%) | **6/15, every run** |
| improved | 4 | 0.930 – 0.980 | 12–15 / 17 (71–88%) | **15/15, every run** |

Two conclusions, and the second one constrains what this evaluation is
entitled to claim.

**The deterministic metrics are exactly reproducible.** `intent_correct` was
6/15 on all four baseline runs and 15/15 on all four improved runs — zero
variance across the whole development period, through several code changes.
That 40% → 100% is a real, stable, repeatable measurement.

**The LLM judge is too noisy to resolve the difference it is being asked to
resolve.** `groundedness` swings by 2–3 cases run to run on identical code,
and the two ranges *overlap*: baseline's best run (13/17) beats improved's
worst (12/17). At n=17 this metric cannot distinguish the two systems. The
76% → 71% "regression" in the headline table is inside that noise band, and
I am not going to report it as a finding in either direction — nor claim the
88% an earlier run produced, which would have been the flattering choice.

What I would do with more time: three judge samples per case with majority
vote, a judge from a different model family than the generator, and a
human-labelled subset to calibrate against. As it stands, **the
deterministic metrics are the ones I would defend**, and they happen to be
the ones that matter most for this product — a fabricated citation and a
false refusal are both deterministically detectable, and both are at 100%.

## Raw examples

### 1. A clean success, verifiable against the audio

Case `qa_bekenstein_entropy`, improved, score 1.0.

> **Q:** Why did Bekenstein think a black hole should have entropy?
>
> **A:** Bekenstein argued that a black hole must carry entropy because
> otherwise the second law of thermodynamics would be violated. He imagined
> dropping a hot, high-entropy gas into a black hole. […] To keep the second
> law intact, the black hole's horizon area must increase by at least as
> much as the lost entropy, implying that the area itself is a measure of
> entropy **[E2 @ 5:25–6:39]**.

The transcript at exactly that citation:

```
[5:30] Here's the thought experiment that forced his hand. The second law is
       supposed to be sacred. […] take a cup of hot gas, which has a lot of
       entropy, and toss it into a black hole. It's gone.
[6:04] You'd have a perfect entropy disposal machine, feed the universe's
       disorder into black holes and the books look cleaner and cleaner.
[6:25] When you drop that hot gas in, the black hole's mass increases a
       little, so its horizon area increases a little, and if area is
       entropy, the hole's entropy goes up by at least as much.
```

The answer's argument is the transcript's argument, at the timestamp it
claims. In the UI this citation is a button that starts the audio at 5:25.

### 2. A correct refusal

Case `oos_superconductivity`, improved, score 1.0, `abstained=true`,
`abstain_reason=model_declared_no_coverage`.

> **Q:** How do these episodes explain superconductivity and BCS theory?
>
> **A:** The collection does not discuss superconductivity or BCS theory.
> The episodes cover Einstein's relativity (special and general), Hawking
> radiation and black holes, DNA structure, information theory, the
> Transformer architecture, Turing machines, and computability — but none
> address superconductivity or the Bardeen-Cooper-Schrieffer theory that
> explains it.

It refuses *and* tells the learner what is actually available, which is the
useful half of a refusal. Note this is a question a language model could
answer fluently from its own training data; the product declines to.

### 3. The failure found by hand — the one that drove the improvement

Case `locate_photo51`, **baseline, score 0.167** — the worst case in the
suite, and a direct failure of one of the brief's own example interactions.

Turn 1 works. The learner asks what Photograph 51 was, and the baseline
answers correctly, citing `[E3 @ 11:04]`.

Turn 2 is *"Take me to the part of the audio that supports that."* With no
routing and no query rewriting, the baseline treats those literal words as a
fresh content question and searches for them:

```
retrieved: ['E7 @ 33:00', 'E4 @ 39:44', 'E4 @ 20:01',
            'E4 @ 0:55',  'E4 @ 31:12', 'E4 @ 30:13']
```

Every passage is from the Turing or Shannon episodes. Photograph 51 is in
E3. The answer that follows is remarkable mostly for its honesty:

> I need to be direct: the sources I have don't contain the specific
> timestamps for what I cited about Photograph 51. Looking back at my
> previous answer, I cited [E3 @ 11:04], [E3 @ 39:00], but those exact
> timestamps are not in my SOURCES list. I made a mistake by citing episodes
> without having the actual audio excerpts to back them up.

**Component at fault: routing and query rewriting, not retrieval.** The
index contains the right passage — turn 1 found it. The pronoun "that" was
never resolved, so the query sent to the retriever had no subject in it. No
amount of better embedding fixes a query that does not mention DNA.

The same case, improved, scores **1.0**:

```
intent    : locate_audio
rewritten : "Play the audio section explaining Photograph 51, its X-shaped
             pattern, helical structure, and physical dimensions of DNA."
retrieved : ['E3 @ 11:04', 'E3 @ 39:00', 'E3 @ 0:55']
```

> **[E3 @ 11:04]** — The speakers explain that Photograph 51 was "an X-ray
> diffraction image of DNA, the sharpest anyone had taken," produced by
> Rosalind Franklin at King's College London. The X-shaped pattern of spots
> is "the unmistakable signature of a helix" because "a helix, a spiral,
> diffracts X-rays into exactly that cross pattern."

Every quoted phrase is verbatim in the transcript at 11:26–11:38.

### 4. Something still broken

Case `route_curved_spacetime`, improved, score 0.833, fails `groundedness`.

The answer correctly names E6 and is genuinely useful. But an
`episode_routing` answer is composed largely from the **episode card** —
the LLM-written summary and topic list — while its citations point at
individual 60-second **chunks**. The groundedness judge is shown only the
cited chunk text, so a claim that is true of the episode as a whole, and
supported by the card, is scored unsupported because the one cited chunk
does not contain it.

This is a real product defect, not only a measurement artefact: if the cited
passage does not support the sentence, the learner who clicks through is
misled, even when the sentence is true. Both remaining failures in the
improved run are this same issue. See "Still unresolved".

## Failure analysis

Reading the baseline records by hand, the failures sort into four groups.
Component attribution matters more than the count.

| Failure | Cases | Component at fault | Evidence |
|---|---|---|---|
| Pronouns never resolved, so follow-up retrieval is noise | `locate_photo51`, `followup_simplify` | **routing / query rewriting** | `locate_photo51` retrieved only E4/E7 chunks for a DNA question; turn 1 had already found the right passage |
| Routing questions answered from content chunks | `route_entropy`, `route_beginner_order`, `route_curved_spacetime` | **retrieval strategy** | `route_entropy` returned six E4 chunks and recommended only E4, missing E2, which develops black-hole entropy independently |
| Comparison answers dominated by one episode | `compare_entropy_two_senses` | **retrieval strategy** | top-k pulled mostly E4; a fair comparison needs k per episode, not k overall |
| Every turn classified `passage_qa` | 9 of 15 labelled cases | **routing (absent by construction)** | baseline `intent_correct` = 40% |

The single most informative record is `locate_photo51`, because it isolates
the cause cleanly: the same system found the correct passage one turn
earlier. That rules out ASR, chunking, indexing and embedding quality, and
points at exactly one component.

Two things the baseline did **well**, worth stating because they bound what
the improvement can claim credit for:

- `abstention_correct` was already 100%. The answer-time prompt refuses
  competently on its own; the retrieval-confidence gate added later did not
  improve refusal, and initially made it worse (below).
- `passage_qa` was already 0.971. Naive chunk RAG genuinely handles plain
  content questions on this corpus.

## The improvement

The failures point at one thing: **the product had a single retrieval
strategy for five different question shapes.** So the improvement is
intent-aware retrieval — classify the turn, rewrite it into a standalone
query, and route it to a strategy that fits.

Concretely, `improved` turns on:

| Mechanism | Fixes |
|---|---|
| LLM router (5 intents) | every turn being treated as a content question |
| conversational query rewriting | `locate_photo51`, `followup_simplify` |
| episode-level index | `route_entropy`, `route_beginner_order` |
| per-episode retrieval for comparisons | `compare_entropy_two_senses` |
| dense + BM25 hybrid (RRF) | jargon queries missed by embeddings alone |
| abstention gates + citation repair | fabricated citations |

Result: mean case score 0.841 → 0.954, `intent_correct` 40% → 100%
(stable across four runs of each), `citation_validity` 94% → 100%,
`retrieval_recall` 92% → 100%, `locate_audio` 0.167 → 1.000. All seven
deterministic metrics are at 100% for `improved`.

### What regressed, and what I did about it

The first improved run was **not** a clean sweep. `abstention_correct` went
100% → 94% and two cases regressed. Both raw runs are preserved in
`runs/baseline_v1/` and `runs/improved_v1_before_abstention_fix/`.

**Regression 1 — a real bug I introduced.** `route_beginner_order` went from
a correct, useful answer to a **false refusal**:

> I don't think this collection covers that. The closest passages I found
> score well below the threshold I need to answer honestly (best dense score
> 0.27, need 0.30).

The retrieval-confidence gate was being applied to `episode_routing` turns.
But "where should I start, and in what order?" is a question *about* the
collection, not about anything said inside it, so it scores near zero
against every 60-second content chunk — by construction, not because the
answer is unavailable. Fixed in `src/app/answer.py` by exempting routing
turns from the retrieval gate and leaving the LLM's semantic gate to catch
genuinely out-of-scope routing questions. Verified that
`oos_plate_tectonics` — a routing-shaped question that *must* refuse — still
abstains correctly.

That same refusal message also revealed a hardcoded `"these three episodes"`
in a corpus of seven. Fixed.

**Regression 2 — my gold label was wrong, not the system.** `qa_base_pairing`
was scored as a retrieval miss. The improved run retrieved E3 @ 19:11–20:43,
where the pairing rule is actually derived ("A and T fit together… G and C
fit together perfectly, clasping with three hydrogen bonds"). My gold range
pointed at 8:59, which is Chargaff's *numerical observation* — the clue the
rule explains, not the rule. The system found the better passage and the
label penalised it. Corrected, with the reasoning recorded in
`eval/cases.yaml`.

After both fixes the suite shows no regressions. I am reporting it that way
rather than manufacturing one, because the regressions were real, were found
by hand, and the raw evidence for both is in the repository.

## A bug the suite missed, found by using the product

Worth recording separately, because Fermi will test unseen interactions and
this is the kind of thing a 17-case suite does not reach.

Driving the CLI by hand through a four-turn session — compare, then
clarify, then "take me to the audio" — produced this:

> I need to be honest: the SOURCES I have don't contain the detailed
> step-by-step breakdown of black hole entropy that I gave you in my
> previous response. […] I violated Rule 1 by inventing citations. […]
> **Can you provide the transcript excerpts from E2 with timestamps?**

The product asked *the learner* for transcripts. Trace:
`traces/session-20260910-110212-f5c431.jsonl`.

**Cause.** `locate_audio` reuses the previous turn's evidence, but took the
top `per_episode_k` hits by rank:

```python
return self.last_hits[: max(2, s.per_episode_k)], True   # first 3 of 21
```

The preceding comparison turn had retrieved 21 passages across episodes, and
the answer being asked about cited passages that sat outside the top three.
Citation repair then correctly stripped those citations as "not retrieved",
leaving the model with nothing to point at.

**Why the suite missed it.** `locate_photo51` follows a single-turn
`passage_qa` question, where the cited passages *are* the top hits. The bug
only appears when the preceding turn was a comparison (wide, many episodes)
or a clarification (evidence already carried over once). No case in the
suite chains three turns of different intents.

**Fix** (`src/app/session.py`): order reused evidence by what the previous
answer actually cited, then fill with the rest.

```python
cited = [h for h in self.last_hits if h.label in self.last_citations]
rest  = [h for h in self.last_hits if h.label not in self.last_citations]
return (cited + rest)[: max(3, len(cited))], True
```

"Take me to that part" means the part that supported the last answer, not
the part that ranked highest. Same session after the fix:

> **[E2 @ 31:33]** "For a box of gas, the entropy … grows with the volume,
> because that's where the stuff is. For a black hole, it grows with the
> area of the boundary."

The same session also exposed the model asserting *"I can't play audio — I'm
a text companion"*, which is false in the UI where every citation renders as
a seek control. Fixed in the `locate_audio` prompt.

**The suite should grow a chained-intent case.** I have not added one,
because a case written after seeing the bug tests the fix rather than the
class of bug, and I would rather say that plainly than bank the pass.

## Attribution — which mechanism actually earned the gain?

`improved` flips six flags at once, so the headline comparison cannot credit
any one of them. Each `abl_*` preset in `src/config.py` flips exactly one
flag on top of `baseline`. `make ablate` runs all of them plus two
like-for-like reference rows and writes `runs/ablations.md`.

All ablation rows are `--no-judge` runs, **including their baseline and
improved reference rows**, so every mean in that table is computed over the
same deterministic metrics. (An earlier version of this table compared
unjudged ablations against the judged baseline and inflated every delta,
because the unjudged mean omits `groundedness` — the hardest metric.)

| Row (one flag on top of baseline) | mean | fully passing | `intent_correct` | `abstention_correct` | Δ mean |
|---|---|---|---|---|---|
| baseline (naive RAG) | 0.821 | 7/17 | 40% | 100% | — |
| + BM25 hybrid (RRF) | 0.813 | 8/17 | 40% | 94% | **−0.008** |
| **+ LLM intent router** | **1.000** | **17/17** | **100%** | **100%** | **+0.179** |
| + router + query rewriting | 0.978 | 15/17 | 100% | 94% | +0.157 |
| + episode-level index | 0.834 | 8/17 | 40% | 94% | +0.013 |
| + per-episode comparison | 0.834 | 7/17 | 40% | 100% | +0.013 |
| + abstention + citation repair | 0.832 | 7/17 | 40% | **82%** | +0.011 |
| improved (all six) | 1.000 | 17/17 | 100% | 100% | +0.179 |

Full table: [`runs/ablations.md`](runs/ablations.md).

Four findings here are worth more than the headline number, and two of them
are uncomfortable:

**1. The router accounts for the entire deterministic gain.** Intent routing
alone scores +0.179 — identical to all six mechanisms together — and takes
the suite to 17/17. The product's central design claim, that these five
question shapes need different retrieval strategies and that recognising the
shape is the hard part, is the one the evidence actually supports. If I had
to ship one thing from this project, it would be the router.

**2. BM25 hybrid retrieval slightly *hurts*** (−0.008), and lowers
`retrieval_recall` from 92% to 85%. Hybrid retrieval is close to a default
recommendation in RAG write-ups, and on this corpus it is not earning its
place. A plausible reason is that contextual retrieval already solved the
problem BM25 usually rescues: every chunk carries an LLM-written header
naming its subject, so the dense vector already contains the jargon that
lexical matching would otherwise have to recover. It stays enabled in
`improved` because it does no harm at the level the full system runs at, but
on this evidence it is the first thing I would remove.

**3. Abstention alone makes refusal *worse*, not better** — `abstention_correct`
100% → 82%. This is the regression described above, isolated: without a
router, the retrieval-confidence gate fires on questions whose evidence is
not chunk-shaped, and the system refuses questions it can answer. Abstention
and routing are not independent features; the gate is only safe once the
router can tell it which turns it must not judge. Shipping abstention
without routing would have made the product measurably less trustworthy
while appearing more cautious.

**4. The ablations cannot see the groundedness gain.** They run `--no-judge`,
and the judged `groundedness` figure is too noisy at this sample size to
attribute anyway (see "How much of this is judge noise?"). So "the router
explains everything" is a claim about the deterministic metrics only. The
per-episode and episode-index mechanisms may well be carrying part of that
judged improvement; this suite cannot separate them, and I am not going to
claim they do.

Adding query rewriting on top of the router costs 0.022 (1.000 → 0.978).
With 17 cases that is one case, so I would not read a real regression into
it — but it is evidence that rewriting is not carrying the improvement
either, and that the mechanisms are not strictly additive.

## Corrections to the eval itself

Three defects in the measurement, all found by disagreeing with a result and
checking the transcript:

1. **Gold timestamp wrong** (`qa_base_pairing`) — marked the clue, not the
   rule. Widened to both ranges.
2. **Gold intent wrong** (`followup_pronoun`) — labelled `clarify_previous`,
   but "Why did that matter for Hilbert's programme?" is a new question
   containing a pronoun, not a request to restate. `clarify_previous` means
   "reuse the previous evidence without searching", which would be the wrong
   strategy. Relabelled `passage_qa`.
3. **`must_mention` too brittle** — the token `"A pairs with T"` failed a
   correct answer that said "A **always** pairs with T", because matching is
   substring-based and does not tolerate an inserted adverb. Changed to the
   invariant fragment `"pairs with t"`. Verified it still rejects unrelated
   text, so the loosening did not create a false pass.

An eval that is never wrong is an eval nobody checked.

## Still unresolved

**1. Routing answers cite chunks for card-derived claims.** Both remaining
failures. An `episode_routing` answer is written from the episode card but
cites individual chunks, so a true statement about the episode gets attached
to a passage that does not contain it. `groundedness` is 88% against a 90%
target entirely because of this. The fix is to make episode cards
first-class citable evidence with their own label form, so a routing answer
can cite the episode rather than borrowing a chunk's timestamp. Not
attempted here because it touches the citation format, the UI's
click-to-play mapping, and `citation_validity` together.

**2. Eight chunks out of 326 initially had no context header** because the
enrichment LLM returned unparseable JSON for two batches. Re-running filled
them (326/326 in the shipped artifacts), but the pipeline tolerates partial
enrichment silently rather than treating it as an error worth failing on.

**3. Local embeddings are a downgrade I chose deliberately.**
`all-MiniLM-L6-v2` (384-dim) replaced `gemini-embedding-001` (768-dim with
asymmetric query/document task types) because the hosted embedding endpoint
rate-limited to the point of being unusable on the free tier. The trade is
real — asymmetric retrieval embeddings measurably help on paraphrased
queries — and it is reversible with one line in `.env`. The upside is that
`make ingest` now needs no embedding key at all.

**4. The judge is the same model family as the generator.** Both are
`claude-haiku-4.5`. Self-preference bias in LLM-as-judge is well documented;
`groundedness` should be read as indicative, not authoritative. The
deterministic metrics — `citation_validity`, `retrieval_recall`,
`abstention_correct` — carry no such risk and are the ones I would defend.

## Cost

| Run | LLM calls | Input tokens | Output tokens | Embeddings |
|---|---|---|---|---|
| `baseline` (with judges) | 32 | 75,779 | 5,534 | 20 |
| `improved` (with judges) | 54 | 105,437 | 7,241 | 70 |
| ingest (7 cards + 41 context batches) | 50 | 101,333 | 14,483 | 333 (local) |

At `claude-haiku-4.5` pricing (\$1 / \$5 per M tokens):

| Step | Cost |
|---|---|
| `make ingest` (excluding ASR) | ~\$0.17 |
| `make eval` (both presets, judges on) | ~\$0.25 |
| `make ablate` (6 ablations + 2 references, no judges) | ~\$0.35 |
| **Total to reproduce everything** | **~\$0.77** |

Transcription of 4h44m through Groq `whisper-large-v3-turbo` ran on the free
tier at roughly 12 seconds per episode. Embeddings are `all-MiniLM-L6-v2`
running locally and cost nothing.

A note on free tiers, since it shaped the build: Groq caps at 200,000 tokens
per day per model and Gemini's free tier allowed 20 `gemini-2.5-flash`
requests per day on the project used here. Neither covers one ingest plus a
two-preset judged evaluation. Enrichment is now checkpointed per episode
(`src/ingest/enrich.py`) specifically because an early run died on a 429
with the whole pass unwritten and ten minutes of completed LLM work
discarded.

## Reproducing

```bash
make ingest     # transcribe -> chunk -> enrich -> index   (~10 min, ~$0.17)
make eval       # baseline, improved, comparison table     (~6 min,  ~$0.25)
make ablate     # per-mechanism attribution table          (~20 min, ~$0.35)
```

Artifacts are committed, so `make eval` works from a fresh clone without
re-transcribing. `make smoke` runs the whole pipeline against a synthetic
fixture with an offline stub model, needing no keys and no audio.
