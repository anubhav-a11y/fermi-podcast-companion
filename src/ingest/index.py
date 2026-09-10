"""Step 4 of ingest: build the dense index.

No vector database. Three hours of audio is ~200 chunks; a (200, 1536)
float32 matrix is 1.2 MB and an exact cosine search over it is a single
numpy matmul, well under a millisecond. Adding a vector store here would be
infrastructure without a benefit — a trade-off worth stating explicitly
rather than reaching for the default stack.

BM25 is built at load time from chunks.json (also trivial at this scale), so
nothing lexical needs persisting.

Output: artifacts/chunk_embeddings.npy, episode_embeddings.npy, index_meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from src import config
from src.app import llm


def chunk_embed_text(c: dict) -> str:
    """Context header + passage. Header first so it also grounds the passage."""
    ctx = (c.get("context") or "").strip()
    head = f"[{c['episode_title']}]"
    return f"{head} {ctx}\n{c['text']}".strip() if ctx else f"{head}\n{c['text']}"


def embed_model_name() -> str | None:
    return {
        "openai": config.OPENAI_EMBED_MODEL,
        "gemini": config.GEMINI_EMBED_MODEL,
        "local": config.LOCAL_EMBED_MODEL,
    }.get(config.EMBED_PROVIDER)


def episode_embed_text(e: dict) -> str:
    return (f"{e['title']}\n{e.get('summary','')}\n"
            f"Topics: {', '.join(e.get('topics', []))}")


def run(chunks_json: Path, episodes_json: Path) -> None:
    if not chunks_json.exists():
        raise SystemExit(f"{chunks_json} missing. Run: make chunk")
    chunks = json.loads(chunks_json.read_text())["chunks"]
    episodes = (json.loads(episodes_json.read_text())["episodes"]
                if episodes_json.exists() else [])

    available = llm.embeddings_available()
    if not available:
        print("FERMI_EMBED_PROVIDER=none -> skipping dense index; "
              "retrieval will be BM25-only.")
        chunk_vecs = np.zeros((len(chunks), 0), dtype="float32")
        ep_vecs = np.zeros((len(episodes), 0), dtype="float32")
    else:
        print(f"Embedding {len(chunks)} chunks with "
              f"{config.EMBED_PROVIDER}/{embed_model_name()} ...")
        chunk_vecs = llm.embed([chunk_embed_text(c) for c in chunks], task="document")
        ep_vecs = (llm.embed([episode_embed_text(e) for e in episodes], task="document")
                   if episodes else np.zeros((0, chunk_vecs.shape[1]), dtype="float32"))

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(config.CHUNK_EMB_NPY, chunk_vecs)
    np.save(config.EPISODE_EMB_NPY, ep_vecs)
    meta = {
        "embeddings_available": bool(available),
        "embed_provider": config.EMBED_PROVIDER,
        "embed_model": embed_model_name(),
        "dim": int(chunk_vecs.shape[1]),
        "n_chunks": len(chunks),
        "n_episodes": len(episodes),
        "chunk_ids": [c["chunk_id"] for c in chunks],
        "episode_ids": [e["episode_id"] for e in episodes],
    }
    config.INDEX_META_JSON.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {config.CHUNK_EMB_NPY} {chunk_vecs.shape} and "
          f"{config.EPISODE_EMB_NPY} {ep_vecs.shape}")
    print("LLM/embedding usage:", llm.usage_report())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the dense retrieval index.")
    ap.add_argument("--chunks", type=Path, default=config.CHUNKS_JSON)
    ap.add_argument("--episodes", type=Path, default=config.EPISODES_JSON)
    a = ap.parse_args(argv)
    run(a.chunks, a.episodes)


if __name__ == "__main__":
    sys.exit(main())
