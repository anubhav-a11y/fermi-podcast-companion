"""Hosted entrypoint (Streamlit Community Cloud / any Streamlit runner).

Two things have to happen before `src.config` is imported, which is why this
file exists rather than pointing the runner straight at `src/app/ui.py`:

1. `src.config` resolves every provider setting from `os.environ` at import
   time. On a hosted runner the settings arrive in `st.secrets`, so they
   have to be copied across *first* — otherwise config silently falls back
   to its defaults and the app talks to the wrong provider.
2. `.env` does not exist on a hosted runner, so there is nothing else to
   read them from.
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

# --- bridge st.secrets -> os.environ, before anything reads config ---------
# Streamlit does export top-level secrets as environment variables, but only
# for the process that owns them and not reliably before third-party imports
# run. Doing it explicitly costs nothing and removes a silent failure mode:
# a missing FERMI_EMBED_PROVIDER meant the query embedder defaulted to a
# different model than the one that built the committed index.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass  # no secrets file: running locally, .env handles it

exec(  # noqa: S102 - deliberate: run the UI module in this process
    compile(
        (Path(__file__).parent / "src" / "app" / "ui.py").read_text(),
        "src/app/ui.py",
        "exec",
    )
)
