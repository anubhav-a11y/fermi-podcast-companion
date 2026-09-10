"""One thin wrapper over whichever LLM / embedding provider is configured.

Why a wrapper: the router, the answerer and the eval judges all need a
`chat()` call, and the trial budget is fixed. Centralising the call gives us
(a) provider portability, (b) one place to count tokens, (c) a `stub`
provider so the pipeline and eval harness run offline with zero spend.
"""

from __future__ import annotations

import hashlib
import json
import time
import os
import re
import threading
from dataclasses import dataclass, field

import numpy as np

from src import config

_lock = threading.Lock()
USAGE = {"calls": 0, "in_tokens": 0, "out_tokens": 0, "embed_texts": 0}


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)


def _record(in_tok: int = 0, out_tok: int = 0, embed: int = 0) -> None:
    with _lock:
        if in_tok or out_tok:
            USAGE["calls"] += 1
        USAGE["in_tokens"] += in_tok
        USAGE["out_tokens"] += out_tok
        USAGE["embed_texts"] += embed


def usage_report() -> dict:
    with _lock:
        return dict(USAGE)


# --------------------------------------------------------------------- chat
_clients: dict = {}


def _client(kind: str):
    if kind in _clients:
        return _clients[kind]
    if kind == "anthropic":
        import anthropic

        _clients[kind] = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    elif kind == "openai":
        from openai import OpenAI

        _clients[kind] = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    elif kind == "gemini":
        from google import genai

        key = os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"]
        _clients[kind] = genai.Client(api_key=key)
    elif kind == "openrouter":
        from openai import OpenAI

        _clients[kind] = OpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                                base_url=config.OPENROUTER_BASE_URL)
    elif kind == "groq":
        from groq import Groq

        _clients[kind] = Groq(api_key=os.environ["GROQ_API_KEY"])
    else:
        raise ValueError(f"unknown client {kind}")
    return _clients[kind]


# --------------------------------------------------------------- rate limits
# Free tiers are tight (Gemini flash allows 5 requests/minute), and a single
# 429 part-way through a 300-chunk ingest otherwise throws the whole pass
# away. Providers report a retry delay in the error body when they know one,
# so prefer that over a blind guess and fall back to exponential backoff.
RETRY_MAX_ATTEMPTS = int(os.getenv("FERMI_RETRY_ATTEMPTS", "6"))
RETRY_BASE_DELAY = float(os.getenv("FERMI_RETRY_BASE_DELAY", "2.0"))
_RETRYABLE = ("429", "resource_exhausted", "rate limit", "rate_limit",
              "overloaded", "503", "500", "internal server error", "timeout")


# Proactive pacing. Retrying *after* a 429 works but wastes wall-clock and
# burns attempts; when the provider's requests-per-minute ceiling is known,
# spacing calls to match it is strictly better. Gemini's free tier allows 5
# rpm for flash, so FERMI_MIN_CALL_INTERVAL_S=13 keeps a long ingest inside
# the limit without a single rejected request.
MIN_CALL_INTERVAL_S = float(os.getenv("FERMI_MIN_CALL_INTERVAL_S", "0"))
_last_call_at = 0.0
_throttle_lock = threading.Lock()


def _throttle() -> None:
    global _last_call_at
    if MIN_CALL_INTERVAL_S <= 0:
        return
    with _throttle_lock:
        wait = MIN_CALL_INTERVAL_S - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _retry_delay_from(err: Exception, attempt: int) -> float:
    """Honour a server-advertised delay; otherwise exponential backoff."""
    text = str(err)
    m = re.search(r"retryDelay['\"]?[:\s]+['\"]?(\d+(?:\.\d+)?)s", text)
    if not m:
        # Providers word this differently: Gemini says "Please retry in 15.4s",
        # Groq says "Please try again in 14m5.856s". Match both, minutes too.
        m2 = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", text, re.I)
        if m2:
            mins = float(m2.group(1) or 0)
            return min(mins * 60 + float(m2.group(2)) + 1.0, 65.0)
        m = re.search(r"[Pp]lease retry in (\d+(?:\.\d+)?)s", text)
    if m:
        return min(float(m.group(1)) + 1.0, 65.0)
    return min(RETRY_BASE_DELAY * (2 ** attempt), 60.0)


def _is_retryable(err: Exception) -> bool:
    text = str(err).lower()
    return any(tok in text for tok in _RETRYABLE)


def _with_retry(fn, *, what: str = "request"):
    """Call `fn()`, retrying transient rate-limit and server errors."""
    last: Exception | None = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            _throttle()
            return fn()
        except Exception as err:              # noqa: BLE001 - provider SDKs differ
            last = err
            if not _is_retryable(err) or attempt == RETRY_MAX_ATTEMPTS - 1:
                raise
            delay = _retry_delay_from(err, attempt)
            print(f"    {what}: rate-limited, retrying in {delay:.0f}s "
                  f"(attempt {attempt + 1}/{RETRY_MAX_ATTEMPTS})", flush=True)
            time.sleep(delay)
    raise last  # pragma: no cover


def chat(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 900,
    temperature: float = 0.1,
    provider: str | None = None,
) -> LLMResult:
    """messages: [{"role": "user"|"assistant", "content": str}, ...]"""
    provider = (provider or config.LLM_PROVIDER).lower()

    if provider == "stub":
        return _stub_chat(system, messages)

    if provider == "anthropic":
        c = _client("anthropic")
        resp = _with_retry(lambda: c.messages.create(
            model=config.ANTHROPIC_MODEL,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ), what="anthropic chat")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        _record(resp.usage.input_tokens, resp.usage.output_tokens)
        return LLMResult(text, provider, config.ANTHROPIC_MODEL,
                         {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens})

    if provider == "gemini":
        from google.genai import types

        c = _client("gemini")
        # Gemini calls the assistant role "model", and takes the system
        # prompt as a separate config field rather than a message.
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])])
            for m in messages
        ]
        resp = _with_retry(lambda: c.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        ), what="gemini chat")
        text = resp.text or ""
        u = getattr(resp, "usage_metadata", None)
        in_tok = getattr(u, "prompt_token_count", 0) or 0
        out_tok = getattr(u, "candidates_token_count", 0) or 0
        _record(in_tok, out_tok)
        return LLMResult(text, provider, config.GEMINI_MODEL,
                         {"in": in_tok, "out": out_tok})

    if provider in ("openai", "groq", "openrouter"):
        c = _client(provider)
        model = {"openai": config.OPENAI_MODEL,
                 "groq": config.GROQ_MODEL,
                 "openrouter": config.OPENROUTER_MODEL}[provider]
        resp = _with_retry(lambda: c.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ), what=f"{provider} chat")
        text = resp.choices[0].message.content or ""
        u = resp.usage
        _record(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
        return LLMResult(text, provider, model,
                         {"in": getattr(u, "prompt_tokens", 0),
                          "out": getattr(u, "completion_tokens", 0)})

    raise SystemExit(f"Unsupported FERMI_LLM_PROVIDER={provider!r}")


def json_chat(system: str, messages: list[dict], **kw) -> dict:
    """chat() + tolerant JSON extraction. Returns {} if nothing parses.

    A silent {} is dangerous: callers fall back to empty fields and the run
    completes "successfully" with an unusable artifact. Warn loudly instead —
    the usual cause is the response hitting max_tokens mid-object.
    """
    raw = chat(system, messages, **kw).text
    data = extract_json(raw)
    if not data:
        print(f"    [warn] LLM returned no parseable JSON "
              f"({len(raw)} chars); tail={raw[-90:]!r}", flush=True)
    return data


def extract_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # first balanced {...} block
    start = raw.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = raw.find("{", start + 1)
    return {}


# --------------------------------------------------------------------- stub
def _stub_chat(system: str, messages: list[dict]) -> LLMResult:
    """Deterministic offline responses keyed off a marker in the system prompt.

    Not a model. Its only job is to let `make smoke` exercise every code path
    (router -> retrieve -> answer -> judge) without keys or spend.
    """
    user = messages[-1]["content"] if messages else ""
    _record(len(system) // 4, 40)

    if "TASK: ROUTE" in system:
        # Only look at the current turn; matching against the history text
        # would inherit the previous turn's intent.
        current = user.split("CURRENT TURN:")[-1]
        low = current.lower()
        if any(w in low for w in ("which episode", "should i listen", "where do i start")):
            intent = "episode_routing"
        elif any(w in low for w in ("compare", "both episodes", "across the episodes")):
            intent = "cross_episode_compare"
        elif any(w in low for w in ("step by step", "didn't understand", "did not understand",
                                    "simpler", "again", "explain that")):
            intent = "clarify_previous"
        elif any(w in low for w in ("take me to", "play the", "jump to", "timestamp")):
            intent = "locate_audio"
        else:
            intent = "passage_qa"
        q = current.strip() or user
        return LLMResult(json.dumps({"intent": intent, "standalone_query": q[:300],
                                     "reason": "stub heuristic"}),
                         "stub", "stub-router")

    if "TASK: ANSWER" in system:
        cites = re.findall(r"\[(E\d+ @ [0-9:]+)\]", user)
        if not cites:
            return LLMResult("NOT_COVERED: the supplied episodes do not appear to "
                             "cover this.", "stub", "stub-answer")
        body = "Stub answer grounded in the retrieved passages."
        tail = " ".join(f"[{c}]" for c in cites[:2])
        return LLMResult(f"{body} {tail}", "stub", "stub-answer")

    if "TASK: JUDGE" in system:
        return LLMResult(json.dumps({"grounded": True, "unsupported_claims": [],
                                     "helpfulness": 4,
                                     "reason": "stub judge always passes"}),
                         "stub", "stub-judge")

    if "TASK: CONTEXT" in system:
        n = user.count("<<<CHUNK")
        return LLMResult(json.dumps({"contexts": ["Stub context header." for _ in range(n)]}),
                         "stub", "stub-context")

    if "TASK: OUTLINE" in system:
        return LLMResult(json.dumps({
            "title": "Stub episode",
            "summary": "Stub episode summary for offline smoke testing.",
            "topics": ["stub topic"],
            "outline": [{"start_s": 0, "label": "Stub section"}],
        }), "stub", "stub-outline")

    return LLMResult("stub", "stub", "stub")


# ---------------------------------------------------------------- embeddings
_embed_model = None


def embeddings_available() -> bool:
    return config.EMBED_PROVIDER in ("openai", "gemini", "local")


def embed(texts: list[str], *, batch: int = 96, task: str = "document") -> np.ndarray:
    """L2-normalised embedding matrix, shape (len(texts), dim).

    `task` is "document" (indexing) or "query" (search). Gemini uses
    asymmetric retrieval embeddings, so passing the right task type there is
    a genuine accuracy win. Other providers ignore it.

    Returns a (n, 0) array when EMBED_PROVIDER=none so callers can degrade
    to lexical-only retrieval instead of crashing.
    """
    global _embed_model
    if not texts:
        return np.zeros((0, 0), dtype="float32")

    provider = config.EMBED_PROVIDER
    if provider == "none":
        return np.zeros((len(texts), 0), dtype="float32")

    if provider == "gemini":
        from google.genai import types

        c = _client("gemini")
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        cfg = types.EmbedContentConfig(task_type=task_type,
                                       output_dimensionality=config.GEMINI_EMBED_DIM)
        vecs: list[list[float]] = []
        # Batch limits on the embedding endpoint have moved around; fall back
        # to one-at-a-time rather than failing a 200-chunk ingest.
        step = min(batch, 32)
        for i in range(0, len(texts), step):
            part = [t.replace("\n", " ")[:8000] for t in texts[i : i + step]]
            try:
                resp = _with_retry(
                    lambda: c.models.embed_content(
                        model=config.GEMINI_EMBED_MODEL, contents=part, config=cfg),
                    what="gemini embed")
                vecs.extend(list(e.values) for e in resp.embeddings)
            except Exception:
                for one in part:
                    r = _with_retry(
                        lambda one=one: c.models.embed_content(
                            model=config.GEMINI_EMBED_MODEL, contents=one, config=cfg),
                        what="gemini embed")
                    vecs.extend(list(e.values) for e in r.embeddings)
            _record(embed=len(part))
        arr = np.asarray(vecs, dtype="float32")

    elif provider == "openai":
        c = _client("openai")
        vecs: list[list[float]] = []
        for i in range(0, len(texts), batch):
            part = [t.replace("\n", " ")[:8000] for t in texts[i : i + batch]]
            resp = c.embeddings.create(model=config.OPENAI_EMBED_MODEL, input=part)
            vecs.extend(d.embedding for d in resp.data)
            _record(embed=len(part))
        arr = np.asarray(vecs, dtype="float32")

    elif provider == "local":
        from sentence_transformers import SentenceTransformer

        if _embed_model is None:
            _embed_model = SentenceTransformer(config.LOCAL_EMBED_MODEL)
        arr = np.asarray(_embed_model.encode(texts, batch_size=32,
                                             show_progress_bar=False), dtype="float32")
        _record(embed=len(texts))
    else:
        raise SystemExit(f"Unsupported FERMI_EMBED_PROVIDER={provider!r}")

    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.clip(norms, 1e-9, None)


def stable_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
