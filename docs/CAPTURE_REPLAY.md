# Complete HotpotQA capture and frozen scheduling

The active runtime now records complete stages by default. It keeps the pinned
upstream prompts/parser and authoritative state semantics. No Jev/Kev inference
is part of collection. Both actor and observation predictor still default to
Gemini 2.5 Flash; hypothetical reasoning uses the actor model.

## Collect, audit, and complete alternatives

```sh
make offline OUTPUT=results/capture-smoke-fresh
.venv/bin/python -m quota_spec.capture_audit results/capture-smoke-fresh

# Paid paired collection; explicit output, budgets and request pacing.
make live COUNT=20 OUTPUT=results/capture-live-fresh
.venv/bin/python -m quota_spec.capture_audit results/capture-live-fresh

# Inspect missing model windows before requesting completion.
.venv/bin/python -m quota_spec.capture_bank results/capture-live-fresh --plan
.venv/bin/python -m quota_spec.capture_bank results/capture-live-fresh \
  --backend http --max-usd .50 --max-requests 600 \
  --output results/capture-bank-fresh
```

To extend the same seeded workload from 20 to 50, collect `--offset 20 --count 30`.
`workload_indices(50)` has the original 20 questions as its prefix. The serial
paper reference retains its separate 20-task API. Collection runs each question
in both sequential and speculative modes; canonical scheduling tapes use only
speculative histories, with sequential runs retained as independent live evidence.

Source snapshots, config, raw requests/usage, events, trajectories and summary
remain in each live directory. `capture/` contains version 2 immutable JSON
blobs, stage nodes, a start journal, step references and a checksum manifest.
Every model attempt is distinct, even when its exact payload repeats. Full
Search results and worker state are saved for used and unused prefetches.
Authoritative before/after state includes page, observation, result titles,
lookup keyword/list/cursor, steps, answer and tool counters. Lookup/Finish remain
local and authoritative. State snapshots preserve absent attributes separately
from null values.

Each stage records dependencies, agent/episode/step/branch/attempt identity,
ready/start/end timestamps, service and local queue duration, errors and output
references. Actual transport payloads/settings and raw responses, tokens, costs,
provider identity and finish reason link to the model node. Secrets and
Authorization headers are excluded. Unknown paid cost stops collection.

Requests default to a 180-second timeout. The live Make target uses 1.1 seconds
between submissions to reduce upstream rate-limit errors. This is a collection
regulator, not a latency optimization. Queue time, actual elapsed generation
span, and HTTP service duration are recorded separately. HTTP service includes
network/provider waiting; it is not pure model compute time. The simulator uses
measured model service plus parsing and excludes local collection pacing.

## Validation and fixed data

The audit verifies blob integrity, graph dependencies and timing, every captured
paid request, and authoritative prompt ancestry. With sockets blocked, it restores
each WikiEnv snapshot, re-executes Search application or local Lookup/Finish,
reparses saved actor outputs through the pinned parser and checks states,
observations and answers. It reconstructs the observed dependency schedule using
measured per-edge dispatch/processing lags (tolerance 1 microsecond). That check
validates the recorded schedule; counterfactual scheduling uses the completed
tapes instead of original absolute timestamps.

Live capture alone is not a complete scheduling bank: cache hits and late
predictions may skip model branches, and unlaunched candidates have no results.
Bank completion uses only the saved pre-tool prefix/action for each missing
window. It retains existing observation/hypothetical outputs, including late ones,
then collects only missing branches and exact-query Search results. It never
transplants model outputs between independently generated prompt histories.
Completion runs outside live timing and reports its separate usage/cost.

A completed bank contains `tapes.json`, both verified capture stores, all ranked
candidates and tool-result references, label-blind `forecast-cases.json`, separate
`forecast-labels.json`, and `dataset-manifest.json`. Missing results are errors;
replay has no online fallback. Wikipedia results are frozen per exact query
within an episode. Reusing a later collected result as a counterfactual tool
sample assumes that frozen environment; no future result enters predictor inputs.

## Shared quota simulation

```sh
.venv/bin/python -m quota_spec.frozen_replay results/capture-bank-fresh \
  --agents 1 2 4 8 --capacity 3 --window-s 10 \
  --output results/frozen-study-fresh
```

`FrozenReplay` uses existing `FixedWindowQuota` and policy/model interfaces,
while supporting every candidate rank and dependency-triggered prediction.
Required Search dispatch opens prediction in parallel. Observation and hypothetical
stages retain their measured durations. The next true action closes the window;
late branches never launch Search. Exact per-agent cache hits can join in-flight
work. Only Search consumes quota, and completion/cancellation does not refund it.
Required work keeps FIFO priority. Policies see observed progress and completed
results, not future tape outputs or actual unfinished service times.

The initial study compares no speculation, current capacity and fixed reserve.
Each policy gets the same tapes, measured durations and question permutation.
A continuous pool of 1/2/4/8 workers takes questions from that queue; a worker
starts its next question after the previous question drains all started work.
One quota persists across the entire question stream, without resets between
questions. This is a closed-loop workload, so actual start times depend on each
policy's completions. Model concurrency is assumed unlimited with fixed single-agent
HTTP durations. This is not a measurement of provider serving capacity.

Reports include answer completion, resource drain, throughput, quota waiting,
wasted Search calls, exact/in-flight hits, per-agent timing and fairness. Answer
outputs are held fixed by construction, so unchanged answers are not new QA
quality evidence. `--tool-duration-s 1.0` provides a declared synthetic duration
sensitivity check; measured Search durations are the default. Results are
exploratory and not yet a Jev/Kev or cross-agent admission evaluation.

## Prepare Jev/Kev inputs

```sh
.venv/bin/python -m quota_spec.frozen_forecasts results/capture-bank-fresh \
  --development-count 20 --output results/predictor-inputs-fresh
```

Use a dataset larger than 20 for this split. The command prepares all five existing
context modes through `prediction.bounded_context`, with exact context hashes,
candidate ranks and disjoint task IDs. Demand contexts cover thinking/queued/running
phases; reuse contexts belong to individual ranked suggestions. Inputs contain
only question, observed progress/history, prior observations and the known
candidate. Answers and future required searches remain outside input files.

This deliberately retains the existing bank's **phase-entry `elapsed=0`**
approximation. Before adaptive elapsed-time forecasts, explicitly extend context
coverage. Freeze Jev/Kev `Forecast` outputs once with exact model/config/context
identity, measured inference latency, tokens and cost. The existing
`JevPredictor`/`KevPredictor` interface and `PredictiveAdmission` full/own-agent
ablation are the next integration point. A missing context must never trigger
unnoticed inference during replay. Predictor access/serving must be validated
before claiming those comparisons are complete.

The original 20 explored questions are development/pilot material. The added 30
are a larger exploratory sample, not a fresh confirmation set after tuning.
Keep development-only history fitting and tuning separate from evaluation.

## Partial runs and provenance

A timeout or upstream 429 preserves every started request and stops spending
when cost is unknown. Never overwrite that directory. Select only fully captured,
successful pairs into a derived directory, audit them, then collect the remaining
seeded indices:

```sh
.venv/bin/python -m quota_spec.capture_cohort select results/interrupted-run \
  --output results/complete-pairs
.venv/bin/python -m quota_spec.capture_audit results/complete-pairs
```

The original partial run retains failed attempts and their cost uncertainty.
After completing disjoint bank shards, merge them with
`quota_spec.capture_cohort merge <bank-a> <bank-b> --output <fresh-dataset>`.
Merged tapes name their shard so stage IDs remain unambiguous. Manifests hash
all nested parts; no question may appear in more than one shard.
