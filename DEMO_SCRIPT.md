# Demo video script — 4 minutes

Screen recording, no editing. Everything below was run and verified, so the
outputs are what you will actually see.

---

## Setup (do this before recording)

```bash
cd fermi-podcast-companion
source .venv/bin/activate
make run                       # http://localhost:8501
```

- **Second terminal tab** open in the repo, for the eval section.
- Browser window large, sidebar visible (that's where the preset selector is).
- Volume up and **unmuted** — you are going to play audio on camera.
- Silence notifications.

If you also have the Streamlit Cloud link live, use it instead of localhost —
mention in one line that it's deployed and password-gated. Local is fine and
one less thing to break.

---

## 0:00 — What it is (20s)

*(on the landing screen, sidebar showing 7 episodes)*

> "This is a grounded companion for seven podcast episodes on landmark
> scientific papers — four and three quarter hours of audio, covering
> relativity, black holes, DNA, information theory, the Transformer paper
> and Turing on computability.
>
> One idea runs through the whole thing: every claim it makes is traceable
> to a specific second of the source audio. Let me show you."

---

## 0:20 — The money shot: a real answer, then play the citation (70s)

**Type:**

```
Why did Bekenstein think a black hole should have entropy?
```

*While it thinks:*

> "This is a genuine physics question, and a language model would answer it
> fluently from training data whether or not these episodes discuss it. The
> learner can't tell the difference — that's the failure mode I designed
> against."

*Answer appears with `[E2 @ 4:26]` and `[E2 @ 5:25]`.*

> "Every factual claim carries a timestamp. And these aren't decoration."

**Expand the sources, and press play on `[E2 @ 5:25]`. Let it run 10 seconds.**

You will hear, roughly:

> *"…take a cup of hot gas, which has a lot of entropy, and toss it into a
> black hole. It's gone… You'd have a perfect entropy disposal machine…"*

> "That's the product. The answer said Bekenstein imagined an entropy
> disposal machine, and there it is in the speakers' own words, at the
> second the citation pointed to. Trustworthiness you can check in one
> click, rather than trustworthiness I assert in a README."

**Do not rush this. If you get one thing right, get this.**

---

## 1:30 — A follow-up with no subject in it (35s)

**Type:**

```
What was Photograph 51 and what did it show?
```

*It answers, citing `[E3 @ 11:04]`. Then type:*

```
Take me to the part of the audio that supports that.
```

> "This is one of the brief's own example interactions, and it's harder
> than it looks. 'That' has no searchable content — nothing in those words
> mentions DNA. The system has to resolve the pronoun against the previous
> turn before it retrieves anything."

*Point at the debug line: `intent=locate_audio`, and the rewritten query.*

> "It classifies the intent, rewrites the question into something
> searchable, and reuses the evidence from the turn before."

---

## 2:05 — The A/B: break it live (65s)  ← strongest beat

> "Now let me show you why any of this was necessary. The naive version of
> this system is one dropdown away."

**In the sidebar, switch Preset from `improved` to `baseline`.**

> "Baseline is competent naive RAG — one index, top-k chunks, answer. No
> intent routing, no query rewriting. That's what a first attempt looks
> like. Same two questions."

**Type:**

```
What was Photograph 51 and what did it show?
```

*It answers fine. Then:*

```
Take me to the part of the audio that supports that.
```

**What you will see** — verified:

```
intent    : passage_qa                     (not locate_audio)
retrieved : E4 @ 39:44, E7 @ 33:00, E4 @ 20:01, E2 @ 28:01 ...
citations : none
```

> "Look at what it retrieved. Shannon, Turing, Hawking — every passage from
> the wrong episode. Photograph 51 is in episode three. It searched the
> literal words 'take me to the part of the audio', found nothing about
> DNA, and now it won't answer at all.
>
> Same corpus, same index, same model. The only difference is that this
> version doesn't know what kind of question it was asked. In my evaluation
> this exact case scored 0.167 out of 1 on baseline and 1.0 on improved."

**Switch back to `improved`.**

---

## 3:10 — The refusal (30s)

**Type:**

```
How do these episodes explain superconductivity and BCS theory?
```

> "Superconductivity appears nowhere in these seven episodes — I grepped
> the full transcript to confirm zero hits before writing this as a test
> case. A model asked this will answer confidently and correctly from
> training data, and that answer is worse than useless here, because the
> product would have quietly stopped being about the podcast.
>
> Instead it refuses, and names what the collection *does* cover — which is
> the useful half of a refusal."

---

## 3:40 — Evaluation and attribution (45s, switch to terminal)

```bash
cat runs/comparison.md
```

> "Seventeen hand-labelled cases across five question types. Every gold
> timestamp read off the real transcript — I invented none, because the
> whole point of the suite is catching invented timestamps.
>
> Mean case score 0.84 to 0.95. Intent classification 40 to 100 percent.
> Seven of the eight metrics are deterministic, and all seven hit 100."

```bash
cat runs/ablations.md
```

> "But improved flips six flags at once, so that can't tell you which
> change earned it. Each of these presets flips exactly one.
>
> Two things I didn't expect. The intent router alone accounts for the
> entire deterministic gain — same delta as all six together. And BM25
> hybrid retrieval, which is close to a default recommendation, very
> slightly hurts on this corpus.
>
> Abstention alone actually makes refusal worse — 100 percent down to 82 —
> because the confidence gate fires on routing questions whose evidence
> isn't chunk-shaped. Shipping it without the router would have made the
> product less trustworthy while looking more cautious."

---

## 4:25 — Close on the limits (20s)

> "Two honest caveats. Groundedness is the one LLM-judged metric, and across
> four runs it swings by up to three cases on unchanged code — the baseline
> and improved ranges overlap, so I don't claim that number in either
> direction. And routing answers still cite individual chunks for claims
> that come from the episode summary, which is a real defect I've written
> up rather than papered over.
>
> All the raw records, both pre-fix runs where I found the regressions, and
> the failure analysis are in EVAL.md."

---

## Quick reference — everything you type, in order

```
Why did Bekenstein think a black hole should have entropy?
What was Photograph 51 and what did it show?
Take me to the part of the audio that supports that.
   [switch sidebar preset -> baseline]
What was Photograph 51 and what did it show?
Take me to the part of the audio that supports that.
   [switch sidebar preset -> improved]
How do these episodes explain superconductivity and BCS theory?
   [terminal] cat runs/comparison.md
   [terminal] cat runs/ablations.md
```

## If something goes wrong

- **Slow answer** (3–8s is normal) — keep talking, don't sit in silence.
- **Audio won't play** — check the tab isn't muted. Fallback: `make chat`
  then `:sources`, which prints passage text with timestamps.
- **A citation looks wrong** — say so out loud and move on. Noticing beats
  hoping nobody else does.
- **Switching preset seems to hang** — it rebuilds the index cache on first
  use of a preset; give it a few seconds.

## Don't

- Don't apologise for the plain UI — a polished frontend is a stated
  non-goal in the brief.
- Don't claim it's perfect. The limits section is the strongest 20 seconds
  in the video.
- Don't read this aloud. These are beats, not a teleprompter.
