PYTHON ?= .venv/bin/python
OUTPUT ?= results/offline-pilot

.PHONY: setup test lint offline preflight
setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -e '.[live,analysis,dev]'
test:
	$(PYTHON) -m unittest discover -s tests -v
lint:
	.venv/bin/ruff check src tests
	.venv/bin/ruff format --check src tests
offline:
	$(PYTHON) -m quota_spec.pipeline --backend mock --predictors mock --count 20 --window-s .1 --seeds 7 17 --samples 4 --output $(OUTPUT)
preflight:
	$(PYTHON) -m quota_spec.preflight --output results/access-offline
