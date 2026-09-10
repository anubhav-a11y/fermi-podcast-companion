"""Intent routing + conversational query rewriting.

Both happen in ONE LLM call. They need the same input (the query plus recent
history) and the same reasoning ("what is the learner actually asking?"), so
splitting them would double latency and cost for no accuracy gain.

Intents:
  passage_qa            answer from specific passages
  episode_routing       "which episode should I listen to for X?"
  cross_episode_compare "compare what these episodes say about X"
  clarify_previous      "I didn't follow that" -> reuse last turn's sources
  locate_audio          "take me to the part that supports this"

A rule-based fallback runs whenever the model output fails to parse, so the
product degrades rather than crashes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from src import config
from src.app import llm

INTENTS = ("passage_qa", "episode_routing", "cross_episode_compare",
           "clarify_previous", "locate_audio")

ROUTER_SYSTEM = """You route turns in a podcast-learning assistant.
TASK: ROUTE

Classify the CURRENT TURN into exactly one intent:
- "passage_qa": asks about the content of the episodes (a concept, a claim,
  an example, a definition, what a speaker said).
- "episode_routing": asks which episode(s) to listen to, where to start, or
  whether the collection covers a topic at all.
- "cross_episode_compare": asks to compare, contrast, or synthesise across
  two or more episodes.
- "clarify_previous": asks about YOUR immediately preceding answer — to
  simplify it, re-explain it, break it into steps, or expand one part of it.
- "locate_audio": asks where in the audio something is, or to be taken to /
  played the supporting part.

Also rewrite the turn as a STANDALONE search query: resolve every pronoun and
ellipsis ("it", "that example", "the first one") using the history, keep the
learner's technical vocabulary verbatim, drop conversational padding. If the
turn is already standalone, repeat it.

Reply with JSON only:
{"intent": "<one of the five>", "standalone_query": "<...>", "reason": "<<=12 words>>"}"""


@dataclass
class Route:
    intent: str
    standalone_query: str
    reason: str
    method: str  # "llm" | "rules"

    def to_dict(self) -> dict:
        return asdict(self)


_CLARIFY = re.compile(
    r"\b(didn'?t (get|follow|understand)|did not (get|follow|understand)|"
    r"step by step|explain (that|it) again|simpler|dumb(er)? it down|"
    r"what do you mean|elaborate|unpack that|say (that )?again)\b", re.I)
_ROUTING = re.compile(
    r"\b(which episode|what episode|which one should i|where (do|should) i start|"
    r"should i listen|do (these|the) episodes (cover|discuss|talk about)|"
    r"is (there|it) covered|any episode)\b", re.I)
_COMPARE = re.compile(
    r"\b(compare|contrast|differ|difference between|both episodes|across (the )?episodes|"
    r"versus|vs\.?)\b", re.I)
_LOCATE = re.compile(
    r"\b(take me to|play (the|that)|jump to|timestamp|where in the (audio|episode)|"
    r"what time|point me to)\b", re.I)


def rule_route(query: str, has_history: bool) -> Route:
    q = query.strip()
    if _LOCATE.search(q):
        return Route("locate_audio", q, "matched locate pattern", "rules")
    if _ROUTING.search(q):
        return Route("episode_routing", q, "matched routing pattern", "rules")
    if _COMPARE.search(q):
        return Route("cross_episode_compare", q, "matched compare pattern", "rules")
    if has_history and (_CLARIFY.search(q) or len(q.split()) <= 5):
        return Route("clarify_previous", q, "matched clarify pattern", "rules")
    return Route("passage_qa", q, "default", "rules")


def route(query: str, history: list[dict], settings: config.Settings) -> Route:
    """history: [{"role": "user"|"assistant", "content": str}, ...] oldest first."""
    has_history = any(m["role"] == "assistant" for m in history)

    if not settings.use_llm_router:
        # Baseline preset: no routing at all. Every turn is treated as a
        # standalone passage question -- the naive RAG behaviour we measure
        # against.
        return Route("passage_qa", query.strip(), "baseline: routing disabled", "rules")

    convo = "\n".join(
        f"{'LEARNER' if m['role'] == 'user' else 'ASSISTANT'}: {m['content'][:700]}"
        for m in history[-4:])
    user = (f"HISTORY (may be empty):\n{convo or '(none)'}\n\n"
            f"CURRENT TURN: {query.strip()}")

    try:
        data = llm.json_chat(ROUTER_SYSTEM, [{"role": "user", "content": user}],
                             max_tokens=250, temperature=0.0)
    except Exception as exc:  # network, auth, rate limit
        r = rule_route(query, has_history)
        r.reason = f"llm router failed ({type(exc).__name__}); {r.reason}"
        return r

    intent = str(data.get("intent", "")).strip()
    sq = str(data.get("standalone_query", "")).strip()
    if intent not in INTENTS or not sq:
        r = rule_route(query, has_history)
        r.reason = f"unparseable router output; {r.reason}"
        return r
    if intent == "clarify_previous" and not has_history:
        return Route("passage_qa", sq, "clarify with no history -> qa", "llm")
    if not settings.use_query_rewrite:
        # Routing without rewriting: keep the classified intent but search the
        # learner's literal words, so the ablation isolates one mechanism.
        sq = query.strip()
    return Route(intent, sq, str(data.get("reason", ""))[:120], "llm")
