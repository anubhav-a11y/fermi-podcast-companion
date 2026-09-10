"""Hugging Face Spaces / Streamlit Cloud entrypoint.

Hosted Streamlit runners look for `app.py` or `streamlit_app.py` at the repo
root; the real UI lives in `src/app/ui.py`. Locally, `make run` points
Streamlit straight at that module, so this file exists purely so a hosted
copy needs no extra configuration.
"""
from pathlib import Path

exec(  # noqa: S102 - deliberate: run the UI module in this process
    compile(
        (Path(__file__).parent / "src" / "app" / "ui.py").read_text(),
        "src/app/ui.py",
        "exec",
    )
)
