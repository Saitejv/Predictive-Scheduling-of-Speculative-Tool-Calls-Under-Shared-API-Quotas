# Experimental design

Use [RUNBOOK.md](RUNBOOK.md) for commands. Historical numerical artifacts under
`docs/` predate the correctness fixes; use newly generated study outputs.

## Data and information boundary

The source corpus has 1,991 HotpotQA documents and 200 scripted source trajectories,
split into 100 development and 100 evaluation task IDs. `collect_qa` preserves
those assignments before issuing model calls. Its pilot contains development
only. The collector sees the question and search results; answers and supporting
facts are validated before any paid requests and used only for scoring after collection; they never enter model inputs. All successful tasks,
including no-search answers and wrong answers, enter evaluation. A failed task
stops collection, is recorded, and must be retried; it is never silently dropped.

One fixed question/top-observed-title generator proposes at most one candidate
per step. Generation time is recorded. Incorrect-candidate execution durations
are benchmarked after the trajectory; their results never enter agent state.
Exact matches use the required call's recorded duration. Final model generation
and final unused candidates are retained. Quota waiting is excluded from recorded
service times; replay adds it under controlled schedules. Repeated identical
searches share results within each task in all replay policies.

## Admission comparison

Compare no speculation, current-capacity admission, tuned fixed reserve, recent
usage forecast reserve, full predictive admission and own-agent-only admission.
Required ordering is FIFO throughout this comparison. Separate progress-ordering controls prioritize completed-call count, both without speculation and with the same current-capacity candidates. The privileged greedy
reference uses development traces only in the pipeline; it is not an optimum.

Full/own policies use identical forecast sources and scenario seeds. Only the
gain objective changes; both retain the global deadline-risk guard. The full
rule sums projected chain-completion savings across observed agents, accounting
for shared quota and avoided required dispatches. These are bounded estimates,
not guaranteed deadline protection under arbitrary arrivals.

## Predictors and contexts

History fits only development trajectories. Jev and Kev supply conditional reuse,
next-search and continuation probabilities; empirical timing samples come from
the same development history. Reuse calibration scores the joint probability
`P(next search) * P(exact candidate | next search)`. Continuation calibration is
conditional on a next search actually occurring.

The five contexts are `task`, `history`, `progress`, `no_history`, `no_progress`.
`history` adds recent calls; `progress` adds completed count, phase, elapsed time
and bounded result excerpt. `no_history` removes the explicit call-history field;
`no_progress` removes only count/phase/elapsed, retaining the same result excerpt. Thus it differs from the history-only context. History may still be inferable
from other observed content; these are field-removal experiments.

Banks freeze phase-entry observed contexts (`elapsed=0`) and deduplicate identical
requests within each backend/context. No labels are sent to providers. Future
state probabilities are selected only after that state is observed. Runtime bank
predictors discard evaluation labels. Full/own comparisons reuse the same bank.
Saved inference latency is charged on every modeled call, capped by the total
per-decision budget; exceeding that budget rejects speculation. Mock latency is
not scientific model evidence and uses the development-frozen scheduler cost.
Actual bank collection token/cost telemetry is separate from modeled replay use.
The live gateway and adaptive CLI instead query models on actual current elapsed
progress. These experiments address different sources of variation and are labeled.

## Tuning and sensitivity

Tune reserve 0/1/2 and horizons of 1/3/10 base windows on four-agent development
batches. Measure scheduler p95 on five development batches and round up to
milliseconds, with a 1 ms minimum. Initial service duration estimates also come
from development. Save configuration, source hashes, data/corpus/bank hashes and
seeds before evaluating held-out outcomes. Frozen repeats reject changed sources,
inputs or forecast banks. Original traces remain loadable; older frozen study
configs must be regenerated because timing semantics changed.

The 12 settings cover concurrency 1/2/4/8, capacities 1/2/3/6, base window times
0.3/1/3, burst/staggered arrivals and probability inversion 0/.5/1. This is a
focused one-factor design, not a Cartesian grid. Staggered arrivals span one
window. Deadlines are four windows after arrival. All policies receive the same
trace batch and seed. Quota resets between independent batches.

Standalone scripted studies default to a .1-second base window. The LLM pipeline
defaults to 10 seconds; select a sensible value from the development pilot before
held-out analysis. Samples default to eight and predicted calls to four per active
agent. Use five paired seeds (7/17/27/37/47) for the main study.

## Metrics, intervals and artifacts

Primary metrics: mean/p95 completion and required queue wait. Completion includes
terminal answer generation. Service and joined execution affect latency, not
quota wait. Inclusive deadlines count exact-boundary completion as success.
Record speculative/unused calls, total dispatches, reuse, per-agent outcomes,
decision overhead, fallbacks, and inference telemetry. Unknown costs stay null.

`metric_comparisons.json` reports paired differences for mean/p95 completion,
mean/p95 wait, deadline misses, unused speculation and overhead. Comparators
include no speculation, full versus own, and history predictive versus fixed and
usage reserves. External predictors are also compared directly to history and reserves, context ablations to their full progress context, and Kev to Jev when both banks exist. The progress/current-capacity contrast isolates required ordering. Positive latency differences are regressions.
Bootstrap whole-seed aggregates with 2,000 resamples to preserve within-run shared
quota interference. Five seeds and one small corpus do not yield population
bounds for HotpotQA or general agent workloads. One-seed smoke-test intervals are
not substantive uncertainty estimates.

`runs.json`, per-task `outcomes.jsonl`, and `events.jsonl` allow inspection of
failures and aggregate claims. Calibration saves Brier/ECE and bins. The pipeline
writes a readable `REPORT.md` and optional sensitivity PNG/PDF figures. It does
not fabricate a completed research paper or favorable findings.

## Live validation

`quota_spec.live` is the existing scripted search fidelity check. The pipeline's
QA live stage runs actual main-model agents (or explicit mocks) through all core
admission policies and the selected predictors. It scores answer EM/F1, checks
fixed-window dispatch budgets and logs waiting, unused calls and inference errors. Live deadlines are four windows after each admitted task arrival, matching replay; deadline context reaches the risk guard. Cached required calls contribute zero wait, and failed optional calls still count as unused work.
Main-model and admission inference overlap; actions publish after both finish.

Live model runs are independent; answers and call sequences may differ. Use frozen
replay for paired causal policy comparisons and live runs for integration/quality
validation. Model API access, actual latency, cost and answer correctness can only
be measured after credentials/endpoints are available.
