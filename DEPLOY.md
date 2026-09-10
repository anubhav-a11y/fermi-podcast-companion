# Deploying the hosted demo

The repo is prepared for this — portable audio paths, committed 24 kbps
audio, a password gate, and a lean `requirements.txt`. What remains is one
browser step that needs your GitHub/Streamlit login, which is why it isn't
already done.

**Target: Streamlit Community Cloud.** Free, native Streamlit, and the app's
measured peak memory is ~415 MB against their ~1 GB limit, so it fits.

> Hugging Face Spaces was the first choice — 16 GB RAM on their free CPU
> tier — but HF now requires a **PRO subscription ($9/mo)** for any Docker
> or Gradio Space, public or private. Only static Spaces are free, and those
> cannot run a Python backend. If you already have PRO, Spaces is the better
> host; `app.py` and `requirements.txt` work there unchanged with a
> three-line Dockerfile.

---

## Before you start: cap your spend (2 min)

The app calls OpenRouter on every question. Even behind a password, put a
ceiling on it:

**https://openrouter.ai/settings/limits** → set a credit limit. $5 is ample;
the full 17-case evaluation costs about $0.25.

---

## Deploy (5 min)

1. **https://share.streamlit.io** → sign in with GitHub.

2. **Create app** → **Deploy a public app from a repo**. When it asks for
   repository access, grant it — the repo is private, so Streamlit's GitHub
   app needs permission to read it.

3. Fill in:

   | Field | Value |
   |---|---|
   | Repository | `anubhav-a11y/fermi-podcast-companion` |
   | Branch | `main` |
   | Main file path | `app.py` |
   | Python version | `3.11` (or 3.12) |

4. Before clicking Deploy, open **Advanced settings → Secrets** and paste
   exactly this, substituting your real OpenRouter key:

   ```toml
   OPENROUTER_API_KEY = "sk-or-v1-your-key-here"
   FERMI_LLM_PROVIDER = "openrouter"
   FERMI_OPENROUTER_MODEL = "anthropic/claude-haiku-4.5"
   FERMI_EMBED_PROVIDER = "local"
   FERMI_APP_PASSWORD = "pick-something-and-share-it-with-fermi"
   ```

   Your key is in your local `.env` — `grep OPENROUTER .env`. Streamlit
   secrets are not exposed to visitors.

5. **Deploy.** First build takes 5–10 minutes, mostly installing torch.

---

## Then check it works

Open the URL, enter the password, and:

1. Ask **"Why did Bekenstein think a black hole should have entropy?"**
2. Expand the sources and **press play on `[E2 @ 5:25]`**.

If the audio plays, the deployment is genuinely working — that is the one
thing worth verifying, because it is the feature the whole product is built
around and the thing most likely to break when hosted.

---

## If the build fails

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: torch` | pip skipped the CPU index | Remove the `--extra-index-url` line from `requirements.txt`; the default wheel works, it is just larger |
| Killed / "app is over its resource limits" | torch + MiniLM too big for the box | Set `FERMI_EMBED_PROVIDER = "none"` in Secrets. Retrieval falls back to BM25 only — weaker on paraphrased questions, but it runs in ~80 MB. Say so in the demo if you use it |
| Citations show text but will not play | audio missing | Confirm `data/audio_web/` has 7 files on `main` |
| Every answer refuses | key missing or wrong | Check Secrets; a bad key surfaces as retrieval scoring zero |
| Slow first question | model download | `all-MiniLM-L6-v2` (~90 MB) is fetched once on cold start |

---

## What the hosted copy is and is not

It runs the **improved** preset by default, with the sidebar preset selector
live so a reviewer can switch to `baseline` and watch the same question get
worse — which is a better argument than any table.

It serves 24 kbps mono audio rather than the supplied originals: 53 MB
instead of 273 MB, durations byte-exact so every timestamp in the index
stays valid. Speech is clearly intelligible, which is all that is needed to
verify a citation.

It is password-gated for two reasons that are not security theatre: every
question spends real API credit, and the index contains full transcripts of
audio that belongs to Fermi rather than to this repo.
