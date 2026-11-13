> Historical extension documentation. Use [the active baseline](../README.md) first.

# Run the complete project

For the current research experiment use [PAPER_PIPELINE.md](PAPER_PIPELINE.md):
the upstream ReAct/Wikipedia workload plus our shared-quota controller. The
local-BM25 workflow below is retained as a legacy integration harness.

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
| Small Speculator | `SPECULATOR_CHAT_URL`, `SPECULATOR_MODEL`, and `SPECULATOR_API_KEY` if required | Propose one exact search or abstain |
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
small live pilot. Offline verification itself never authenticates an account.

For OpenRouter, both chat URLs are `https://openrouter.ai/api/v1/chat/completions`.
Use `QA_MODEL=deepseek/deepseek-v4.1-flash` and
`SPECULATOR_MODEL=openai/gpt-oss-120b`, with the same OpenRouter key in each
credential variable. Set `JEV_BASE_URL=https://openrouter.ai/api/alpha`,
`JEV_MODEL=typesafe/jev-1.14`, and `TYPESAFE_API_KEY` to the OpenRouter key.
The adapter appends `/decisions` to an `/alpha` base; native System One URLs
continue to work. Use `--predictors history jev` to omit Kev.

Optional `QA_REASONING_EFFORT` and `SPECULATOR_REASONING_EFFORT` set the
OpenRouter reasoning effort (the pilot uses `low`). Reasoning tokens share the
output cap: the pilot uses 4096 QA tokens and 512 Speculator tokens.
Set both `*_RESPONSE_FORMAT=json_object` for JSON mode and
`SPECULATOR_PROVIDER_SORT=latency` to prefer low latency routing. Supported sorts
are `latency`, `throughput`, and `price`; these are routing preferences, not
latency guarantees. These options are included in resume identity.
Returned `usage.cost` is the billed cost and overrides configured price estimates.

The default `--candidate-backend auto` uses the HTTP Speculator with HTTP QA and
an explicitly synthetic fixture with mock QA. Configure its complete
chat-completions URL independently from the main model and select a small model.
It receives only the question and up to four observed search histories (three
bounded documents each). It returns `{"action":"search","query":"..."}` or
`{"action":"skip"}`. It never sees the main model's pending action or gold labels.
Its proposal goes to the existing quota controller; Jev/Kev estimate demand/reuse
and do not generate the search query.

`SPECULATOR_TIMEOUT_S` defaults to 2, `SPECULATOR_MAX_OUTPUT_TOKENS` to 128, and
`SPECULATOR_TOKEN_PARAMETER` to `max_tokens`. Set the latter to
`max_completion_tokens` if needed. `SPECULATOR_INPUT_USD_PER_MILLION` and
`SPECULATOR_OUTPUT_USD_PER_MILLION` control its separate cost accounting.
Missing configuration fails before any paid QA request. Runtime timeout/schema
failures produce no candidate, preserve required QA behavior, and remain in
Speculator telemetry; the live pipeline flags these failures for inspection.
Successful QA checkpoints retain failed proposals on resume. Use a fresh
collection to repeat those proposals.

Main QA and the Speculator start together. Only a proposal returned before the
main JSON action is ready can be admitted. A pending draft is cancelled when the
main action completes; admission also runs in parallel and never blocks required
searches. Cancellation closes the local request and may still incur provider cost.
Such records are marked `cancelled`, separately from errors, and charges remain
unknown when no usage response was received. This harness consumes complete JSON
actions; it does not stop on the first streamed token.

Use `--candidate-backend heuristic` for an explicit comparison with the original
question/top-title generator. Use the same model, workload and scheduling
settings in separate output directories when comparing candidate sources.

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
# Main QA model + small Speculator + history needs no Jev/Kev access.
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
or the live stage. The Speculator makes at most `count * max_calls` additional
collection requests (600 at defaults), plus `live_count * max_calls` per live
policy. No proposal is requested after the observed search budget is exhausted.
Use staged execution below for an exact bank request preview.

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

The small Speculator and main QA inference start together from the same observed
history. `candidate_delay_s` records proposal availability; `think_s` includes the
barrier at the later completion of the two models. This also charges latency for
abstentions and failed proposals. Live QA uses the same barrier, then waits for
admission before publishing the required action. All replay policies, including
no speculation, share the frozen candidates and generation overhead to isolate
admission effects. This comparison does not measure the cost of removing the
Speculator entirely. Separate telemetry records actual proposal requests/tokens/costs.
The proposer is not a trained reproduction of Speculative Actions. Real results
may show that reserves perform equally well or better.

## Outputs and interpretation

- `traces/tasks/`: atomic, checksummed per-task checkpoints with QA and Speculator telemetry.
- `traces/speculator-inference.jsonl`, `live/*-speculator-inference.jsonl`: separate proposal usage, failures and latency.
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
