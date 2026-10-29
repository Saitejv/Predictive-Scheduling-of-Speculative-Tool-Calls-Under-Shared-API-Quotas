# Predictive Scheduling of Speculative Tool Calls Under Shared API Quotas

CSE 585 project by Jack McClure, Saitej Velaga, and Angela Li.
Based on the [October 23 proposal](CSE_585_Project_Proposal_oct_23.pdf).

**Start with [the complete runbook](docs/RUNBOOK.md).** The code supports key-free
verification and actual-model collection, predictor/context experiments, paired
replay, and live QA validation. Add credentials and endpoint/model settings to
`.env` when available. No real model measurements are claimed yet.

## Run without API keys

```sh
make setup
make test
make offline
```

`make offline` runs a 20-task mock pilot through collection, five forecast contexts,
12 scheduling settings, paired policy comparisons, a development reference, live
QA checks, plots, and a generated `results/offline-pilot/REPORT.md`. Mock answer
scores remain null. Use `make offline OUTPUT=results/another-pilot` for a fresh run.

## Collect actual data

```sh
cp .env.example .env
# Fill in the QA endpoint/model/key and available demand predictors.
set -a
source .env
set +a

# Pilot using only the main QA model and history forecasting.
.venv/bin/python -m quota_spec.pipeline \
  --backend http --predictors history --count 20 --window-s 10 \
  --output results/llm-pilot

# Full proposal experiment once Jev and a Kev server are available.
.venv/bin/python -m quota_spec.pipeline \
  --backend http --predictors jev kev --count 200 --window-s 10 \
  --max-requests 20000 --output results/llm-full
```

Repeat the same command with `--resume` after an interruption. Successful task
and forecast checkpoints avoid repeated inference. Existing run directories are
protected. The [runbook](docs/RUNBOOK.md) explains request budgets, cost settings,
provider compatibility, staged execution, exact repeats and artifacts. A Kev
endpoint must already be serving a model; an API key alone does not create it.

## Contribution and implementation

The bounded paired admission rule estimates candidate savings against delays to
other agents' future required calls. Both simulations use the same sampled demand,
retain quota debt until fixed-window refill, account for exact result reuse, and
apply an estimated incremental deadline-risk guard. Jev, Kev and history forecast
demand; the cross-agent admission rule is the systems contribution.

The repository includes:

- Atomic asyncio/FastAPI quota gateway, exact caching and in-flight joining.
- Replay with serial dependencies, candidate/inference timing and final answer time.
- No speculation, current capacity, tuned fixed reserve, usage forecast reserve,
  predictive full/own-agent ablation, progress ordering and privileged reference.
- Label-blind, resumable QA collection over a checksummed local HotpotQA corpus.
- Frozen Jev/Kev/mock forecast banks for five observed-context configurations.
- Development-only tuning, 1/2/4/8-agent studies, paired multi-metric confidence
  intervals, calibration, event/outcome logs, plots and report generation.
- Live QA answer EM/F1, quota checks, token/cost/failure telemetry and mock modes.

The supplied 200 trajectories are **scripted retrieval**, not LLM evidence.
The fixed candidate generator uses the question/top observed title; it is not a
reproduction of a learned generator from Speculative Actions. Real improvements,
calibration and answer quality must be established by the actual-model experiments.
Negative or neutral scheduling results are valid outcomes.

## Individual commands

```sh
.venv/bin/python -m quota_spec.cli --skip-reference --output results/demo
.venv/bin/python -m quota_spec.experiments --output results/scripted-study
.venv/bin/python -m quota_spec.live --output results/scripted-live
.venv/bin/python -m quota_spec.preflight --output results/access
.venv/bin/python -m quota_spec.collect_qa --help
.venv/bin/python -m quota_spec.forecast_bank --help
.venv/bin/python -m quota_spec.pipeline --help
```

The standalone study defaults to the supplied scripted data and a 0.1-second
base quota window. The LLM pipeline defaults to 10 seconds. Both sweep 12 focused
settings with five paired seeds unless overridden. Use `--no-plots` to omit
matplotlib. Replay and history require only Python's standard library. HTTP
adapters/gateway require the `live` extra; plotting requires `analysis`.
`requirements-lock.txt` records the earlier Python 3.13/macOS environment;
the declared extras support fresh compatible installations.

## HTTP gateway

```sh
.venv/bin/python -m uvicorn quota_spec.gateway:create_app --factory \
  --host 127.0.0.1 --port 8000 --workers 1
```

`POST /observe` publishes observed progress. `/candidate` and `/required` accept
`{"task_id":"agent-a","query":"Scott Derrickson"}`. Only required calls expose
results. Call `POST /finish/{task_id}` to release task state. `/health` reports the
corpus checksum. Select policies/predictors using the `QUOTA_*` variables in
`.env.example`. Use one worker: quota and registry state are process-local.

## Documentation

- [Runbook and model setup](docs/RUNBOOK.md)
- [Architecture and admission semantics](docs/ARCHITECTURE.md)
- [Experimental design](docs/EXPERIMENTS.md)
- [Trace schema](docs/TRACE_FORMAT.md)
- [Current status](docs/STATUS.md)
- [Validation evidence](docs/REVIEW_VALIDATION.md)
- [Proposal checklist](docs/IMPLEMENTATION_PLAN.md)
- [Data attribution](data/README.md)

The old [exploratory report](docs/REPORT.md), retained figures and numerical summary
are explicitly historical and must not be cited as results from the current code.
Generated `results/`, local environments and credentials are ignored by Git.
