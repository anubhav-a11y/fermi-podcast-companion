# Product note

## Intended user

A self-directed learner — late undergraduate, career switcher, or curious
engineer — who has 4h44m of dense long-form audio across seven episodes and
a specific question. The supplied collection is the *Great Papers* series,
and it is deliberately cross-disciplinary: special and general relativity,
Hawking radiation, the double helix, Shannon's information theory, the 2017
Transformer paper, and Turing on computability. The learner knows some
science but is unlikely to know all six fields. They are not looking to be
entertained, and they are not looking for a summary. They want to get to the
part of the audio that answers their question, understand it, and be able to
check that what they were told is actually what was said.

## The problem I chose

Long-form audio is close to unsearchable. Nearly five hours of conversation
contains a few hundred substantive ideas, each buried at some unmarked
timestamp inside a discursive discussion, and the learner cannot find them
without listening to all of it. So the obvious product is search-plus-chat.

But the obvious product has an obvious failure mode, and it is the one that
matters here. Every paper in this collection is famous, so a language model
asked about Hawking radiation or base pairing will answer fluently from its
own training data whether or not the episodes discuss it — and it will often
be *correct*, just not grounded. The learner cannot tell the difference
between an answer from the audio and an answer from the model's memory of a
textbook. That failure is worse than
useless — it is a companion that quietly stops being about the podcast while
still sounding like it is.

So I framed the problem as **verifiable retrieval, not conversation**: the
learner should always be able to see which passage an answer came from, hear
it, and be told plainly when the collection does not cover something.

Three concrete needs follow:

1. **Find where an idea lives.** "Why did Bekenstein think a black hole has
   entropy?" should return the passage where the speakers actually argue it,
   not a paraphrase of Wikipedia.
2. **Choose where to spend five hours.** "Which episodes should I listen to
   to understand entropy?" is a different question from a content question,
   and needs a different answer shape — here the honest answer names two
   episodes, E2 and E4, that use the word in genuinely different senses.
3. **Trust the answer.** Every claim cited, every citation playable, and a
   refusal when the audio does not support an answer.

## What I decided, and why

**Citations are timestamps, and timestamps are playable.** This is the spine
of the product. It makes grounding something the learner can check in one
click rather than something I claim in a README, and it turns the brief's
"take me to the part of the original audio" from a feature into a
side-effect. It also constrains chunking: ~60 second windows, because a
citation to a 5-minute block is not a citation.

**Five intents, not one.** I started with plain chunk RAG and it failed
badly on two of the brief's own example questions. "Which episode should I
listen to?" cannot be answered from a 60-second passage, because no single
passage says what an episode is *about* — that needs an episode-level index.
"Compare how the black hole episode and the Shannon episode use the word
entropy" retrieves six passages from whichever episode is most verbose,
which makes a fair comparison impossible
— that needs per-episode retrieval. Routing to different strategies was the
single highest-value structural decision in the build.

**Refusal is a feature, and it is tested in both directions.** Three out-of-
scope cases in the eval suite must be refused; the rest must *not* be. Note
that "out of scope" here is not the same as "not physics": the collection
covers molecular biology, information theory and mathematical logic too, so
each refusal case was checked against the full transcript to confirm the
topic is genuinely absent rather than merely off-genre. A
system can score perfectly on "did it refuse when it should" by refusing
everything, so measuring only one direction is measuring nothing.

**Verification is code, not a model judging itself.** Citation validity,
retrieval recall and abstention correctness are all computed
deterministically. Only groundedness and helpfulness use an LLM judge, and
that judge sees only the cited passages — so it checks support, not recall.

This turned out to matter more than I expected. Across four runs of each
preset, the deterministic metrics were *identical every time*
(`intent_correct` 6/15 baseline, 15/15 improved, zero variance), while the
LLM judge's groundedness score swung by up to three cases on unchanged
code — enough that its baseline and improved ranges overlap. The
deterministic metrics are the ones this product's claims rest on, and that
is a design choice, not an accident.

**Baseline and improved are feature flags in one codebase.** The brief asks
for a measured before-and-after. Implementing that as two branches, or as a
remembered earlier state, makes the comparison unreproducible. As flags
(`src/config.py`), anyone can re-derive both numbers from one ingest pass.

## What I deliberately did not build

- **Speaker diarisation.** Real cost, and the questions I care about are
  about ideas, not about who said them. Answers attribute to "the speakers".
  This is the first thing I would add with more time.
- **A polished frontend.** A stated non-goal. The UI exists to demonstrate
  click-to-play citations; everything else about it is plain Streamlit.
- **Catalogue scale.** Seven episodes, 326 chunks, exact search over a
  numpy array, no vector store. At this size a vector database would add a
  dependency and a failure mode to solve a problem that does not exist —
  brute-force cosine over 326×384 floats is sub-millisecond. This is the
  correct engineering answer here, not a shortcut, and it is the first thing
  that would have to change at catalogue scale.
- **Study aids** (quizzes, flashcards, notes). Plausible and easy to bolt
  on, but they would trade depth on grounding for breadth of features, and
  grounding is what the collection actually needs.

## What the evidence changed my mind about

Two beliefs I started with did not survive contact with the measurements,
and saying so is more useful than a tidy narrative.

**I expected hybrid BM25 + dense retrieval to be a clear win.** It is close
to a default recommendation, and jargon-heavy audio is exactly the case it
is supposed to help. Measured on its own it *slightly hurts* (mean 0.813 vs
0.821 baseline, `retrieval_recall` 92% → 85%). The likely reason is that
contextual retrieval already covers the same ground: every chunk carries an
LLM-written header naming its subject, so the jargon BM25 would rescue is
already in the dense vector. I left it on because it is harmless in the full
system, but the evidence says it is the first thing to remove.

**I expected the improvement to be spread across five mechanisms.** It is
not. Intent routing alone accounts for the entire deterministic gain
(+0.179, identical to all six flags together). The episode index,
per-episode comparison and abstention gate each contribute ~0.01 on their
own. The product's thesis — that these question shapes need different
retrieval strategies — holds, but the load-bearing part is *recognising the
shape*, not the strategies themselves.

There is also one thing the evidence made worse before it made it better:
the abstention gate, measured alone, drops refusal accuracy from 100% to
82%, because it fires on routing questions whose evidence is not
chunk-shaped and refuses questions the system can answer. Abstention and
routing are not independent features. Shipping the gate without the router
would have made the product measurably less trustworthy while looking more
cautious.

## How I would know it is working

The learner asks a question, gets an answer they can check against the audio
in one click, and is told honestly when the episodes do not cover something.
The measurable version of that is in [EVAL.md](EVAL.md): citation validity,
retrieval recall, abstention accuracy in both directions, and groundedness
against cited passages only.
