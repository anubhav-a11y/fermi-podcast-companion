"""Central configuration.

Two things live here:

1. Environment-driven settings (paths, provider names, model names).
2. The feature-flag `Settings` presets. The eval harness runs the *same*
   product code under `baseline` and `improved` presets, so the
   before/after comparison required by the brief is reproducible with a
   single ingest pass and two eval commands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict, replace
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a hard dep, but stay usable
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _path(env_key: str, default: Path) -> Path:
    return Path(os.getenv(env_key, str(default))).expanduser()


AUDIO_DIR = _path("FERMI_AUDIO_DIR", ROOT / "data" / "audio")
ARTIFACT_DIR = _path("FERMI_ARTIFACT_DIR", ROOT / "artifacts")
TRACE_DIR = _path("FERMI_TRACE_DIR", ROOT / "traces")
RUN_DIR = _path("FERMI_RUN_DIR", ROOT / "runs")

TRANSCRIPTS_JSON = ARTIFACT_DIR / "transcripts.json"
CHUNKS_JSON = ARTIFACT_DIR / "chunks.json"
EPISODES_JSON = ARTIFACT_DIR / "episodes.json"
CHUNK_EMB_NPY = ARTIFACT_DIR / "chunk_embeddings.npy"
EPISODE_EMB_NPY = ARTIFACT_DIR / "episode_embeddings.npy"
INDEX_META_JSON = ARTIFACT_DIR / "index_meta.json"

# ---------------------------------------------------------------- providers
# LLM provider for routing / answering / judging.
#   anthropic | openai | gemini | groq | stub
# `stub` is a deterministic offline fake so the whole pipeline (and the eval
# harness) can be smoke-tested with no API keys and no spend.
LLM_PROVIDER = os.getenv("FERMI_LLM_PROVIDER", "anthropic").lower()

# Embedding provider: openai | gemini | local | none
#   local -> sentence-transformers (all-MiniLM-L6-v2), no API cost
#   none  -> skip dense retrieval entirely; system falls back to BM25 only
EMBED_PROVIDER = os.getenv("FERMI_EMBED_PROVIDER", "openai").lower()

# Transcription provider: local (faster-whisper) | groq
ASR_PROVIDER = os.getenv("FERMI_ASR_PROVIDER", "local").lower()

# Model names are env-overridable because provider catalogues change.
ANTHROPIC_MODEL = os.getenv("FERMI_ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_MODEL = os.getenv("FERMI_OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("FERMI_GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("FERMI_GROQ_MODEL", "llama-3.3-70b-versatile")

# OpenRouter: one key, many upstream models, OpenAI-compatible wire format.
# Used here as the primary provider because the free tiers of Groq (200k
# tokens/day) and Gemini (20 requests/day) cannot cover a full ingest plus a
# two-preset evaluation with LLM judges.
OPENROUTER_BASE_URL = os.getenv("FERMI_OPENROUTER_BASE_URL",
                                "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("FERMI_OPENROUTER_MODEL",
                             "anthropic/claude-3.5-haiku")
OPENAI_EMBED_MODEL = os.getenv("FERMI_OPENAI_EMBED_MODEL", "text-embedding-3-small")
GEMINI_EMBED_MODEL = os.getenv("FERMI_GEMINI_EMBED_MODEL", "gemini-embedding-001")
# gemini-embedding-001 defaults to 3072 dims. 768 is ample for 200 chunks and
# a quarter of the storage; we re-normalise after truncation, which Google's
# docs require when you reduce dimensionality.
GEMINI_EMBED_DIM = int(os.getenv("FERMI_GEMINI_EMBED_DIM", "768"))
LOCAL_EMBED_MODEL = os.getenv("FERMI_LOCAL_EMBED_MODEL", "all-MiniLM-L6-v2")
WHISPER_LOCAL_MODEL = os.getenv("FERMI_WHISPER_MODEL", "medium.en")
WHISPER_GROQ_MODEL = os.getenv("FERMI_WHISPER_GROQ_MODEL", "whisper-large-v3-turbo")

# Domain vocabulary fed to Whisper as an initial prompt. Whisper is biased by
# this text, which measurably reduces jargon errors on physics audio.
# Whisper's initial_prompt is a *decoding bias*, not a glossary lookup, and it
# behaves best when it reads like a sample of the audio itself. Measured on
# this corpus: a dense comma-list of terms doubled the rate of spurious "Sch-"
# tokens and induced a 12-segment repetition loop, while a bare "Names: A, B,
# C" list got echoed back into the transcript verbatim during quiet passages.
# A single natural sentence carrying the same proper nouns avoided both.
JARGON_PROMPT = (
    "Today we trace the great papers, from Einstein, Lorentz and Minkowski "
    "on relativity, to Hawking and Bekenstein on black hole entropy and the "
    "Schwarzschild radius, to Watson, Crick, Rosalind Franklin and Chargaff "
    "on the double helix, to Claude Shannon on information, and to Alan "
    "Turing, David Hilbert and Kurt Goedel on the Entscheidungsproblem."
)

# Groq's transcription endpoint rejects prompts over this length outright.
GROQ_PROMPT_MAX_CHARS = 896

# ------------------------------------------------------------------ chunking
CHUNK_TARGET_S = float(os.getenv("FERMI_CHUNK_TARGET_S", "60"))
CHUNK_MIN_S = float(os.getenv("FERMI_CHUNK_MIN_S", "30"))
CHUNK_MAX_S = float(os.getenv("FERMI_CHUNK_MAX_S", "95"))
CHUNK_OVERLAP_SEGMENTS = int(os.getenv("FERMI_CHUNK_OVERLAP", "1"))


@dataclass(frozen=True)
class Settings:
    """Query-time feature flags.

    Everything that differs between the baseline and the improved system is
    a flag here, so both variants share one ingest pass and one code path.
    """

    name: str = "improved"

    # --- retrieval
    use_bm25_hybrid: bool = True       # dense + BM25 fused with RRF
    # Intent routing and query rewriting are separate mechanisms that happen
    # to share one LLM call. They were originally behind a single flag, which
    # made the ablation uninterpretable -- turning "rewriting" on also turned
    # routing on, so neither could be credited for a gain. Split them.
    use_llm_router: bool = True        # classify the turn into one of 5 intents
    use_query_rewrite: bool = True     # resolve pronouns against history
    use_episode_index: bool = True     # route "which episode" to summaries
    use_per_episode_comparison: bool = True  # retrieve per episode, then fuse
    top_k: int = 6
    per_episode_k: int = 3
    rrf_k: int = 60

    # --- trustworthiness
    use_abstention: bool = True
    abstain_dense_threshold: float = 0.30   # max cosine below this -> no coverage
    abstain_lexical_threshold: float = 0.18  # used when embeddings unavailable
    citation_repair: bool = True        # strip citations not in retrieved set

    # --- generation
    temperature: float = 0.1
    # Reasoning models (Groq's gpt-oss) spend part of this budget on
    # hidden reasoning before emitting content, so leave headroom.
    max_tokens: int = 1600

    def to_dict(self) -> dict:
        return asdict(self)


BASELINE = Settings(
    name="baseline",
    use_bm25_hybrid=False,
    use_llm_router=False,
    use_query_rewrite=False,
    use_episode_index=False,
    use_per_episode_comparison=False,
    use_abstention=False,
    citation_repair=False,
)

IMPROVED = Settings(name="improved")

# Ablations. BASELINE differs from IMPROVED on six flags at once, so a
# baseline->improved delta alone cannot say which change earned the gain.
# Each preset below flips exactly one flag on top of BASELINE, which turns
# the comparison into an attribution: run the same suite across them and the
# per-metric jump is attributable to a single named mechanism.
ABL_HYBRID = replace(BASELINE, name="abl_hybrid", use_bm25_hybrid=True)
ABL_ROUTER = replace(BASELINE, name="abl_router", use_llm_router=True)
ABL_REWRITE = replace(BASELINE, name="abl_rewrite",
                      use_llm_router=True, use_query_rewrite=True)
ABL_EPISODE_INDEX = replace(BASELINE, name="abl_episode_index",
                            use_episode_index=True)
ABL_PER_EPISODE = replace(BASELINE, name="abl_per_episode",
                          use_per_episode_comparison=True)
ABL_ABSTENTION = replace(BASELINE, name="abl_abstention",
                         use_abstention=True, citation_repair=True)

PRESETS = {
    "baseline": BASELINE,
    "improved": IMPROVED,
    "abl_hybrid": ABL_HYBRID,
    "abl_router": ABL_ROUTER,
    "abl_rewrite": ABL_REWRITE,
    "abl_episode_index": ABL_EPISODE_INDEX,
    "abl_per_episode": ABL_PER_EPISODE,
    "abl_abstention": ABL_ABSTENTION,
}


def get_preset(name: str) -> Settings:
    if name not in PRESETS:
        raise SystemExit(f"Unknown preset {name!r}. Choose from {sorted(PRESETS)}.")
    return PRESETS[name]


def fmt_ts(seconds: float) -> str:
    """Seconds -> mm:ss (or h:mm:ss past an hour)."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
