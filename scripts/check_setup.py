"""Preflight check.  python scripts/check_setup.py  (or: make check)

Tells you exactly what is and isn't ready, and what to run next.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

OK, WARN, BAD = "  ok  ", " warn ", " MISS "
issues: list[str] = []


def line(state: str, label: str, detail: str = "") -> None:
    print(f"[{state}] {label:<34s} {detail}")


def has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


print("\n=== dependencies ===")
for mod, why, required in [
    ("numpy", "vector math", True),
    ("yaml", "eval cases", True),
    ("dotenv", "env loading", True),
    ("streamlit", "web UI", False),
    ("anthropic", "LLM provider", False),
    ("openai", "LLM + embeddings", False),
    ("google.genai", "Gemini LLM + embeddings", False),
    ("groq", "hosted Whisper / LLM", False),
    ("faster_whisper", "local transcription", False),
    ("sentence_transformers", "local embeddings", False),
]:
    if has(mod):
        line(OK, mod, why)
    elif required:
        line(BAD, mod, f"{why} — REQUIRED")
        issues.append(f"pip install {mod}")
    else:
        line(WARN, mod, f"{why} — not installed")

print("\n=== external tools ===")
for tool, why in [("ffmpeg", "audio decode/downsample"), ("ffprobe", "duration probe")]:
    if shutil.which(tool):
        line(OK, tool, why)
    else:
        line(WARN, tool, f"{why} — install ffmpeg if transcription fails")

print("\n=== configuration ===")
line(OK, "llm provider", config.LLM_PROVIDER)
line(OK, "embed provider", config.EMBED_PROVIDER)
line(OK, "asr provider", config.ASR_PROVIDER)
_MODEL_OF = {"openrouter": getattr(config, "OPENROUTER_MODEL", ""),
             "anthropic": config.ANTHROPIC_MODEL, "openai": config.OPENAI_MODEL,
             "gemini": config.GEMINI_MODEL, "groq": config.GROQ_MODEL}
if _MODEL_OF.get(config.LLM_PROVIDER):
    line(OK, "llm model", _MODEL_OF[config.LLM_PROVIDER])

needed_keys = []
if config.LLM_PROVIDER == "anthropic":
    needed_keys.append("ANTHROPIC_API_KEY")
if config.LLM_PROVIDER == "openai" or config.EMBED_PROVIDER == "openai":
    needed_keys.append("OPENAI_API_KEY")
if config.LLM_PROVIDER == "groq" or config.ASR_PROVIDER == "groq":
    needed_keys.append("GROQ_API_KEY")
if config.LLM_PROVIDER == "openrouter":
    needed_keys.append("OPENROUTER_API_KEY")

if config.LLM_PROVIDER == "stub":
    line(WARN, "api keys", "stub provider — no keys needed, no real answers either")

# Gemini accepts either name; only complain if both are absent.
if config.LLM_PROVIDER == "gemini" or config.EMBED_PROVIDER == "gemini":
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        line(OK, "GEMINI_API_KEY", "set")
    else:
        line(BAD, "GEMINI_API_KEY", "not set — add it to .env")
        issues.append("set GEMINI_API_KEY in .env")

for key in dict.fromkeys(needed_keys):
    if os.getenv(key):
        line(OK, key, "set")
    else:
        line(BAD, key, "not set — add it to .env")
        issues.append(f"set {key} in .env")

print("\n=== audio ===")
audio_dir = config.AUDIO_DIR
if not audio_dir.exists():
    line(BAD, "data/audio", "directory missing")
    issues.append("create data/audio and put the 3 supplied files there")
else:
    exts = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".mp4", ".webm", ".aac"}
    files = [p for p in audio_dir.iterdir() if p.suffix.lower() in exts]
    if not files:
        line(BAD, "audio files", f"none found in {audio_dir}")
        issues.append("download the 3 supplied Fermi Podcast files into data/audio/")
    else:
        total_mb = sum(p.stat().st_size for p in files) / 1e6
        line(OK, "audio files", f"{len(files)} file(s), {total_mb:.0f} MB")
        for p in files:
            print(f"          - {p.name} ({p.stat().st_size/1e6:.0f} MB)")

print("\n=== artifacts ===")
for path, label, nxt in [
    (config.TRANSCRIPTS_JSON, "transcripts.json", "make transcribe"),
    (config.CHUNKS_JSON, "chunks.json", "make chunk"),
    (config.EPISODES_JSON, "episodes.json", "make enrich"),
    (config.INDEX_META_JSON, "index_meta.json", "make index"),
]:
    if path.exists():
        try:
            data = json.loads(path.read_text())
            n = len(data.get("episodes", data.get("chunks", [])))
            extra = f"{n} records" if n else ""
        except Exception:
            extra = "unreadable"
        line(OK, label, extra)
    else:
        line(WARN, label, f"not built — run: {nxt}")

if config.INDEX_META_JSON.exists():
    meta = json.loads(config.INDEX_META_JSON.read_text())
    line(OK, "dense index",
         f"{'on' if meta.get('embeddings_available') else 'OFF (BM25 only)'} "
         f"dim={meta.get('dim')} model={meta.get('embed_model')}")

print("\n" + "=" * 62)
if issues:
    print("Not ready yet. Fix these:")
    for i in issues:
        print("  -", i)
    print("\nMeanwhile you can verify the pipeline offline with:  make smoke")
    sys.exit(1)

if not config.CHUNKS_JSON.exists():
    print("Setup looks good. Build the corpus next:   make ingest")
else:
    print("Ready. Start the product:   make run      Evaluate it:   make eval")
sys.exit(0)
