PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
OUTPUT ?= results/hotpot-smoke
EVIDENCE ?= results/hotpot-live-paired-20
REPORT_OUTPUT ?= results/hotpot-report
EXPORT_OUTPUT ?= results/hotpot-stage-export
COUNT ?= 20
OFFSET ?= 0
MAX_USD ?= .50
ACTOR ?= google/gemini-2.5-flash
SPECULATOR ?= openai/gpt-4.1-nano
CAPTURE_INTERVAL_S ?= 1.1
PAID_SOURCE ?= results/hotpot-live-audit/source-snapshot

.PHONY: setup prepare test test-baseline test-extensions lint offline live capture report export reference single-agent-check
setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -e '.[paper,analysis,dev]'
prepare:
	$(PYTHON) -m quota_spec.upstream
test:
	$(PYTHON) -m unittest discover -s tests -v
test-baseline:
	$(PYTHON) -m unittest discover -s tests/baseline -v
test-extensions:
	$(PYTHON) -m unittest discover -s tests/extensions -v
lint:
	$(RUFF) check src tests scripts
	$(RUFF) format --check src tests scripts
offline:
	$(PYTHON) -m quota_spec.hotpot_runtime --backend mock --count 2 --output $(OUTPUT)
live:
	$(PYTHON) -m quota_spec.hotpot_runtime --backend http --purpose benchmark --actor $(ACTOR) --speculator $(SPECULATOR) --count $(COUNT) --offset $(OFFSET) --max-usd $(MAX_USD) --max-requests 2000 --output $(OUTPUT)
capture:
	$(PYTHON) -m quota_spec.hotpot_runtime --backend http --purpose capture --actor $(ACTOR) --speculator $(SPECULATOR) --count $(COUNT) --offset $(OFFSET) --max-usd $(MAX_USD) --max-requests 2000 --min-request-interval-s $(CAPTURE_INTERVAL_S) --output $(OUTPUT)
single-agent-check:
	$(PYTHON) -m quota_spec.single_agent_reference --output $(OUTPUT)
report:
	$(PYTHON) scripts/report_hotpot_runtime.py $(EVIDENCE) --output $(REPORT_OUTPUT) --source-snapshot $(PAID_SOURCE)
export:
	$(PYTHON) -m quota_spec.stage_export $(EVIDENCE) --output $(EXPORT_OUTPUT)
reference:
	$(PYTHON) scripts/run_upstream_baseline.py --help
