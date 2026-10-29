# Experimental design and artifacts

> Review note (October 28, 2026): numerical results below are historical, from
> before the correctness review. Current code fixes progress tracking, forecast
> state, execution-duration leakage, deadline censoring, inference overhead and
> aggregation. Regenerate studies before using old numbers as current evidence.
> See [API setup](API_SETUP.md) and [review validation](REVIEW_VALIDATION.md).

## Workload

Use frozen `data/development.json` and `data/evaluation.json`: 100 original task
IDs each, split by ID hash. The 20-task pilot comes from development only. The
shared corpus contains 1,991 paragraphs from the first 200 HotpotQA distractor
validation examples. See `data/README.md` for attribution, source checksums and
scripted-agent limitations. The three-search retrieval harness uses no answers
or supporting-fact labels to generate queries/candidates.

Think and service times were measured during local search collection with
controlled 15/10 ms delays. Replay uses the saved timings identically across
policies. Mismatched candidate service time uses the required call's measured
latency estimate. Neither timings nor the first-200 subset represent production
agent workloads.

## Policies

| Policy | Current implementation |
| --- | --- |
| No speculation | Required FIFO baseline |
| Current capacity | Admit when no required queue and capacity remains |
| Fixed reserve | Reserve 0/1/2 tuned on development |
| Usage forecast | Recent observed required-call rate times remaining window duration |
| Predictive | Shared-scenario bounded cross-agent completion objective plus risk guard |
| Own-agent-only | Same forecasts, random seed and global risk guard, owner gain only |
| Progress ordering | Separate no-speculation control, more-completed-call count first |
| Future-informed reference | Privileged greedy full-trace pilot diagnostic |

The tuned fixed reserve can be zero, making it identical to current capacity.
The progress control is not an admission-policy comparison. No baseline is a
full reproduction of an external research system.

## Tuning and frozen evaluation

`python -m quota_spec.experiments` fits history on development only. It measures
scheduler wall time on five development batches and freezes a rounded-up p95
cost with a 1 ms minimum. It tunes reserve and a .1/.3/1 second horizon using
four-agent development batches, then writes `frozen_config.json` **before**
held-out evaluation. Fixed budgets are eight samples, four predicted calls per
active agent, and epsilon .05. `--frozen-config` reuses saved settings and seeds
with checksum validation; measured diagnostics may vary by host.

The focused grid has 12 settings: 1/2/4/8 agents, capacity 1/2/3/6, window
.03/.1/.3 seconds, burst/staggered arrival, and probability inversion error
0/.5/1. This is a one-factor sensitivity design around four agents and quota
3 per .1 second, not the full Cartesian product. A probability error of .5
flattens reuse forecasts to .5; error 1 inverts them. Timing forecasts remain
fixed. All policies receive identical recorded candidates.

Each seed shuffles tasks into bounded batches of at most N simultaneous agents.
Quota/registry reset between independent batches. Staggered arrivals spread
within a quota window. Controlled deadlines are four windows after arrival.
Seeds 7/17/27/37/47 are paired across policies. Aggregates use all 100 evaluation
tasks per seed; raw per-task data retain partial final batches.

## Metrics and uncertainty

Primary metrics are mean/p95 completion and required quota-queue wait. Task
completion is finish minus arrival. Tool execution and remaining joined execution
count toward latency, not quota waiting. p95 is nearest rank. Exact cached and
in-flight reuse have no quota wait. Deadlines are inclusive. Record unused
speculation, dispatch count, per-agent waiting, inference diagnostics and overhead.

Paired differences subtract the no-speculation seed aggregate. Bootstrap whole
seed aggregates (2,000 resamples), preserving interference within each shared-quota
run. Report 95% percentile intervals and every positive mean delta as a regression.
Only five seeds and one frozen small workload are used. These intervals quantify
this experiment's ordering/sampling variation; they are not population confidence
bounds for HotpotQA or general agents. Zero-width intervals can arise for the
deterministic single-agent controls.

History calibration scores candidate reuse using held-out labels in the evaluator
only. Report Brier score, expected calibration error and bin counts. External-model
calibration and context comparisons require live Jev/Kev access and remain absent.

## Live validation

`python -m quota_spec.live` runs 12 scripted retrieval agents with concurrency
capped at four and a shared quota of three dispatches per .1 second. It verifies
that all policies produce identical required queries/results, checks every fixed
window, and reports measured gateway completion alongside replay estimates.
It also computes supporting-title recall from separate labels. This does not
measure generated-answer correctness; `answer_exact_match` is null. A main-model
QA experiment remains necessary.

## Reproducibility artifacts

The CLI saves trace/config/history, per-policy JSONL events, metrics and external
inference records when applicable. The study saves frozen configuration with
source hashes, dataset/corpus hashes, Git revision (null in an unborn repository)
and dirty status, seeds, tuning scores, `events.jsonl`, `outcomes.jsonl`,
`runs.json`, `comparisons.json`, `calibration.json`, and PNG/PDF sensitivity plots.
The live harness saves full required outputs, event logs and summary. The access
audit records missing integrations with null measurements. Generated `results/`
are ignored; the frozen data and source are retained in the repository.

Validation gates cover quota accounting/refill boundaries, atomic exact reuse,
client and execution cancellation, failed speculative results, FIFO at refill
boundaries, dependencies, no future observations, bounded/timeout adapter
contracts, prediction errors, horizon boundaries, and paired cross-agent harm.
Run the complete suite before regenerating experiments.
