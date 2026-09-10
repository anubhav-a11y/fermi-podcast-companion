"""Step 3 of ingest: add the two derived layers that retrieval needs.

1. Episode cards (title, 3-sentence summary, topic list, rough outline).
   These power "which episode should I listen to?" — a question that chunk
   retrieval answers badly, because no single 60-second passage says what an
   episode is *about*.

2. Per-chunk contextual headers. A one-line "what this passage is about,
   in the context of this episode" prefix, embedded together with the chunk
   text. Standalone spoken chunks are full of unresolved pronouns ("and
   that's why it breaks down") which embed poorly; the header restores the
   missing subject. This is the contextual-retrieval trick, batched 8 chunks
   per call to keep the token bill down.

Output: artifacts/episodes.json, and `context` filled in artifacts/chunks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import config
from src.app import llm

OUTLINE_SYSTEM = """You are indexing an episode of a podcast about landmark scientific
papers for a search system. The collection spans physics, molecular
biology, information theory, machine learning and mathematical logic.
TASK: OUTLINE
You are given a compressed transcript with timestamps. Reply with JSON only:
{
  "title": "<a descriptive title for this episode, <=12 words>",
  "summary": "<3 sentences: what this episode covers and who it suits>",
  "topics": ["<6-12 specific topics/concepts actually discussed>"],
  "outline": [{"start_s": <number>, "label": "<short section label>"}]
}
Rules: use only what is in the transcript. Topics must be concepts the
speakers actually discuss, not general science you assume. 6-10 outline
sections. No prose outside the JSON."""

CONTEXT_SYSTEM = """You are preparing podcast passages for a search index.
TASK: CONTEXT
You get an episode summary, then several numbered passages from that episode.
For EACH passage write ONE short sentence (max 25 words) stating what the
passage is about, resolving any pronouns using the episode context.
Do not summarise the whole episode. Do not add facts that are not present.
Reply with JSON only: {"contexts": ["...", "..."]}  — one entry per passage,
in order."""


def compress_transcript(ep: dict, max_chars: int = 10000) -> str:
    """Downsampled transcript for the episode-card call.

    26k chars costs ~5.7k input tokens per episode, and on a free tier with a
    200k tokens-per-day ceiling that is a meaningful fraction of the whole
    budget for a task -- naming an episode's topics -- that an evenly
    downsampled tenth of the transcript answers just as well.
    """
    segs = ep["segments"]
    lines = [f"[{config.fmt_ts(s['start'])}] {s['text']}" for s in segs]
    blob = "\n".join(lines)
    if len(blob) <= max_chars:
        return blob
    stride = max(2, len(blob) // max_chars + 1)
    return "\n".join(lines[::stride])[:max_chars]


def build_episode_card(ep: dict, attempts: int = 3) -> dict:
    """Build one episode card, insisting on a usable result.

    The card is not optional decoration: its topics and summary become the
    context header prepended to every chunk in the episode, and the episode
    index that routing questions search. A card that comes back empty -- a
    small model returning zero characters, or JSON truncated mid-object --
    would otherwise be written to disk and silently degrade both. So retry,
    and escalate the token budget each time rather than accept an empty one.
    """
    for attempt in range(attempts):
        card = _try_episode_card(ep, max_tokens=2600 + 1200 * attempt)
        if card.get("topics"):
            return card
        print(f"    [warn] empty episode card for {ep['episode_id']}, "
              f"retry {attempt + 1}/{attempts}", flush=True)
    raise SystemExit(
        f"Could not build an episode card for {ep['episode_id']} after "
        f"{attempts} attempts. Re-run `make enrich` (completed episodes are "
        f"cached), or set FERMI_GROQ_MODEL to a larger model.")


def _try_episode_card(ep: dict, max_tokens: int) -> dict:
    body = compress_transcript(ep)
    data = llm.json_chat(
        OUTLINE_SYSTEM,
        [{"role": "user", "content": f"Filename hint: {ep['title']}\n\nTRANSCRIPT:\n{body}"}],
        # gpt-oss spends part of the budget on hidden reasoning before it
        # emits content; at 1200 the outline JSON truncated intermittently
        # and parsed to {}, silently yielding an episode card with no topics.
        max_tokens=max_tokens, temperature=0.1)
    return {
        "episode_id": ep["episode_id"],
        "file_title": ep["title"],
        "title": data.get("title") or ep["title"],
        "summary": data.get("summary", ""),
        "topics": data.get("topics", []),
        "outline": data.get("outline", []),
        "duration_s": ep["duration_s"],
        "audio_path": ep["audio_path"],
        "asr_model": ep.get("asr_model", ""),
    }


def add_contexts(chunks: list[dict], card: dict, batch: int = 8) -> None:
    header = (f"EPISODE: {card['title']}\nSUMMARY: {card['summary']}\n"
              f"TOPICS: {', '.join(card.get('topics', [])[:12])}")
    for i in range(0, len(chunks), batch):
        group = chunks[i : i + batch]
        blocks = "\n\n".join(
            f"<<<CHUNK {n}>>>\n{c['text']}" for n, c in enumerate(group, start=1))
        data = llm.json_chat(
            CONTEXT_SYSTEM,
            [{"role": "user", "content": f"{header}\n\nPASSAGES:\n{blocks}"}],
            max_tokens=1600, temperature=0.1)
        ctxs = data.get("contexts") or []
        for c, ctx in zip(group, ctxs):
            if isinstance(ctx, str):
                c["context"] = ctx.strip()[:300]
        done = min(i + batch, len(chunks))
        print(f"    contexts {done}/{len(chunks)}", end="\r", flush=True)
    print()


def run(transcripts: Path, chunks_json: Path, episodes_json: Path,
        skip_context: bool) -> None:
    if not chunks_json.exists():
        raise SystemExit(f"{chunks_json} missing. Run: make chunk")
    eps = json.loads(transcripts.read_text())["episodes"]
    chunks = json.loads(chunks_json.read_text())["chunks"]

    # Resume support. Enrichment is the most expensive ingest step (one LLM
    # call per episode plus one per batch of 8 chunks) and free-tier daily
    # token caps are real: an earlier run died on a 429 with the whole pass
    # unwritten and ~10 minutes of completed work discarded. So checkpoint
    # after every episode, and skip on re-run whatever is already done.
    done_cards: dict[str, dict] = {}
    if episodes_json.exists():
        try:
            for c in json.loads(episodes_json.read_text())["episodes"]:
                if c.get("topics"):
                    done_cards[c["episode_id"]] = c
        except (json.JSONDecodeError, KeyError):
            pass
    if done_cards:
        print(f"resuming: {len(done_cards)} episode card(s) already built "
              f"({', '.join(sorted(done_cards))})")

    def checkpoint(cards: list[dict]) -> None:
        episodes_json.parent.mkdir(parents=True, exist_ok=True)
        episodes_json.write_text(json.dumps({"episodes": cards}, indent=2))
        chunks_json.write_text(json.dumps({"chunks": chunks}, indent=2))

    cards = []
    for ep in eps:
        eid = ep["episode_id"]
        mine = [c for c in chunks if c["episode_id"] == eid]
        already = done_cards.get(eid)
        if already and (skip_context or all(c.get("context") for c in mine)):
            print(f"{eid}: cached, skipping")
            cards.append(already)
            continue

        card = already
        if card is None:
            print(f"{eid}: building episode card ...", flush=True)
            card = build_episode_card(ep)
        cards.append(card)
        print(f"    title:  {card['title']}")
        print(f"    topics: {', '.join(card['topics'][:6])}")
        if not skip_context:
            todo = [c for c in mine if not c.get("context")]
            if todo:
                add_contexts(todo, card)
        checkpoint(cards)

    checkpoint(cards)
    filled = sum(1 for c in chunks if c["context"])
    print(f"\nWrote {episodes_json} ({len(cards)} cards) and updated {chunks_json} "
          f"({filled}/{len(chunks)} chunks have context headers)")
    print("LLM usage so far:", llm.usage_report())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build episode cards and chunk contexts.")
    ap.add_argument("--transcripts", type=Path, default=config.TRANSCRIPTS_JSON)
    ap.add_argument("--chunks", type=Path, default=config.CHUNKS_JSON)
    ap.add_argument("--episodes", type=Path, default=config.EPISODES_JSON)
    ap.add_argument("--skip-context", action="store_true",
                    help="episode cards only; cheaper, slightly worse retrieval")
    a = ap.parse_args(argv)
    run(a.transcripts, a.chunks, a.episodes, a.skip_context)


if __name__ == "__main__":
    sys.exit(main())
