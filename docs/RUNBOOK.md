# Run the complete project

Run commands from the repository root. Python 3.11+ is required. The supplied
corpus and 200 source tasks are already local; no dataset download is needed.

## Install and verify without keys

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[live,analysis,dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
.venv/bin/python -m quota_spec.preflight --output results/access-offline
.venv/bin/python -m quota_spec.pipeline \
  --backend mock --predictors mock --count 20 --window-s .1 \
  --seeds 7 17 --samples 4 --output results/offline-pilot
```

The pipeline collects 10 development and 10 evaluation mock trajectories, freezes
all five mock predictor contexts, tunes on development, evaluates 12 settings,
compares full versus own-agent admission, runs a privileged development reference,
checks live QA through ten policy configurations, and writes `REPORT.md`.
Mock answer scores are null. No external inference occurs in this command.
Use `--no-plots` when matplotlib is unavailable. Dependency installation itself
requires access to a package index unless packages are cached.

## Configure actual models

```sh
cp .env.example .env
# Edit .env, then export it into the shell:
set -a
source .env
set +a
```

| Integration | Required configuration | Purpose |
| --- | --- | --- |
| Main QA model | `QA_CHAT_URL`, `QA_MODEL`, and the provider's `QA_API_KEY` if required | Generate searches and answers |
| Jev | `TYPESAFE_API_KEY`; optional `JEV_BASE_URL` / `JEV_MODEL` | Forecast demand |
| Kev | `KEV_BASE_URL` to an already running System One server; optional `KEV_API_KEY` | Forecast demand |

The QA URL is the **complete chat-completions endpoint**, including its path.
The QA adapter sends JSON instructions and expects a JSON search/answer action
in `choices[0].message.content`. It does not use a provider's native tool schema.
For endpoints that require `max_completion_tokens`, set
`QA_TOKEN_PARAMETER=max_completion_tokens`; otherwise keep `max_tokens`.
`QA_MAX_OUTPUT_TOKENS` defaults to 512 and can be increased for models with a
larger reasoning/output budget. Provider-specific compatibility still needs the
small live pilot; no account has been authenticated during offline verification.

Jev and Kev use the [System One contract](https://docs.typesafe.ai/api/system-one).
A Jev key does **not** start a Kev server; see the
[Kev serving instructions](https://github.com/jaredpalmer/kev). Record the exact
served weight revision in `KEV_REVISION` and use a pinned model where available.
No weights or remote servers are provisioned by this project.

Set `QA_INPUT_USD_PER_MILLION`, `QA_OUTPUT_USD_PER_MILLION`, and the corresponding
`QUOTA_*` prices to obtain monetary cost estimates. Prices may also be passed as
CLI flags. Unknown prices/token usage remain null, including free categories
unless explicitly priced at zero. Do not commit `.env`; it is ignored.

## Actual-model pilot and full collection

Start with a small pilot to verify the selected QA endpoint, model responses,
and demand predictors before a full collection. Select only available providers.

```sh
# Main QA model + history needs no Jev/Kev access.
.venv/bin/python -m quota_spec.pipeline \
  --backend http --predictors history --count 20 --window-s 10 \
  --output results/llm-history-pilot

# All proposal integrations once both demand predictors are configured.
.venv/bin/python -m quota_spec.pipeline \
  --backend http --predictors jev kev --count 200 --window-s 10 \
  --max-requests 20000 --output results/llm-full
```

`--count 200` preserves 100 development and 100 evaluation task IDs. Collection
makes at most `count * (max_calls + 1)` main-model requests (800 at the defaults).
The separate live stage makes up to `live_count * (max_calls + 1)` main-model
requests **per live policy**, plus demand inference; set `--live-count 0` to omit
it. The forecast-bank request limit applies only to bank construction, not QA
or the live stage. Use staged execution below for an exact bank request preview.

The default live count is four, repeated across baselines, history full/own,
progress-order controls, and each selected external predictor's full/own policy using progress context.
The replay study evaluates every selected context. A default 10-second quota
window is a starting setting for LLM latency; choose it after the development
pilot and freeze it before examining held-out results. The study sweeps 0.3x,
1x, and 3x that period. Deadlines are four windows after arrival.

The collector stops on the first failed model task and atomically retains
successful tasks and failure telemetry. Fix access and rerun the **same command**
with `--resume`. Successful QA tasks and forecast responses are not called again. Failed attempts remain archived for cost auditing. All provider configurations and bank checksums are validated before resumed forecast inference begins.
A partially written study is preserved as `study-interrupted-N` and recomputed
without new model calls. A failed live stage is preserved and rerun; it can issue
new model calls. Resume rejects changed model/source/experiment settings. Changing
source code, resolved model/endpoint/pricing settings, or plot settings requires a fresh pipeline directory; retained traces can be used by
the staged study commands. Fresh runs refuse to overwrite nonempty directories.

## Staged execution and request preview

```sh
# Collect real QA trajectories once. Use --resume after an interrupted collection.
.venv/bin/python -m quota_spec.collect_qa \
  --backend http --count 200 --output results/llm-data

# Preview exact unique input counts without keys or inference.
.venv/bin/python -m quota_spec.forecast_bank --data results/llm-data \
  --backends jev kev --output results/llm-forecasts

# Add --execute to perform the explicitly selected inference.
.venv/bin/python -m quota_spec.forecast_bank --data results/llm-data \
  --backends jev kev --output results/llm-forecasts --max-requests 20000 --execute

# All provider/context responses are frozen; this study makes no API requests.
.venv/bin/python -m quota_spec.experiments --data results/llm-data \
  --forecast-banks results/llm-forecasts/jev-*.json results/llm-forecasts/kev-*.json \
  --window-s 10 --output results/llm-study

# Exact repeat: same code, input traces, banks, tuning and seeds; fresh output.
.venv/bin/python -m quota_spec.experiments --data results/llm-data \
  --forecast-banks results/llm-forecasts/jev-*.json results/llm-forecasts/kev-*.json \
  --frozen-config results/llm-study/frozen_config.json --output results/llm-repeat
```

For history-only studies, omit `--forecast-banks`. For a reduced model pilot,
use `--contexts task history progress` or just `progress` consistently across
bank collection and pipeline resume. Both the initial forecast-bank command and
preflight are read-only with respect to model APIs unless execution is requested.

## What the experiment measures

The contribution is the paired, cross-agent admission rule in `admission.py`:
compare dispatch/reject on identical sampled future demand, account for quota
that cancellation cannot restore, subtract overhead, and constrain estimated
new deadline misses. The full/own comparison keeps forecasts, samples and the
risk guard fixed and changes whose latency enters the gain objective.

Forecast banks hold phase-entry probabilities with elapsed time fixed to zero.
Runtime timing distributions still use development history and elapsed progress.
They deliberately isolate predictor/context quality from new stochastic API
responses. Every simulated use charges saved inference latency, subject to the
total decision timeout, even when the response was cached during collection.
Bank collection records actual paid calls and costs; repeated replay incurs no
new provider charge. Adaptive live inference uses current state and is a separate
validation, not an identical frozen-prediction experiment.

Trace outcomes include final answer generation, candidate generation latency,
unused final candidates, no-search answers, exact reuse, required waits, and
inference overhead. Observed candidate generation is included in frozen think
time across replay policies. The rollout's chain endpoint remains an approximation
to full task completion; measured terminal answer time is used by the evaluator,
not leaked into policy forecasts.

The fixed candidate generator is a question/top-observed-title heuristic. It
meets the one-candidate/observed-state interface but does not reproduce a learned
candidate generator from Speculative Actions. All policies use the same recorded
candidates. Real results may show that reserves perform equally well or better.

## Outputs and interpretation

- `traces/tasks/`: atomic, checksummed per-task checkpoints and QA inference telemetry.
- `traces/development.json`, `evaluation.json`, `pilot.json`: replayable traces;
  pilot stays within development. Gold labels remain separate.
- `forecasts/*.json`: observed input, model/revision, probabilities, latency,
  token/cost telemetry, and held-out calibration. Runtime predictors remove labels.
- `study/frozen_config.json`: development tuning, source/data/bank hashes and seeds.
- `study/events.jsonl`, `outcomes.jsonl`, `runs.json`: auditable per-policy execution.
- `study/metric_comparisons.json`: paired confidence intervals for mean/p95 completion,
  mean/p95 waiting, deadline misses, unused calls and overhead, including full/own.
- `study/calibration.json`, `forecast_calibration.json`: Brier/ECE and bins.
- `study/sensitivity.png`, `sensitivity.pdf`: sensitivity plots when enabled.
- `reference.json`: privileged greedy development diagnostic, not an optimal bound.
- `live/`: independent live QA runs, answer EM/F1, quota checks and failure counts.
- `inference_summary.json`: actual request counts, failures, tokens and costs, including retained failed attempts and interrupted live runs. Unknown costs remain null.
- `REPORT.md`: generated summary, gains/regressions, caveats and artifact index.

Five paired seeds are the default. Bootstrap whole-seed aggregates to retain
within-run interference. The 12 settings are focused sensitivity tests, not a full
Cartesian sweep. Quota resets between batches. Independent live model answers
can vary; do not interpret live policy differences as paired causal effects.
The generated report is an experiment summary; the final course paper still
requires interpreting actual measurements and documenting limitations.

## Gateway ordering and reproducibility

`QUOTA_REQUIRED_ORDER=fifo` is the default. Set it to `progress` to prioritize
larger observed completed-call counts among queued required calls. Keep FIFO
for the main admission comparison; the study and live pipeline include separate
`progress_order` and `progress_current_capacity` controls.

Changes to the source, model configuration, trace files or bank contents require
a fresh experiment output. Credentials may be rotated without changing experiment
identity. A saved run from older source code is not resumable under this version.
Never compare historical `docs/` numbers against newly generated results.
