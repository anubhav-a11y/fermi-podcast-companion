# Demo recording script — 4 minutes

Screen recording only, no editing needed. Talk over it.
QuickTime on macOS: **File → New Screen Recording** (or ⌘⇧5). Record the
whole screen, include microphone.

**Before you hit record**

```bash
cd fermi-podcast-companion
source .venv/bin/activate
make run                      # Streamlit opens at localhost:8501
```

Have a second terminal tab ready with the repo, for the eval section at the end.
Close Slack/mail notifications. Make the browser window large.

---

## 0:00 — What this is (20s, on the Streamlit landing screen)

> "This is a grounded companion for a collection of seven podcast episodes
> on landmark scientific papers — about four and three quarter hours of
> audio, spanning relativity, black hole thermodynamics, DNA, information
> theory, the Transformer paper and Turing's computability paper.
>
> The whole product is built around one idea: every claim it makes is
> traceable to a specific second of the source audio. Let me show you what
> that means."

Point at the sidebar showing the 7 episodes and the chunk count.

---

## 0:20 — A content question, then the click-to-play moment (70s)

**Type:**

```
Why did Bekenstein think a black hole should have entropy?
```

While it answers:

> "This is a real physics question, and a language model could answer it
> fluently from its own training data. That's exactly the failure mode I
> designed against — the learner can't tell the difference between an
> answer from the audio and an answer from the model's memory."

When the answer appears, point at the citations:

> "Every factual claim carries a timestamp. And these aren't decorative."

**Now click the `[E2 @ 5:25]` citation. Let the audio actually play for
8–10 seconds.** Let the viewer hear the speaker say the thing the answer
claimed.

> "That's the product. The answer said Bekenstein imagined an entropy
> disposal machine, and there it is, in the speakers' own words, at the
> second the citation pointed to. Trustworthiness you can check in one
> click, rather than trustworthiness I assert in a README."

**This is the moment the demo lives or dies on. Don't rush it.**

---

## 1:30 — The follow-up that needs conversational memory (40s)

**Type:**

```
Take me to the part of the audio that supports that.
```

> "This is one of the brief's own example interactions, and it's harder
> than it looks. 'That' has no meaning on its own — there's nothing in
> those words to search for. The system has to resolve the pronoun against
> the previous turn before it retrieves anything.
>
> In my baseline, this exact case scored 0.167 out of 1 — the worst case in
> the whole suite. It searched the literal words and came back with
> passages from the Turing and Shannon episodes."

Point at the debug line showing `intent=locate_audio` and the rewritten query.

> "Now it classifies the intent, rewrites the question into something
> searchable, and reuses the evidence from the turn before."

---

## 2:10 — Routing: a question no single passage can answer (40s)

**Type:**

```
Which episodes should I listen to if I want to understand entropy, and why?
```

> "This one is structurally different. No sixty-second passage says what an
> episode is *about*, so chunk retrieval can't answer it — my baseline
> recommended one episode and missed the other entirely.
>
> The honest answer names two episodes that use the word entropy in
> genuinely different senses: Shannon's information entropy, and
> Bekenstein-Hawking black hole entropy. It even suggests an order to
> listen in."

---

## 2:50 — The refusal (35s)

**Type:**

```
How do these episodes explain superconductivity and BCS theory?
```

> "Superconductivity appears nowhere in these seven episodes — I grepped
> the full transcript to confirm zero hits before writing this as a test
> case. A model asked this will answer confidently and correctly from
> training data, and that answer would be worse than useless here, because
> the product would have quietly stopped being about the podcast.
>
> Instead it refuses, and tells the learner what the collection *does*
> cover — which is the useful half of a refusal."

---

## 3:25 — The evaluation (60s, switch to terminal)

```bash
cat runs/comparison.md
```

> "Seventeen hand-labelled cases across five question types. Every gold
> timestamp was read off the actual transcript — I didn't invent any,
> because the whole point of the suite is catching invented timestamps.
>
> Baseline to improved: mean case score 0.84 to 0.95, and intent
> classification 40 percent to 100 percent. Seven of the eight metrics are
> deterministic, and all seven are at 100 percent after the improvement."

```bash
cat runs/ablations.md
```

> "But 'improved' flips six flags at once, so that comparison can't tell
> you which change earned the gain. So each of these presets flips exactly
> one.
>
> Two findings I didn't expect. The intent router alone accounts for the
> *entire* deterministic improvement — same delta as all six mechanisms
> together. And BM25 hybrid retrieval, which is close to a default
> recommendation, very slightly *hurts* on this corpus.
>
> Abstention alone actually makes refusal worse — a hundred percent down to
> eighty-two — because the confidence gate fires on routing questions whose
> evidence isn't chunk-shaped. Abstention and routing aren't independent
> features, and shipping the gate without the router would have made the
> product less trustworthy while looking more cautious."

---

## 4:25 — Close (20s)

> "Two things I'd flag honestly. Groundedness is an LLM judge, and across
> four runs it swings by up to three cases on unchanged code — the baseline
> and improved ranges overlap, so I don't claim that number in either
> direction. And routing answers still cite individual chunks for claims
> that come from the episode summary, which is a real defect I've written
> up rather than papered over.
>
> All the raw records, both pre-fix runs where I found the regressions, and
> the failure analysis are in the repo. EVAL.md has the detail."

---

## If something goes wrong mid-recording

- **Slow answer** — normal, 3–8s per turn. Keep talking.
- **Audio doesn't play** — check the browser tab isn't muted. Fall back to
  `make chat` then `:sources`, which prints the passage text with timestamps.
- **A citation looks wrong** — say so out loud and move on. Noticing it is
  better than hoping nobody else does.

## Don't

- Don't apologise for the plain UI. It's a stated non-goal in the brief.
- Don't claim it's perfect. The honest limitations are the strongest part.
- Don't read this script word for word. These are the beats, not a lecture.
