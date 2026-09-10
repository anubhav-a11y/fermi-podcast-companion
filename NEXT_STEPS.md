# What's left — your steps, in order

Everything in the repo is done, committed, and verified. Three things remain
and two of them only you can do.

---

## Step 1 — Watch the product yourself (15 min)

Before recording anything, use it. You need to be able to talk about it
naturally, and you need to have seen it fail at least once.

```bash
cd fermi-podcast-companion
source .venv/bin/activate
make run                    # Streamlit at localhost:8501
```

Do this specifically:

1. Ask **"Why did Bekenstein think a black hole should have entropy?"**
2. **Click the `[E2 @ 5:25]` citation and listen.** Confirm the speaker
   actually says what the answer claimed. This is the thing you are
   selling — you should hear it work with your own ears once.
3. Ask **"Take me to the part of the audio that supports that."**
4. Ask something the episodes don't cover and watch it refuse.
5. Try to break it. Ask something ambiguous, or a three-turn chain. If you
   find a failure, that is *useful* — say so in the demo. I found one bug
   this way that the 17-case suite missed.

Sessions are saved to `traces/` automatically and are a deliverable, so
keep the good ones.

---

## Step 2 — Record the demo (45 min including retakes)

Follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md). It has the exact queries, the
timing, and what to say at each beat.

**macOS:** ⌘⇧5 → Record Entire Screen → make sure microphone is on.

Aim for 4 minutes. Two or three takes is normal. Do not edit — an unedited
screen recording reads as more honest than a polished one.

**The one moment that matters:** clicking a citation and letting the audio
play for 8–10 seconds. Everything else in the demo is supporting material.
If you only get one thing right, get that.

Save as `demo.mp4` next to the repo (not inside it — it will be large).

---

## Step 3 — Submit

Use the same "Take Home Submission Link" from Avani's email.

**Include:**
- The repo (zip it, or push to a private GitHub repo and share access)
- `demo.mp4`

**Zip it like this** — excludes the venv, the audio, and your API key:

```bash
cd ..
zip -r fermi-submission.zip fermi-podcast-companion \
  -x '*/.venv/*' -x '*/data/audio/*' -x '*/.env' \
  -x '*/__pycache__/*' -x '*/.DS_Store' -x '*/.git/*'
```

Then **verify the key is not in there**:

```bash
unzip -p fermi-submission.zip '*/.env' 2>/dev/null && echo "STOP - key leaked" || echo "safe - no .env in zip"
```

If you push to GitHub instead, `.env` is gitignored and the commit is
already clean — I verified no key appears in any tracked file.

**A short note to include with the submission:**

> The collection I received was 7 episodes / 4h44m (the brief describes 3
> files ≤3 hours), so the eval set covers all seven. Artifacts are
> committed, so `make eval` runs from a fresh clone without re-transcribing;
> `make ingest` rebuilds everything from the raw audio. `make smoke` runs
> the full pipeline offline against a fixture with no API keys, if you want
> to check the plumbing before spending anything.
>
> EVAL.md is the main document. The sections I would point at are
> "Attribution", which shows the intent router alone accounts for the entire
> deterministic gain, and "How much of this is judge noise?", which is why I
> don't claim the groundedness movement in either direction.

---

## If a grader asks you something

Be ready for these — they're the obvious questions.

**"Why local embeddings instead of a hosted model?"**
Gemini's embedding endpoint rate-limited into unusability on the free tier.
MiniLM runs in seconds locally and means `make ingest` needs no embedding
key at all. The trade is real — you lose Gemini's asymmetric query/document
task types, which help on paraphrased queries — and it's one line in `.env`
to switch back.

**"Why no vector database?"**
326 chunks × 384 dimensions. Brute-force cosine is sub-millisecond. A vector
DB would add a dependency and a failure mode to solve a problem that doesn't
exist at this size. It's the first thing that would change at catalogue
scale.

**"Your groundedness is only 71–88%. Why?"**
Two reasons, both written up. First, it's the one LLM-judged metric and it
swings by up to three cases across runs on unchanged code — the baseline and
improved ranges overlap, so at n=17 it can't resolve the difference. Second,
there's a real defect underneath it: routing answers are composed from
episode cards but cite individual chunks, so a claim that's true of the
episode gets attached to a passage that doesn't contain it. That's in "Still
unresolved" with the fix I'd make.

**"How do I know you didn't invent the gold timestamps?"**
You can check any of them. `make peek --grep <term>` prints the transcript
with timestamps. EVAL.md quotes the transcript verbatim at each cited
timestamp in the raw examples for exactly this reason.

**"What would you do next?"**
Make episode cards first-class citable evidence with their own label form,
which fixes the routing-groundedness defect. Then a chained-intent eval case
(three turns, three different intents), because that's the gap that let the
`locate_audio` bug through. Then speaker diarisation — answers currently
attribute to "the speakers" collectively.

---

## Quick reference

```bash
make smoke      # offline, no keys, no audio — proves the plumbing (~15s)
make check      # what's configured, what's missing
make run        # Streamlit UI with click-to-play citations
make chat       # terminal UI; :sources :episodes :reset :usage
make eval       # baseline + improved + comparison   (~6 min, ~$0.25)
make ablate     # per-mechanism attribution          (~20 min, ~$0.35)
make ingest     # rebuild everything from raw audio   (~10 min, ~$0.17)
make peek --grep Bekenstein     # read the transcript
```

Key documents: [EVAL.md](EVAL.md) · [PRODUCT_NOTE.md](PRODUCT_NOTE.md) ·
[README.md](README.md) · [RUNBOOK.md](RUNBOOK.md) (build log) ·
[DEMO_SCRIPT.md](DEMO_SCRIPT.md)
