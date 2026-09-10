"""Step 1 of ingest: raw audio -> timestamped transcript segments.

Two providers:

* `local`  faster-whisper. No API cost, runs on CPU (int8) or GPU (float16).
* `groq`   whisper-large-v3-turbo. Much faster; files are transparently
           downsampled with ffmpeg when they exceed the upload limit.

Output: artifacts/transcripts.json
    [{episode_id, title, audio_path, duration_s, segments: [{start,end,text}]}]

Per the brief we start from the supplied raw audio only. No platform
captions or transcript APIs are used anywhere in this repo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from src import config
from src.ingest import glossary

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".mp4", ".webm", ".aac"}
GROQ_MAX_BYTES = 24 * 1024 * 1024


def find_audio(audio_dir: Path) -> list[Path]:
    files = sorted(p for p in audio_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO_EXT)
    if not files:
        raise SystemExit(
            f"No audio found in {audio_dir}.\n"
            "Download the 3 supplied Fermi Podcast files into that folder first."
        )
    return files


def nice_title(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ")
    stem = " ".join(stem.split())
    return stem[:1].upper() + stem[1:]


def _ffprobe_duration(path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _shrink_for_upload(path: Path) -> Path:
    """16 kHz mono 32 kbps mp3 — plenty for ASR, ~8x smaller."""
    if not shutil.which("ffmpeg"):
        raise SystemExit(
            f"{path.name} is larger than the API upload limit and ffmpeg is not "
            "installed. Install ffmpeg, or use FERMI_ASR_PROVIDER=local."
        )
    tmp = Path(tempfile.mkdtemp()) / (path.stem + ".mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", "16000",
         "-b:a", "32k", str(tmp)],
        check=True, capture_output=True)
    return tmp


# ------------------------------------------------------------------ providers
def transcribe_local(path: Path) -> list[dict]:
    from faster_whisper import WhisperModel

    device = os.getenv("FERMI_WHISPER_DEVICE", "cpu")
    compute = os.getenv("FERMI_WHISPER_COMPUTE", "int8" if device == "cpu" else "float16")
    model = _local_model(config.WHISPER_LOCAL_MODEL, device, compute)

    segments, _info = model.transcribe(
        str(path),
        language="en",
        vad_filter=True,                      # drops long silences/music beds
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=config.JARGON_PROMPT,  # biases decoding toward jargon
        condition_on_previous_text=False,     # avoids repetition loops
        beam_size=5,
    )
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        if len(out) % 50 == 0 and out:
            print(f"    ... {len(out)} segments, up to {config.fmt_ts(out[-1]['end'])}",
                  flush=True)
    return out


_LOCAL_MODEL_CACHE: dict = {}


def _local_model(name: str, device: str, compute: str):
    key = (name, device, compute)
    if key not in _LOCAL_MODEL_CACHE:
        from faster_whisper import WhisperModel

        print(f"    loading faster-whisper {name} ({device}/{compute})", flush=True)
        _LOCAL_MODEL_CACHE[key] = WhisperModel(name, device=device, compute_type=compute)
    return _LOCAL_MODEL_CACHE[key]


def transcribe_groq(path: Path) -> list[dict]:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    # Groq rejects an over-long prompt with a 400 rather than truncating it,
    # which would fail the whole run. Trim on a comma so we never cut a term
    # in half and bias decoding toward a fragment.
    prompt = config.JARGON_PROMPT
    if len(prompt) > config.GROQ_PROMPT_MAX_CHARS:
        prompt = prompt[: config.GROQ_PROMPT_MAX_CHARS]
        prompt = prompt[: prompt.rfind(",")] + "."
        print(f"    jargon prompt trimmed to {len(prompt)} chars for Groq", flush=True)

    upload = path
    if path.stat().st_size > GROQ_MAX_BYTES:
        print("    file over upload limit -> downsampling with ffmpeg", flush=True)
        upload = _shrink_for_upload(path)

    with open(upload, "rb") as fh:
        resp = client.audio.transcriptions.create(
            file=(upload.name, fh.read()),
            model=config.WHISPER_GROQ_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            language="en",
            prompt=prompt,
        )
    data = resp if isinstance(resp, dict) else resp.model_dump()
    out = []
    for s in data.get("segments", []):
        text = (s.get("text") or "").strip()
        if text:
            out.append({"start": round(float(s["start"]), 2),
                        "end": round(float(s["end"]), 2), "text": text})
    return out


# ---------------------------------------------------------------------- main
def run(audio_dir: Path, out_json: Path, provider: str, force: bool) -> dict:
    files = find_audio(audio_dir)
    existing: dict[str, dict] = {}
    if out_json.exists() and not force:
        for ep in json.loads(out_json.read_text())["episodes"]:
            existing[ep["title"]] = ep

    episodes = []
    for i, path in enumerate(files, start=1):
        title = nice_title(path)
        if title in existing:
            print(f"[{i}/{len(files)}] {title}: cached, skipping "
                  f"({len(existing[title]['segments'])} segments)")
            ep = existing[title]
            ep["episode_id"] = f"E{i}"
            episodes.append(ep)
            continue

        print(f"[{i}/{len(files)}] transcribing {path.name} via {provider} ...", flush=True)
        t0 = time.time()
        segments = transcribe_local(path) if provider == "local" else transcribe_groq(path)
        if not segments:
            raise SystemExit(f"No speech recognised in {path.name}.")

        # The jargon prompt only biases decoding, so a few proper nouns still
        # come back misspelled. Repair them deterministically before anything
        # downstream indexes the text -- see glossary.py for why this matters
        # to retrieval rather than just to readability.
        fixed = glossary.correct_segments(segments)
        if fixed:
            print(f"    glossary: {fixed} proper-noun correction(s)", flush=True)
        dur = _ffprobe_duration(path) or segments[-1]["end"]
        episodes.append({
            "episode_id": f"E{i}",
            "title": title,
            "audio_path": str(path.resolve()),
            "duration_s": round(dur, 2),
            "asr_provider": provider,
            "asr_model": (config.WHISPER_LOCAL_MODEL if provider == "local"
                          else config.WHISPER_GROQ_MODEL),
            "segments": segments,
        })
        words = sum(len(s["text"].split()) for s in segments)
        print(f"    done in {time.time()-t0:.0f}s — {len(segments)} segments, "
              f"{words} words, {config.fmt_ts(dur)} audio")

    payload = {"episodes": episodes}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2))
    total = sum(e["duration_s"] for e in episodes)
    print(f"\nWrote {out_json} — {len(episodes)} episodes, {config.fmt_ts(total)} total audio")
    print("Skim the transcript before moving on:  make peek")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Transcribe supplied podcast audio.")
    ap.add_argument("--audio-dir", type=Path, default=config.AUDIO_DIR)
    ap.add_argument("--out", type=Path, default=config.TRANSCRIPTS_JSON)
    ap.add_argument("--provider", default=config.ASR_PROVIDER, choices=["local", "groq"])
    ap.add_argument("--force", action="store_true", help="re-transcribe cached episodes")
    a = ap.parse_args(argv)
    run(a.audio_dir, a.out, a.provider, a.force)


if __name__ == "__main__":
    sys.exit(main())
