"""Answer generation and the trustworthiness machinery around it.

The whole product hangs on one promise: every factual claim comes from the
supplied audio, and the learner can check it. Three mechanisms enforce that.

1. Citation contract. Sources are presented as numbered blocks labelled
   `[E2 @ 34:12]`, and the model must attach those exact labels to claims.
2. Abstention. A retrieval-side gate (max cosine below threshold) plus a
   semantic gate (the model emits `NOT_COVERED:` when the sources do not
   answer the question). Either one triggers a refusal instead of an answer.
3. Citation validation. After generation, every emitted label is checked
   against the labels actually retrieved this turn. Invalid labels are
   recorded and, when `citation_repair` is on, stripped from the text. A
   hallucinated timestamp never reaches the learner.

Nothing here trusts the model to behave; it is all checked after the fact,
which is also what makes the eval harness able to measure it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import config
from src.app import llm
from src.app.retrieve import Corpus, Hit

CITE_RE = re.compile(r"\[(E\d+)\s*@\s*(\d+(?::\d{2})+)\]")
NOT_COVERED = "NOT_COVERED:"

BASE_RULES = f"""You are the Fermi Podcast Companion. You help a learner
understand a small, fixed collection of podcast episodes about
landmark scientific papers (physics, molecular biology, information
theory, machine learning and mathematical logic).

HARD RULES
1. Every factual claim about the episodes must carry a citation in the exact
   form [E2 @ 34:12], copied verbatim from a SOURCE header below. Never
   invent, adjust or round a timestamp. Never cite a source that is not listed.
2. Use ONLY the SOURCES for what the episodes say. If you add standard science
   background that is not in the sources, prefix that sentence with
   "Background (not from the episodes):".
3. If the SOURCES do not contain enough to answer, reply with exactly
   "{NOT_COVERED}" followed by one or two sentences saying what the collection
   does not cover and, if relevant, what it does cover instead. Do not guess.
4. Speak to a curious learner: plain language, concrete, no hedging padding.
   Prefer 120-220 words. Do not open with "Great question".
5. Attribute to the speakers, not to the field in general: "in this episode they
   argue ...". If speakers disagree or hedge, say so.
"""

INTENT_GUIDE = {
    "passage_qa": "Answer the question directly, then give the one detail or "
                  "example from the sources that makes it concrete.",
    "episode_routing": "Recommend episodes in priority order. For each: the "
                       "episode, one line on why it fits this learner's goal, "
                       "and a citation to the passage that shows it covers the "
                       "topic. If none cover it, follow rule 3.",
    "cross_episode_compare": "Compare explicitly. State each episode's position "
                             "with its own citation, then what they share and "
                             "where they differ. Never blend them into one voice. "
                             "If only one episode discusses it, say that.",
    "clarify_previous": "Re-explain your previous answer more simply, in "
                        "numbered steps, using the SAME sources. Add an analogy "
                        "if it helps. Do not introduce new claims.",
    "locate_audio": "Point to the exact place: episode, timestamp, and a short "
                    "verbatim quote of what is said there. Every citation you "
                    "emit is rendered as a playable audio control seeked to "
                    "that second, so never say you cannot play audio or that "
                    "you are text-only -- just cite the moment. Under 90 words.",
}


@dataclass
class Answer:
    text: str
    intent: str
    standalone_query: str
    sources: list[dict]
    citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    abstained: bool = False
    abstain_reason: str = ""
    confidence: dict = field(default_factory=dict)
    router: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "intent": self.intent,
            "standalone_query": self.standalone_query,
            "citations": self.citations,
            "invalid_citations": self.invalid_citations,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
            "confidence": self.confidence,
            "router": self.router,
            "sources": self.sources,
            "usage": self.usage,
        }


def render_sources(hits: list[Hit], corpus: Corpus) -> str:
    blocks = []
    for n, h in enumerate(hits, start=1):
        c = h.chunk
        ep = corpus.episode_by_id.get(c["episode_id"], {})
        title = ep.get("title") or c["episode_title"]
        blocks.append(
            f"SOURCE {n} — [{h.label}] — {c['episode_id']}: {title} "
            f"({config.fmt_ts(c['start_s'])}-{config.fmt_ts(c['end_s'])})\n"
            f"{c['text']}")
    return "\n\n".join(blocks)


def render_catalogue(corpus: Corpus) -> str:
    lines = []
    for e in corpus.episodes:
        lines.append(f"{e['episode_id']}: {e['title']} "
                     f"({config.fmt_ts(e.get('duration_s', 0))}) — "
                     f"{e.get('summary', '')} Topics: {', '.join(e.get('topics', [])[:10])}")
    return "\n".join(lines) or "(no episode cards built)"


def extract_citations(text: str) -> list[str]:
    seen, out = set(), []
    for ep, ts in CITE_RE.findall(text):
        label = f"{ep} @ {ts}"
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def validate_citations(text: str, hits: list[Hit],
                       repair: bool) -> tuple[str, list[str], list[str]]:
    """Returns (possibly repaired text, valid labels, invalid labels)."""
    allowed = {h.label for h in hits}
    found = extract_citations(text)
    valid = [c for c in found if c in allowed]
    invalid = [c for c in found if c not in allowed]
    if invalid and repair:
        for bad in invalid:
            text = text.replace(f"[{bad}]", "")
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s+([.,;:])", r"\1", text)
        text += ("\n\n_(One or more citations in the draft did not match a "
                 "retrieved passage and were removed. Ask me to locate the "
                 "audio if you want to verify a specific claim.)_")
    return text.strip(), valid, invalid


def generate(query: str, route, hits: list[Hit], history: list[dict],
             corpus: Corpus, settings: config.Settings,
             reused_evidence: bool = False) -> Answer:
    conf = corpus.confidence(hits)

    # --- gate 1: retrieval confidence
    # Skipped when evidence was deliberately carried over from the previous
    # turn ("I didn't follow that"). Those follow-ups contain almost no
    # searchable content, so their retrieval scores are meaningless — gating
    # on them makes the product refuse to clarify its own answer.
    # An episode_routing turn ("where should I start?") is answered from the
    # episode cards, not from 60-second content chunks, and it is a question
    # *about* the collection rather than about anything said inside it -- so
    # it scores near zero against every chunk. Gating it on chunk confidence
    # made the product refuse to recommend a listening order it could in fact
    # produce (observed in baseline->improved as route_beginner_order
    # regressing from a correct answer to a false refusal). The abstention
    # decision for routing turns belongs to the episode-level evidence.
    gate_applies = (not reused_evidence
                    and route.intent != "episode_routing")
    if gate_applies and not corpus.has_coverage(hits, settings):
        thr = (settings.abstain_dense_threshold if corpus.dense_ok
               else settings.abstain_lexical_threshold)
        text = (
            "I don't think this collection covers that. The closest passages I "
            f"found score well below the threshold I need to answer honestly "
            f"(best {conf['mode']} score {conf[conf['mode'] + '_max']:.2f}, "
            f"need {thr:.2f}).\n\nWhat this collection does cover:\n"
            + "\n".join(f"- {e['episode_id']}: {e['title']} — "
                        f"{', '.join(e.get('topics', [])[:5])}"
                        for e in corpus.episodes))
        return Answer(text=text, intent=route.intent,
                      standalone_query=route.standalone_query,
                      sources=[h.to_dict() for h in hits],
                      abstained=True, abstain_reason="retrieval_below_threshold",
                      confidence=conf, router=route.to_dict())

    system = (BASE_RULES + "\nTASK: ANSWER\nTHIS TURN: "
              + INTENT_GUIDE.get(route.intent, INTENT_GUIDE["passage_qa"]))

    parts = [f"EPISODE CATALOGUE\n{render_catalogue(corpus)}"]
    if route.intent == "episode_routing":
        parts.append("Recommend from the catalogue above, justified by the sources below.")
    parts.append(f"SOURCES (the only evidence you may cite)\n\n{render_sources(hits, corpus)}")
    parts.append(f"LEARNER QUESTION: {query.strip()}")
    if route.standalone_query.lower() != query.strip().lower():
        parts.append(f"(interpreted as: {route.standalone_query})")

    messages = [{"role": m["role"], "content": m["content"]} for m in history[-4:]]
    messages.append({"role": "user", "content": "\n\n".join(parts)})

    try:
        result = llm.chat(system, messages, max_tokens=settings.max_tokens,
                          temperature=settings.temperature)
    except Exception as exc:
        return Answer(text=f"[generation failed: {type(exc).__name__}: {exc}]",
                      intent=route.intent, standalone_query=route.standalone_query,
                      sources=[h.to_dict() for h in hits], confidence=conf,
                      router=route.to_dict(), abstained=False,
                      abstain_reason="generation_error")

    raw = result.text.strip()

    # --- gate 2: model-side semantic abstention
    abstained = raw.upper().startswith(NOT_COVERED)
    if abstained:
        raw = raw[len(NOT_COVERED):].strip()

    text, valid, invalid = validate_citations(raw, hits, settings.citation_repair)

    return Answer(text=text, intent=route.intent,
                  standalone_query=route.standalone_query,
                  sources=[h.to_dict() for h in hits],
                  citations=valid, invalid_citations=invalid,
                  abstained=abstained,
                  abstain_reason="model_declared_no_coverage" if abstained else "",
                  confidence=conf, router=route.to_dict(),
                  usage=result.usage)
