.PHONY: help setup setup-ingest check fixture smoke ingest transcribe chunk enrich index peek run chat eval-baseline eval-improved eval report ablate audio-web clean-runs clean-artifacts

PY ?= python
VENV ?= .venv

help:
	@echo ""
	@echo "  Fermi Podcast Companion"
	@echo ""
	@echo "  SETUP"
	@echo "    make setup            create .venv, install runtime deps, copy .env.example\n    make setup-ingest     extra deps to rebuild artifacts from raw audio"
	@echo "    make check            verify keys, ffmpeg, audio files, artifacts"
	@echo ""
	@echo "  OFFLINE TEST (no keys, no audio, ~10s)"
	@echo "    make smoke            build fixture corpus and run the eval on it"
	@echo ""
	@echo "  BUILD FROM THE REAL AUDIO"
	@echo "    make ingest           transcribe + chunk + enrich + index  (one command)"
	@echo "    make peek             skim the transcript to sanity-check ASR quality"
	@echo ""
	@echo "  USE IT"
	@echo "    make run              Streamlit UI with click-to-play citations"
	@echo "    make chat             terminal REPL"
	@echo ""
	@echo "  EVALUATE"
	@echo "    make eval             baseline run, improved run, and the comparison"
	@echo "    make report           re-print the comparison table"
	@echo "    make ablate           per-mechanism attribution table (6 ablations)"
	@echo "    make audio-web        24kbps copies for a hosted demo (53 MB)"
	@echo ""

# ------------------------------------------------------------------- setup
setup:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Done. Now:  1) put your API keys in .env"
	@echo "            2) source $(VENV)/bin/activate"
	@echo "            3) make check"
	@echo ""
	@echo "That installs what the shipped system needs to RUN against the"
	@echo "committed artifacts. To rebuild them from the raw audio:"
	@echo "            make setup-ingest   # adds a Whisper backend"

# Extra dependencies only needed to rebuild artifacts/ from the audio.
setup-ingest:
	$(VENV)/bin/pip install -r requirements-ingest.txt

check:
	$(PY) scripts/check_setup.py

# ------------------------------------------------------- offline smoke test
fixture:
	$(PY) scripts/make_fixture.py

smoke: fixture
	@echo "\n--- chunking fixture ---"
	FERMI_ARTIFACT_DIR=artifacts_fixture $(PY) -m src.ingest.chunk
	@echo "\n--- indexing fixture (lexical only, no API calls) ---"
	FERMI_ARTIFACT_DIR=artifacts_fixture FERMI_EMBED_PROVIDER=none $(PY) -m src.ingest.index
	@echo "\n--- baseline run on fixture ---"
	FERMI_ARTIFACT_DIR=artifacts_fixture FERMI_EMBED_PROVIDER=none FERMI_LLM_PROVIDER=stub \
	  $(PY) -m eval.run --preset baseline --cases eval/cases_fixture.yaml --out runs/smoke_baseline
	@echo "\n--- improved run on fixture ---"
	FERMI_ARTIFACT_DIR=artifacts_fixture FERMI_EMBED_PROVIDER=none FERMI_LLM_PROVIDER=stub \
	  $(PY) -m eval.run --preset improved --cases eval/cases_fixture.yaml --out runs/smoke_improved
	@echo "\n--- comparison ---"
	$(PY) -m eval.report --a runs/smoke_baseline --b runs/smoke_improved
	@echo "\nSmoke test complete. The plumbing works. Now build the real corpus: make ingest"

# -------------------------------------------------------------- real ingest
ingest: transcribe chunk enrich index
	@echo "\nCorpus ready. Sanity-check it:  make peek     Then:  make run"

transcribe:
	$(PY) -m src.ingest.transcribe

chunk:
	$(PY) -m src.ingest.chunk

enrich:
	$(PY) -m src.ingest.enrich

index:
	$(PY) -m src.ingest.index

peek:
	$(PY) scripts/peek.py

# ------------------------------------------------------------------ product
run:
	streamlit run src/app/ui.py

chat:
	$(PY) -m src.app.cli

# --------------------------------------------------------------- evaluation
eval-baseline:
	$(PY) -m eval.run --preset baseline

eval-improved:
	$(PY) -m eval.run --preset improved

eval: eval-baseline eval-improved report

report:
	$(PY) -m eval.report --out runs/comparison.md

# Attribution: `improved` flips six flags at once, so the headline delta
# cannot credit any single mechanism. Each abl_* preset flips exactly one.
# All rows run --no-judge, including the two reference rows, so the mean
# scores are computed over the same metrics and are comparable.
ABLATIONS = abl_hybrid abl_router abl_rewrite abl_episode_index \
            abl_per_episode abl_abstention

ablate:
	$(PY) -m eval.run --preset baseline --no-judge --out runs/baseline_nojudge
	$(PY) -m eval.run --preset improved --no-judge --out runs/improved_nojudge
	@for p in $(ABLATIONS); do \
		echo "--- $$p"; \
		$(PY) -m eval.run --preset $$p --no-judge || exit 1; \
	done
	$(PY) scripts/ablation_table.py --out runs/ablations.md

# Low-bitrate copies for a hosted demo. 24 kbps mono keeps speech clearly
# intelligible and durations byte-exact, so every timestamp in the index
# stays valid, at 53 MB for 4h44m instead of 273 MB.
audio-web:
	@mkdir -p data/audio_web
	@for f in data/audio/*.mp3; do \
		out="data/audio_web/$$(basename "$$f")"; \
		[ -f "$$out" ] && continue; \
		echo "  $$(basename "$$f")"; \
		ffmpeg -v error -y -i "$$f" -ac 1 -ar 22050 -b:a 24k "$$out"; \
	done
	@du -sh data/audio_web

# ------------------------------------------------------------------- hygiene
clean-runs:
	rm -rf runs/* traces/*

clean-artifacts:
	rm -rf artifacts/*.json artifacts/*.npy artifacts_fixture
