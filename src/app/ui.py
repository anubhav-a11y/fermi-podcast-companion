"""Streamlit chat UI.  streamlit run src/app/ui.py   (or: make run)

Deliberately thin — a polished frontend is a stated non-goal. The one thing
worth building here is the payoff of citing timestamps: each source expands
into a real audio player seeked to that second, so the learner can verify
an answer against the original audio in one click.
"""

from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from src import config  # noqa: E402
from src.app import llm  # noqa: E402
from src.app.session import Companion  # noqa: E402

st.set_page_config(page_title="Fermi Podcast Companion", page_icon="🎧", layout="centered")


def _gate() -> None:
    """Optional shared-password gate, active only when a password is set.

    Needed for a hosted copy for two reasons that have nothing to do with
    security theatre: the app spends real API credit on every turn, and the
    index contains full transcripts of audio that belongs to Fermi, not to
    this repo. Locally no password is configured and this is a no-op.
    """
    expected = os.environ.get("FERMI_APP_PASSWORD")
    if not expected:
        try:                                    # st.secrets raises if absent
            expected = st.secrets.get("FERMI_APP_PASSWORD")
        except Exception:
            expected = None
    if not expected:
        return

    if st.session_state.get("_authed"):
        return

    st.title("🎧 Fermi Podcast Companion")
    st.caption("This demo is password-protected because it spends API credit "
               "per question and indexes audio that is not mine to publish.")
    with st.form("gate"):
        given = st.text_input("Access password", type="password")
        if st.form_submit_button("Enter"):
            if hmac.compare_digest(given.strip(), expected.strip()):
                st.session_state["_authed"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()


_gate()


@st.cache_resource(show_spinner="Loading index ...")
def get_companion(preset: str) -> Companion:
    return Companion(settings=config.get_preset(preset))


preset = st.sidebar.selectbox("Preset", sorted(config.PRESETS), index=1,
                              help="baseline = naive RAG; improved = routed hybrid "
                                   "retrieval with abstention")
comp = get_companion(preset)

st.title("🎧 Fermi Podcast Companion")
st.caption(comp.banner())

with st.sidebar:
    st.subheader("Episodes")
    for e in comp.corpus.episodes:
        with st.expander(f"{e['episode_id']} · {e['title'][:34]}"):
            st.write(e.get("summary", ""))
            st.caption("Topics: " + ", ".join(e.get("topics", [])[:10]))
            st.caption(f"Length: {config.fmt_ts(e.get('duration_s', 0))}")
    st.divider()
    st.subheader("Try asking")
    for ex in ["Which episode should I start with to understand superconductivity, and why?",
               "Explain what they mean by 'more is different', simply.",
               "Compare what the episodes say about noise in quantum systems.",
               "I didn't follow that. Walk me through it step by step.",
               "Do these episodes explain Hawking radiation?"]:
        st.caption("· " + ex)
    st.divider()
    if st.button("Clear conversation"):
        comp.reset()
        st.session_state.messages = []
        st.rerun()
    st.caption(f"Trace: `{comp.trace_path.name}`")
    st.caption(f"Usage: {llm.usage_report()}")

if "messages" not in st.session_state:
    st.session_state.messages = []


def render_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander(f"Sources — {len(sources)} passages from the audio", expanded=False):
        for s in sources:
            ep = comp.corpus.episode_by_id.get(s["episode_id"], {})
            st.markdown(
                f"**[{s['label']}]** {ep.get('title', s['episode_title'])} "
                f"· {config.fmt_ts(s['start_s'])}–{config.fmt_ts(s['end_s'])} "
                f"· dense `{s['dense']:.3f}` lex `{s['lexical']:.3f}`")
            st.caption(s["text"])
            path = config.resolve_audio(ep.get("audio_path"))
            if path:
                st.audio(path, start_time=int(s["start_s"]))
            else:
                st.caption("_(audio file not found — put the episode files in "
                           "`data/audio/`, or run `make audio-web` to build "
                           "the committed low-bitrate copies)_")
            st.divider()


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            if m.get("abstained"):
                st.warning("Answered as *not covered* — the collection does not "
                           "support an answer here.")
            if m.get("invalid_citations"):
                st.error("Removed unverifiable citations: "
                         + ", ".join(m["invalid_citations"]))
            render_sources(m.get("sources", []))
            if m.get("intent"):
                st.caption(f"intent `{m['intent']}` · searched as "
                           f"`{m.get('standalone_query', '')}`")

if q := st.chat_input("Ask about the episodes..."):
    st.session_state.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        with st.spinner("Searching the audio ..."):
            ans = comp.ask(q)
        st.markdown(ans.text)
        if ans.abstained:
            st.warning("Answered as *not covered*.")
        if ans.invalid_citations:
            st.error("Removed unverifiable citations: " + ", ".join(ans.invalid_citations))
        render_sources(ans.sources)
        st.caption(f"intent `{ans.intent}` · searched as `{ans.standalone_query}`")
    st.session_state.messages.append({
        "role": "assistant", "content": ans.text, "sources": ans.sources,
        "intent": ans.intent, "standalone_query": ans.standalone_query,
        "abstained": ans.abstained, "invalid_citations": ans.invalid_citations,
    })
