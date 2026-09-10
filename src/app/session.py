"""The product itself: one class, one method, one turn.

`Companion.ask()` is the single entry point used by the CLI, the Streamlit
UI and the eval harness. Nothing in the eval path bypasses it — otherwise
the evaluation would be measuring a different system from the one shipped.

It also writes a JSONL trace per session containing the learner input, the
router decision, the retrieved passages with timestamps, and the final
response. That is the "saved traces" deliverable, and it's the artifact that
makes grounding auditable after the fact.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from src import config
from src.app import answer as answer_mod
from src.app import llm, router
from src.app.retrieve import Hit, load_corpus


class Companion:
    def __init__(self, settings: config.Settings | None = None,
                 trace_path: Path | None = None, session_id: str | None = None):
        self.settings = settings or config.IMPROVED
        self.corpus = load_corpus()
        self.history: list[dict] = []
        self.last_hits: list[Hit] = []
        # Labels the previous answer actually cited. "Take me to that part"
        # means the passages that supported the last answer, which are not
        # necessarily its top-ranked hits.
        self.last_citations: list[str] = []
        self.session_id = session_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        if trace_path is None:
            config.TRACE_DIR.mkdir(parents=True, exist_ok=True)
            trace_path = config.TRACE_DIR / f"session-{self.session_id}.jsonl"
        self.trace_path = trace_path
        self.turn = 0

    # ------------------------------------------------------------------ retrieval
    def _retrieve(self, route_result) -> tuple[list[Hit], bool]:
        """Returns (hits, reused_evidence)."""
        s, q = self.settings, route_result.standalone_query
        intent = route_result.intent

        if intent == "clarify_previous" and self.last_hits:
            # Reuse the previous turn's evidence. A follow-up like "I didn't
            # follow that" has almost no retrievable content of its own, and
            # searching on it returns noise.
            return self.last_hits, True

        if intent == "locate_audio":
            if self.last_hits:
                # Put the passages the previous answer *cited* first, then
                # fill with its other evidence. Truncating by rank instead
                # dropped the cited passages whenever the last answer quoted
                # something outside the top few hits -- citation repair then
                # stripped those citations as "not retrieved" and the answer
                # collapsed into an apology. Observed in a real session after
                # a cross-episode comparison returned 21 passages.
                cited = [h for h in self.last_hits
                         if h.label in self.last_citations]
                rest = [h for h in self.last_hits
                        if h.label not in self.last_citations]
                ordered = cited + rest
                return ordered[: max(3, len(cited))], True
            return self.corpus.search_chunks(q, s, k=3), False

        if intent == "cross_episode_compare" and s.use_per_episode_comparison:
            return self.corpus.search_per_episode(q, s), False

        if intent == "episode_routing" and s.use_episode_index:
            ranked = self.corpus.search_episodes(q, s)
            hits: list[Hit] = []
            for r in ranked:
                hits.extend(r["evidence"])
            return hits[: s.top_k + 2], False

        return self.corpus.search_chunks(q, s), False

    # ----------------------------------------------------------------------- turn
    def ask(self, query: str) -> answer_mod.Answer:
        self.turn += 1
        t0 = time.time()

        route_result = router.route(query, self.history, self.settings)
        hits, reused = self._retrieve(route_result)
        ans = answer_mod.generate(query, route_result, hits, self.history,
                                  self.corpus, self.settings,
                                  reused_evidence=reused)
        ans.router["reused_evidence"] = reused

        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": ans.text})
        self.history = self.history[-8:]
        if hits and route_result.intent != "locate_audio":
            self.last_hits = hits
            self.last_citations = list(ans.citations)

        self._trace(query, ans, time.time() - t0)
        return ans

    def reset(self) -> None:
        self.history, self.last_hits, self.last_citations = [], [], []

    def _trace(self, query: str, ans: answer_mod.Answer, elapsed: float) -> None:
        record = {
            "session_id": self.session_id,
            "turn": self.turn,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "preset": self.settings.name,
            "settings": self.settings.to_dict(),
            "learner_input": query,
            "router": ans.router,
            "retrieved": ans.sources,
            "confidence": ans.confidence,
            "response": ans.text,
            "citations": ans.citations,
            "invalid_citations": ans.invalid_citations,
            "abstained": ans.abstained,
            "abstain_reason": ans.abstain_reason,
            "elapsed_s": round(elapsed, 2),
            "usage": ans.usage,
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trace_path, "a") as fh:
            fh.write(json.dumps(record) + "\n")

    # ---------------------------------------------------------------- utilities
    def audio_target(self, label: str) -> dict | None:
        """Map a citation label like 'E2 @ 34:12' back to a playable audio spot."""
        for src in (s for s in (self.last_hits or []) ):
            if src.label == label:
                ep = self.corpus.episode_by_id.get(src.chunk["episode_id"], {})
                return {"audio_path": ep.get("audio_path"),
                        "start_s": src.chunk["start_s"],
                        "end_s": src.chunk["end_s"],
                        "episode_title": ep.get("title", src.chunk["episode_title"])}
        return None

    def banner(self) -> str:
        st = self.corpus.stats()
        return (f"{st['episodes']} episodes · {st['chunks']} chunks · "
                f"{config.fmt_ts(st['audio_s'])} audio · "
                f"dense={'on' if st['dense'] else 'off'} · "
                f"llm={config.LLM_PROVIDER} · preset={self.settings.name}")
