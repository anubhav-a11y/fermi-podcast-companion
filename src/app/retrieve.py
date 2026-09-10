"""Retrieval over the ingested corpus.

Three retrieval modes, because the learner asks three different shapes of
question and one index cannot serve all of them:

* `search_chunks`      passage-level, dense + BM25 fused with RRF.
* `search_episodes`    over episode cards, for "which episode should I ...".
* `search_per_episode` k hits from *each* episode, for comparison questions
                       (a global top-k on a comparison query tends to return
                       6 passages from whichever episode is most verbose,
                       which makes a fair comparison impossible).

Every hit carries its own dense and lexical scores so the abstention gate
and the eval harness can inspect retrieval confidence directly.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from src import config
from src.app import llm

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "as", "is", "are", "was", "were", "be", "been", "it", "its", "this",
    "that", "these", "those", "at", "by", "from", "about", "into", "so", "than",
    "then", "there", "what", "which", "who", "how", "why", "when", "do", "does",
    "did", "can", "could", "would", "should", "i", "you", "we", "they", "he",
    "she", "me", "my", "our", "your", "not", "no", "yes", "s", "t",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class Hit:
    chunk: dict
    dense: float = 0.0
    lexical: float = 0.0
    rrf: float = 0.0
    ranks: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return self.chunk["chunk_id"]

    @property
    def label(self) -> str:
        """The citation token the learner sees, e.g. `E2 @ 34:12`."""
        return f"{self.chunk['episode_id']} @ {config.fmt_ts(self.chunk['start_s'])}"

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "episode_id": self.chunk["episode_id"],
            "episode_title": self.chunk["episode_title"],
            "start_s": self.chunk["start_s"],
            "end_s": self.chunk["end_s"],
            "label": self.label,
            "dense": round(self.dense, 4),
            "lexical": round(self.lexical, 4),
            "rrf": round(self.rrf, 5),
            "text": self.chunk["text"],
        }


class Corpus:
    """Loads artifacts once and serves the three retrieval modes."""

    def __init__(self):
        if not config.CHUNKS_JSON.exists():
            raise SystemExit(
                f"{config.CHUNKS_JSON} not found.\n"
                "Build the artifacts first:  make ingest   (or: make smoke for the offline fixture)"
            )
        self.chunks: list[dict] = json.loads(config.CHUNKS_JSON.read_text())["chunks"]
        self.by_id = {c["chunk_id"]: c for c in self.chunks}
        self.episodes: list[dict] = (
            json.loads(config.EPISODES_JSON.read_text())["episodes"]
            if config.EPISODES_JSON.exists() else [])
        self.episode_by_id = {e["episode_id"]: e for e in self.episodes}

        self.meta = (json.loads(config.INDEX_META_JSON.read_text())
                     if config.INDEX_META_JSON.exists() else {})
        self.dense_ok = bool(self.meta.get("embeddings_available")) and \
            config.CHUNK_EMB_NPY.exists()
        if self.dense_ok:
            self.chunk_vecs = np.load(config.CHUNK_EMB_NPY)
            self.ep_vecs = (np.load(config.EPISODE_EMB_NPY)
                            if config.EPISODE_EMB_NPY.exists() else None)
            if self.chunk_vecs.shape[0] != len(self.chunks):
                raise SystemExit("Index is stale (embedding rows != chunks). "
                                 "Re-run: make index")
        else:
            self.chunk_vecs = None
            self.ep_vecs = None

        self._bm25 = _BM25([tokenize(f"{c.get('context','')} {c['text']}")
                            for c in self.chunks])
        self._ep_bm25 = _BM25([tokenize(f"{e.get('title','')} {e.get('summary','')} "
                                        f"{' '.join(e.get('topics', []))}")
                               for e in self.episodes]) if self.episodes else None

    # ------------------------------------------------------------- internals
    def _dense_scores(self, query: str, matrix) -> np.ndarray:
        if not self.dense_ok or matrix is None or matrix.size == 0:
            return np.zeros(matrix.shape[0] if matrix is not None else 0, dtype="float32")
        q = llm.embed([query], task="query")
        if q.shape[1] != matrix.shape[1]:
            return np.zeros(matrix.shape[0], dtype="float32")
        # NumPy 2.x on macOS/Accelerate raises spurious divide-by-zero,
        # overflow and invalid-value warnings from the BLAS matmul even
        # though both operands are finite unit vectors and the result is
        # exact. Verified: no NaN or inf in the output. Silence them here
        # only, so a genuine numerical problem elsewhere still surfaces.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            return matrix @ q[0]

    # ------------------------------------------------------------- chunk search
    def search_chunks(self, query: str, settings: config.Settings, *,
                      k: int | None = None,
                      episode_ids: list[str] | None = None) -> list[Hit]:
        k = k or settings.top_k
        idxs = [i for i, c in enumerate(self.chunks)
                if not episode_ids or c["episode_id"] in episode_ids]
        if not idxs:
            return []

        dense_all = self._dense_scores(query, self.chunk_vecs)
        lex_all = self._bm25.scores(tokenize(query))
        lex_max = float(lex_all.max()) if lex_all.size and lex_all.max() > 0 else 1.0

        dense_rank = _rank_map(idxs, dense_all) if self.dense_ok else {}
        lex_rank = _rank_map(idxs, lex_all)

        pool: dict[int, Hit] = {}

        def touch(i: int) -> Hit:
            if i not in pool:
                pool[i] = Hit(chunk=self.chunks[i],
                              dense=float(dense_all[i]) if self.dense_ok else 0.0,
                              lexical=float(lex_all[i]) / lex_max)
            return pool[i]

        if self.dense_ok:
            for i, r in dense_rank.items():
                if r < 25:
                    h = touch(i)
                    h.rrf += 1.0 / (settings.rrf_k + r + 1)
                    h.ranks["dense"] = r
        if settings.use_bm25_hybrid or not self.dense_ok:
            for i, r in lex_rank.items():
                if r < 25:
                    h = touch(i)
                    h.rrf += 1.0 / (settings.rrf_k + r + 1)
                    h.ranks["lexical"] = r

        hits = sorted(pool.values(), key=lambda h: (-h.rrf, -h.dense))
        return hits[:k]

    def search_per_episode(self, query: str, settings: config.Settings) -> list[Hit]:
        out: list[Hit] = []
        for ep in (self.episodes or [{"episode_id": e} for e in
                                     sorted({c["episode_id"] for c in self.chunks})]):
            out.extend(self.search_chunks(query, settings,
                                          k=settings.per_episode_k,
                                          episode_ids=[ep["episode_id"]]))
        return sorted(out, key=lambda h: (-h.rrf, -h.dense))

    # ----------------------------------------------------------- episode search
    def search_episodes(self, query: str, settings: config.Settings) -> list[dict]:
        """Ranked episode cards, each with its best supporting passage."""
        if not self.episodes:
            return []
        dense = self._dense_scores(query, self.ep_vecs) if self.ep_vecs is not None \
            else np.zeros(len(self.episodes), dtype="float32")
        lex = (self._ep_bm25.scores(tokenize(query)) if self._ep_bm25 is not None
               else np.zeros(len(self.episodes), dtype="float32"))
        lex_max = float(lex.max()) if lex.size and lex.max() > 0 else 1.0

        ranked = []
        for i, ep in enumerate(self.episodes):
            best = self.search_chunks(query, settings, k=2,
                                      episode_ids=[ep["episode_id"]])
            combined = 0.65 * float(dense[i]) + 0.35 * (float(lex[i]) / lex_max)
            ranked.append({
                "episode": ep,
                "score": combined,
                "dense": float(dense[i]),
                "lexical": float(lex[i]) / lex_max,
                "evidence": best,
            })
        return sorted(ranked, key=lambda r: -r["score"])

    # ------------------------------------------------------------- confidence
    def confidence(self, hits: list[Hit]) -> dict:
        if not hits:
            return {"dense_max": 0.0, "lexical_max": 0.0, "mode": "none"}
        return {
            "dense_max": round(max(h.dense for h in hits), 4),
            "lexical_max": round(max(h.lexical for h in hits), 4),
            "mode": "dense" if self.dense_ok else "lexical",
        }

    def has_coverage(self, hits: list[Hit], settings: config.Settings) -> bool:
        """Retrieval-side abstention gate (the LLM has a second, semantic one)."""
        if not settings.use_abstention:
            return True
        if not hits:
            return False
        c = self.confidence(hits)
        if self.dense_ok:
            return c["dense_max"] >= settings.abstain_dense_threshold
        return c["lexical_max"] >= settings.abstain_lexical_threshold

    def stats(self) -> dict:
        return {
            "episodes": len(self.episodes) or len({c["episode_id"] for c in self.chunks}),
            "chunks": len(self.chunks),
            "dense": self.dense_ok,
            "embed_model": self.meta.get("embed_model"),
            "audio_s": sum(e.get("duration_s", 0) for e in self.episodes),
        }


def _rank_map(idxs: list[int], scores: np.ndarray) -> dict[int, int]:
    order = sorted(idxs, key=lambda i: -float(scores[i]))
    return {i: r for r, i in enumerate(order)}


class _BM25:
    """Okapi BM25. ~40 lines, avoids a dependency and is easy to reason about."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.corpus = corpus
        self.N = len(corpus) or 1
        self.lens = np.array([len(d) or 1 for d in corpus], dtype="float32")
        self.avgdl = float(self.lens.mean()) if len(corpus) else 1.0
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for doc in corpus:
            counts: dict[str, int] = {}
            for t in doc:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.corpus), dtype="float32")
        for t in query:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, counts in enumerate(self.tf):
                f = counts.get(t)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avgdl)
                out[i] += idf * (f * (self.k1 + 1)) / denom
        return out


@lru_cache(maxsize=1)
def load_corpus() -> Corpus:
    return Corpus()
