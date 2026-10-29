# Predictive Scheduling of Speculative Tool Calls Under Shared API Quotas

CSE 585 research project by Jack McClure, Saitej Velaga, and Angela Li.
Requirements: [October 23 proposal](CSE_585_Project_Proposal_oct_23.pdf).

This repository contains a deterministic replay engine, observed-state history
forecasts, bounded paired admission, quota reserve baselines, a single-process
FastAPI/asyncio gateway, a frozen local HotpotQA search corpus, and reproducible
experiments. A dispatch spends quota until the next fixed window; completion
and cancellation do not refund it. Required calls get priority and exact matching
calls within the same task share executions and results.

## Setup and tests

Replay and history forecasting require only Python 3.11+ and the standard library.
The gateway, model HTTP adapters, and plots use optional dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[live,analysis]'
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

`requirements-lock.txt` records the Python 3.13/macOS environment used for the
reported run. A version-exact environment can use `pip install -r requirements-lock.txt`.
The full suite contains 67 tests; HTTP/model contract tests skip when their
optional dependencies are absent.

## API readiness without keys

Start with [the offline verification and API setup guide](docs/API_SETUP.md).
`.env.example` lists every supported endpoint, credential and gateway setting.
The `mock` System One predictor tests HTTP serialization without network calls;
`python -m quota_spec.qa --backend mock` tests the bounded QA-agent workflow.
Real model access is selected explicitly. No API key is needed for the existing
replay, scripted live validation, tests, or either mock mode.

## Replay comparisons

```sh
PYTHONPATH=src .venv/bin/python -m quota_spec.cli --agents 4 --output results/demo
PYTHONPATH=src .venv/bin/python -m quota_spec.cli --trace data/pilot.json --capacity 3 --window-s .1 --output results/pilot
PYTHONPATH=src .venv/bin/python -m quota_spec.cli --trace data/evaluation.json --history-trace data/development.json --capacity 3 --window-s .1 --horizon-s .3 --samples 8 --skip-reference --output results/predictive-demo
```

The last command launches all 100 evaluation tasks concurrently. For controlled
1/2/4/8-agent batches, use the study runner below. `--history-trace` must have
disjoint task IDs. Other controls include `--reserve`, `--samples`, `--max-calls`,
`--epsilon`, `--overhead-s`, and `--required-order progress` for the separate
required-ordering experiment. Future-informed reference results are privileged
and greedy, not optimal or deployable.

Each CLI run saves input trace, configuration, history model (when fitted),
metrics, and per-policy decision/event logs. Reuse the frozen inputs rather than
recollecting timings when reproducing an existing experiment. Output files in
an existing directory are replaced; choose a new output directory to preserve runs.

## Data and experiments

`data/` includes 200 measured **scripted retrieval** trajectories over 1,991
HotpotQA documents, split into 100 development and 100 evaluation tasks. The
20-task pilot is a subset of development. The agent sees questions and search
outputs; gold answers/supporting facts are kept separately in `labels.json`.
These are actual local search invocations, but they are not LLM-agent traces.
See [data attribution and provenance](data/README.md).

```sh
# Existing frozen data: no dataset download or model key needed.
PYTHONPATH=src .venv/bin/python -m quota_spec.experiments --output results/study
PYTHONPATH=src .venv/bin/python -m quota_spec.live --output results/live
PYTHONPATH=src .venv/bin/python -m quota_spec.preflight --output results/access

# Repeat saved settings, seeds and modeled overhead exactly, in a fresh directory.
PYTHONPATH=src .venv/bin/python -m quota_spec.experiments --frozen-config results/study/frozen_config.json --output results/repeated-study

# Collect a NEW dataset/timing run into a NEW directory (downloads public data).
PYTHONPATH=src .venv/bin/python -m quota_spec.collect --output data-new
```

Use `--no-plots` to omit matplotlib and figure generation.
The study tunes on development, writes its configuration before evaluation,
then runs 12 focused settings, five repeated seeds, and seven policies/controls.
It saves per-task outcomes, events, calibration, paired confidence intervals,
and PNG/PDF sensitivity figures. Quota resets between batches; this is a bounded
concurrency experiment rather than a continuous arrival queue. The live check
compares actual gateway timing against replay and verifies identical required
search results across policies. Answer exact match is unmeasured.

## Live HTTP gateway

```sh
PYTHONPATH=src .venv/bin/python -m uvicorn quota_spec.gateway:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

`QUOTA_CORPUS` can select a corpus file. `GET /health` reports its checksum.
`POST /observe` accepts current `task_id`, `task_context`, `completed_calls`, and
`result_excerpt`, and optional `deadline_s`. Call `POST /finish/{task_id}` when
an agent finishes to release its registry and progress. `POST /candidate` and `POST /required` accept
`{"task_id":"agent-a","query":"Scott Derrickson"}`. Candidates return only
admission status; required requests return results. The default HTTP factory uses
current-capacity admission. Set `QUOTA_POLICY=predictive` and `QUOTA_PREDICTOR=history|mock|jev|kev`
to select predictive live admission; `QUOTA_HISTORY` selects the development
trace. Explicit `create_app(policy=...)` and `Gateway(policy=...)` also work. Use one worker because the ledger and
registry live in process memory.

## Jev and Kev

Both adapters use the documented System One `state/model/questions` contract,
bounded contexts and a total request timeout. They return the same bounded
forecast schema as history and log inference latency, tokens, failures, and
monetary cost when prices are explicitly configured. Missing cost is `null`.

```sh
# Set credentials/endpoints in your environment, then choose a predictor:
PYTHONPATH=src .venv/bin/python -m quota_spec.cli --trace data/evaluation.json --history-trace data/development.json --predictor kev --context progress --skip-reference --output results/kev
```

Jev requires `TYPESAFE_API_KEY`; Kev requires `KEV_BASE_URL`. Context modes are
`task`, `history`, `progress`, `no_history`, and `no_progress`. Kev's selected
artifact/revision and the local access audit are documented in
[model access](docs/MODEL_ACCESS.md). Neither external model was run in the
reported experiments. No model training, paid API call, or hosted deployment
is needed for the local workflow. The new bounded HTTP QA-agent integration is
mock-tested; real answer quality still requires an accessible main model.
See [API setup](docs/API_SETUP.md) for its separate `QA_*` configuration.

## Documentation

- [Implementation checklist and remaining blockers](docs/IMPLEMENTATION_PLAN.md)
- [Architecture and admission semantics](docs/ARCHITECTURE.md)
- [Experimental design](docs/EXPERIMENTS.md)
- [Trace schema](docs/TRACE_FORMAT.md)
- [Measured status](docs/STATUS.md)
- [Exploratory research report](docs/REPORT.md)

Keep credentials in environment variables or an untracked `.env`. Generated
results, raw downloads, and the local virtual environment are ignored by Git.
No hosted Git remote is configured.
