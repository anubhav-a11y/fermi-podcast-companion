# Fermi Podcast Companion

A grounded conversational companion for a fixed collection of seven
long-form episodes on landmark scientific papers — 4h44m of audio spanning
relativity, black-hole thermodynamics, the double helix, information theory,
the Transformer architecture and computability. Built from the supplied raw
audio only: no platform captions, transcripts or caption APIs are used
anywhere in this repo.

Every factual claim in an answer carries a citation like `[E2 @ 5:25]`, and
in the UI that citation expands into an audio player seeked to that second.
When the collection does not cover something, the product says so instead of
answering from general knowledge.

| | Episode | Length |
|---|---|---|
| E1 | Einstein's Special Relativity | 52:14 |
| E2 | How Black Holes Radiate, Hawking 1975 | 45:17 |
| E3 | The Double Helix, Watson and Crick 1953 | 43:16 |
| E4 | Shannon and the Birth of Information, 1948 | 39:52 |
| E5 | Attention Is All You Need, 2017 | 36:24 |
| E6 | General Relativity, Einstein 1915 | 33:48 |
| E7 | On Computable Numbers, Turing 1936 | 33:02 |

**Measured result:** mean case score 0.816 → 0.980 and `intent_correct`
40% → 100% from baseline to improved, over 17 hand-labelled evaluation
cases. See [EVAL.md](EVAL.md).

---

## Hosted demo

`app.py` + [DEPLOY.md](DEPLOY.md) deploy this to Streamlit Community Cloud
in about five minutes (measured peak memory ~415 MB, inside their limit).
The hosted copy serves committed 24 kbps audio so click-to-play citations
work, and sits behind a shared password because each question spends API
credit and the index holds transcripts of audio that is not mine to publish.

## Quickstart

### 0. Verify the plumbing first (no API keys, no audio, ~15 seconds)

```bash
python -m venv .venv && source .venv/bin/activate
pip install numpy python-dotenv PyYAML
make smoke
```

This builds a small synthetic corpus, runs both eval presets against it with
an offline stub model, and prints the comparison table. It proves the
pipeline works before you spend an hour on transcription or a cent on API
calls. The numbers it prints are meaningless — the fixture text is invented.

### 1. Real setup

```bash
make setup                  # venv + dependencies + .env
source .venv/bin/activate
# put your API key(s) in .env
make check                  # tells you exactly what is missing
```

You need **one** chat provider key. OpenRouter, Gemini, Anthropic, OpenAI
and Groq are all supported; pick whichever you have. Embeddings run locally
by default and need no key. Transcription needs no key with
`FERMI_ASR_PROVIDER=local`.

**The configuration this repo's results were produced with** — one key,
local embeddings, hosted Whisper:

```
OPENROUTER_API_KEY=sk-or-...
FERMI_LLM_PROVIDER=openrouter
FERMI_OPENROUTER_MODEL=anthropic/claude-haiku-4.5
FERMI_EMBED_PROVIDER=local
FERMI_ASR_PROVIDER=groq        # or `local` for faster-whisper, no key
```

A note on free tiers, learned the hard way: Groq caps at 200k tokens/day
per model and Gemini's free tier allowed 20 `gemini-2.5-flash` requests/day
on the project used here. Both are too small for a full ingest plus a
two-preset evaluation. `make ingest` and `make eval` together cost about
**\$0.42** on OpenRouter with `claude-haiku-4.5`.

Alternative all-Gemini setup:

```
GEMINI_API_KEY=...
FERMI_LLM_PROVIDER=gemini
FERMI_EMBED_PROVIDER=gemini
FERMI_ASR_PROVIDER=local
```

Anthropic or Groq don't offer embedding models, so pair them with
`FERMI_EMBED_PROVIDER=local` (free, `pip install sentence-transformers`) or
`openai` if you have that key too. `none` falls back to BM25-only retrieval —
it works, but loses paraphrase matching.

`ffmpeg` should be installed.

### 2. Add the audio

Download the three supplied Fermi Podcast files into `data/audio/`. Any
common format works. Filenames become episode labels, so name them sensibly.

### 3. Build the corpus (one command)

```bash
make ingest
```

Runs transcribe → chunk → enrich → index. On CPU with `medium.en` this takes
roughly 1–1.5× real time, so budget about 2–3 hours for 3 hours of audio, or
set `FERMI_ASR_PROVIDER=groq` for a few minutes instead. Transcription is
cached per episode; re-running skips work already done.

Then check the ASR actually worked before building on it:

```bash
make peek                       # sample each episode
make peek --grep Bekenstein     # check a specific jargon term
```

If names and jargon are mangled, fix it here — bump `FERMI_WHISPER_MODEL` or
extend `JARGON_PROMPT` in `src/config.py`. Every later stage inherits these
errors.

### 4. Use it

```bash
make run      # Streamlit UI with click-to-play citations
make chat     # terminal REPL
```

### 5. Evaluate it

```bash
make eval     # baseline run + improved run + comparison table
make ablate   # per-mechanism attribution: which single flag earned the gain
```

Writes `runs/baseline/`, `runs/improved/` and `runs/comparison.md`. See
[EVAL.md](EVAL.md).

---

## What it does

Five intents, each with its own retrieval strategy, because these questions
have genuinely different shapes and one index cannot serve them all:

| Intent | Example | Retrieval |
|---|---|---|
| `passage_qa` | "Why does a black hole have entropy?" | hybrid chunk search |
| `episode_routing` | "Which episodes cover entropy?" | episode cards, not chunks |
| `cross_episode_compare` | "Compare the two senses of entropy" | k hits per episode, then fuse |
| `clarify_previous` | "I didn't follow that, step by step" | reuse last turn's evidence |
| `locate_audio` | "Take me to the part that supports that" | last turn's evidence + timestamp |

Routing and query rewriting happen in a single LLM call — they need the same
input and the same reasoning, so splitting them would double cost for no
accuracy gain. A rule-based fallback runs whenever the model output fails to
parse, so the product degrades instead of crashing.

## Architecture

```
data/audio/  ──► transcribe.py ──► chunk.py ──► enrich.py ──► index.py
                 faster-whisper    ~60s          episode        embeddings
                 or Groq           sentence-     cards +        (numpy)
                 + jargon prompt   aligned       chunk
                                   + overlap     contexts
                                                                    │
   cli.py / ui.py ──► session.py ──► router.py ──► retrieve.py ◄────┘
                      one turn       intent +      dense + BM25
                           │         rewrite       fused with RRF
                           ▼                            │
                      answer.py ◄────────────────────────┘
                      citation contract, abstention gates,
                      post-hoc citation validation
                           │
                           ├──► traces/*.jsonl
                           └──► eval/run.py ──► runs/{baseline,improved}/
```

`Companion.ask()` in `session.py` is the single entry point. The CLI, the UI
and the eval harness all go through it, so the evaluation measures the
shipped product rather than a parallel reimplementation.

### Trustworthiness, enforced in three places

1. **Citation contract.** Sources are presented as labelled blocks and the
   model must copy those labels verbatim onto claims.
2. **Two abstention gates.** A retrieval gate (max cosine below threshold)
   and a semantic gate (the model emits `NOT_COVERED:`). Either fires a
   refusal. The retrieval gate is deliberately skipped for follow-ups that
   reuse prior evidence — those queries have no searchable content, so
   gating on their scores makes the product refuse to clarify itself.
3. **Post-hoc citation validation.** Every emitted label is checked against
   what was actually retrieved this turn. Invalid ones are recorded and
   stripped. A hallucinated timestamp never reaches the learner.

None of this trusts the model to behave. It is all checked after the fact,
which is also what lets the eval harness measure it.

### Notable trade-offs

- **No vector database.** ~200 chunks is a 1.2 MB float32 matrix; exact
  cosine search is one numpy matmul. A vector store would be infrastructure
  without a benefit at this scale.
- **BM25 hand-written (~40 lines) rather than a dependency.** Easy to read,
  one less thing to install, fast enough for 200 documents.
- **~60 second chunks.** Short enough that a citation points at a precise
  spot in the audio, long enough that a spoken explanation is not cut in
  half. ASR segments (2–8 s) are far too small to answer from.
- **Contextual headers on chunks.** Standalone spoken passages are full of
  unresolved pronouns, which embed poorly. A one-line LLM-generated header
  restores the missing subject before embedding. Batched 8 per call.
- **One provider wrapper** (`src/app/llm.py`) behind chat and embeddings, so
  the model choice is a config line rather than a rewrite. Gemini's
  asymmetric retrieval embeddings get the correct task type
  (`RETRIEVAL_DOCUMENT` at index time, `RETRIEVAL_QUERY` at search time),
  which other providers ignore.
- **Baseline and improved are feature flags, not branches** (`src/config.py`).
  One ingest pass, two eval commands, a reproducible comparison.

## Layout

```
src/config.py          paths, providers, and the baseline/improved presets
src/ingest/            transcribe → chunk → enrich → index
src/app/llm.py         provider wrapper (anthropic|openai|groq|stub) + embeddings
src/app/router.py      intent classification + conversational query rewriting
src/app/retrieve.py    hybrid chunk / episode / per-episode search, BM25, RRF
src/app/answer.py      citation contract, abstention, citation validation
src/app/session.py     one turn end to end; writes traces
src/app/cli.py         terminal REPL
src/app/ui.py          Streamlit UI with audio seek
eval/cases.yaml        17 cases across 5 intents and 7 episodes
eval/run.py            runner; preserves raw inputs and outputs
eval/judges.py         deterministic metrics + LLM groundedness judge
eval/report.py         baseline vs improved markdown comparison
scripts/check_setup.py preflight diagnostics
scripts/peek.py        transcript inspection
traces/                per-session JSONL: input → retrieval → response
runs/                  raw eval results and summaries
```

## Cost

For 3 hours of audio: transcription is free locally, embeddings are ~$0.01
(or free on Gemini's free tier), chunk contexts are ~200 short calls, and
each eval run is ~15 cases × 2 calls plus judging. On Gemini Flash the whole
project fits comfortably in a free-tier allowance. Actual token counts are
recorded in every `summary.json` under `usage`.

## Notes and limits

- Model names are env-overridable (`FERMI_GEMINI_MODEL`,
  `FERMI_ANTHROPIC_MODEL`, etc.) because provider catalogues change; adjust
  if a name has moved on.
- Speaker diarisation is not implemented. Answers attribute to "the
  speakers" collectively rather than to named individuals.
- ASR errors propagate. `make peek` exists so you catch them deliberately
  rather than discovering them in an answer.
- `artifacts/` is committed so the system runs without re-transcribing;
  `data/audio/` is gitignored since the audio is not ours to redistribute.
