> Current checkpoint: complete 50-question version 2 capture, finite bank
> completion and basic shared-quota replay are implemented. See
> [CAPTURE_RESULTS_2026-11-12.md](CAPTURE_RESULTS_2026-11-12.md) and
> [CAPTURE_REPLAY.md](CAPTURE_REPLAY.md). This document retains the original plan;
> Jev/Kev forecast integration and the live multi-agent check remain open.

# Codebase decision and frozen-output replay plan

Prepared November 12, 2026. This is a plan, not an implemented replay feature.
No additional inference is needed to audit and package the existing recordings.

## Which codebase produced the results?

The latest 6.659 s sequential / 5.975 s speculative latency result came from
**our concurrent runtime in this repository**, using the authors' workload
components. The earlier direct agreement experiment called the authors'
original serial runner. These are distinct execution drivers.

| Component | Source in latest live run |
| --- | --- |
| ReAct instructions, six examples, observation/action prompts | Authors' pinned files |
| Action extraction and thought/action parsing | Authors' `HotPotQARun` methods |
| Wikipedia Search and local Lookup/Finish behavior | Authors' `WikiEnv`; Search results applied by our adapter |
| HotpotQA dataset and intended seed-248 question order | Authors' dataset and sampling convention |
| Answer normalization and F1 | Authors' wrapper functions |
| Async episode loop, speculation windows, cache/in-flight joining | Our `hotpot_runtime.py` |
| OpenRouter transport, concurrent budgets, logging, paired metrics | Our code |
| Shared quotas, admission, multi-agent replay, Jev integration | Our existing project modules; not used in the latest live run |

`paper.load_upstream` imports the authors' source directly from a checksummed
download at revision `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c`. The full clone
under `tmp/speculative-action-upstream/` remains pristine at the same revision.
We have not created a GitHub fork. Our latest loop does not call the original
`webthink` driver; it reuses its parser and environment components.

**Recommended foundation:** keep this repository as the primary implementation
for the project, with the authors' code pinned as an attributed reference
dependency. Keep the original-runner check as a regression reference. Extend
the current runtime, trace format and replay/admission modules rather than
replace them with the upstream serial evaluator. A GitHub fork can be made
later if desired; it does not supply the missing replay/capture machinery.

The latest run used `google/gemini-2.5-flash` for both actor and observation
prediction. The actor had a 1,000-token cap; observation prediction had a
100-token cap. These were different roles/settings of the same model, not
an actual large/small model pairing. The hypothetical actor also used Gemini.
Jev is a later demand predictor, not this observation speculator.

## What we already saved

All of the latest run's model outputs are retained in
`results/hotpot-live-paired-20/`:

| Artifact | Contents |
| --- | --- |
| `requests.jsonl` | 296 exact model request payloads and raw responses |
| `inference.jsonl` | Request IDs, episode/step/role, durations, tokens, provider and billed costs |
| `events.jsonl` | 1,299 timestamped events, including model/search starts and completions, candidate readiness and answer readiness |
| `tasks/` | 40 episodes with authoritative thoughts, actions, observations, final answers and QA outcomes |
| `config.json` | Model settings, indices, upstream manifest and runtime source hashes |

The exact paid source snapshot and settled account audit are under
`results/hotpot-live-audit/`. Existing outputs can already be inspected and
rescored without inference. They are not yet a complete counterfactual replay
dataset.

The missing pieces are explicit node/dependency IDs, immutable before/after
tool state, complete Search result payloads (including unused prefetches),
and predictions/candidate outputs for windows that were skipped or stopped
early. Search completion events currently store timings rather than full
page/result state. The existing replay adapter also reduces each step to one
candidate, while the live run allowed up to three; silently dropping two is
not a faithful conversion.

## Capture boundaries

Treat these as asynchronous events, not synchronization barriers:

1. **Authoritative actor completes:** save its exact input/output, parsed
   thought/action, model configuration and duration; make the required call ready.
2. **Required Search starts:** save pre-tool state and dependencies. Start the
   real Search and observation predictor in parallel when eligible.
3. **Observation predictor completes:** save provisional text and duration.
   Run the hypothetical actor on that branch-local input.
4. **Hypothetical actor completes:** save the entire ranked candidate list,
   raw response and duration. Each candidate becomes an independent optional
   tool node that a scheduler can admit or reject.
5. **Tool completes / next true actor completes:** save the full real tool
   result and state transition, plus the true next action. Verify exact
   prefetch reuse, misses and in-flight joins without substituting provisional
   content into authoritative state.

Each node needs run/task/agent/step/branch IDs; dependency edges; readiness,
submission and completion timestamps; request and state hashes; output blob
references; cost/tokens; success/error/truncation; and candidate rank where
applicable. Service time must be separate from queue/admission waiting.

Store full WikiEnv page/observation/result-title state and lookup cursor data
as immutable blobs or snapshots, including results from wrong prefetches.
Credentials stay outside captures. Preserve the upstream revision/license and
hash the manifest and blobs. Request identity must include exact inputs and
model settings; a shared step number is not sufficient to reuse a response.

## Ordered implementation plan

### 1. Package existing evidence and declare the canonical tapes

Inventory/hash the current files and join the existing records by request ID,
episode and step. Export a stage graph with an explicit coverage report for
missing states/results/branches. Preserve all raw files.

For the first scheduling dataset, use all 20 speculative episodes' authoritative
trajectories because their recorded predictions belong to those same histories.
Retain the 20 independent sequential episodes as separate live evidence. Do
not transplant predictions between modes merely because question/step IDs
match: their prompts and trajectories frequently differ.

The resulting fixed tapes hold true actor outputs and final QA outcomes fixed
across scheduler policies. A no-speculation replay of those tapes is a new
matched control; it is not the independently sampled live sequential run.

**Acceptance:** every saved request is accounted for, stage edges are valid,
and every absent output is explicitly marked rather than fabricated.

### 2. Add complete stage capture before another paid benchmark

Add a versioned recorder and blob store to the current runtime. Preserve all
three candidates and actual tool result/state payloads. Repeated identical
prompts can have different stochastic responses, so retain node/attempt
identity instead of collapsing recordings into a single global response.

Add a separate bank-completion mode that fills missing predictions, hypothetical
actor outputs and candidate tool results for every eligible boundary on the
chosen authoritative tapes, even when the original live policy skipped a
window because it was late or a cache hit. This collection uses only the
frozen information available at the original decision boundary. Run it outside
the latency benchmark so extra collection work does not distort that benchmark.
List missing requests and expected cost before any further paid collection.

This fills a finite set of scheduling alternatives on fixed trajectories. It
does not attempt to precompute every possible newly generated agent history.

**Acceptance:** stateful Lookup can resume from a saved snapshot; unused and
used prefetches both have complete results; missing nodes produce explicit
cache misses; replay never silently invokes a model or Wikipedia.

### 3. Validate single-agent replay before changing scheduling

Implement two modes using the same tapes: a timed offline execution that feeds
recorded outputs to the runtime, and discrete-event replay that advances virtual
time without sleeping. Consume recorded model service times, local processing,
tool times and drain work; recompute readiness from dependency completion.

First reproduce the recorded schedule and its three useful cache hits, answers,
late windows and resource drain. Report residual timing differences with an
explicit tolerance for recorded logging/processing overhead. Then compare
sequential and speculative scheduling on identical complete tapes.

**Acceptance:** socket/model calls are blocked; answers and required action
sequences are identical by construction across policies; timing and costs are
reproducible from a seed; no candidate is available before its dependencies.

Fixed-trace QA invariance is a property of this scheduling experiment. It is
not independent evidence that a changed prompt/model preserves answer quality.

### 4. Extend the existing replay engine to 1/2/4/8 agents

Reuse `replay.py`, quota accounting, exact-call registry, policies and admission
simulation. Extend the trace/event interface to represent multiple candidates,
persistent per-agent prefetches and trigger dependencies faithfully; do not
flatten the latest run into the old one-candidate schema.

Interleave the frozen agent graphs using controlled arrivals and one shared
fixed-window Search quota. Recompute future readiness when an agent waits,
joins a call or reuses a result. Shift relative event dependencies, not copied
absolute wall-clock timestamps. Each policy receives the same tapes, candidates,
tool durations, arrivals and random seeds.

Start with no speculation, current-capacity admission, fixed reserve and history
forecasting. Include the existing full versus own-agent-only admission ablation
with required-call ordering held fixed. Search alone spends shared quota;
Lookup/Finish stay local. Cancellation does not refund consumed quota.

**Acceptance:** one-agent no-quota replay agrees with step 3; quota invariants
hold; no held-out future information reaches policies; multi-agent results
include actual active-agent counts and per-agent waiting/fairness.

### 5. Freeze Jev forecasts, then test the proposed contribution

Keep observation speculation and Jev demand forecasting as separate stages.
Create/cache Jev responses once for declared, observed decision contexts,
using exact context/model/settings hashes. Reuse the existing forecast-bank
machinery where its context assumptions apply.

The current bank deliberately uses phase-entry contexts with `elapsed=0`.
Label that approximation. If we add elapsed-time buckets or richer global
context, define and populate that new context coverage explicitly; a response
for a different simulated state is not interchangeable. An uncovered context
must stop or use a separately declared fallback, never an unnoticed inference
call or a future-aware answer.

With those forecasts held fixed, compare full cross-agent admission against
the same rule ignoring delay to other agents. Replay predictor latency and
logical usage even though cached forecasts no longer incur new API charges.
Use development traces for tuning; the already explored 20 questions are a
pilot, not fresh held-out evidence. Expand to the proposal's larger disjoint
development/evaluation set only after the capture/replay gates pass.

**Acceptance:** scheduler comparisons do not pay for new model calls; the
global/own-only pair shares forecasts and inputs; neutral or negative outcomes
are retained.

### 6. Validate simulation assumptions with a small live check

Report mean/p95 completion time, makespan/throughput, required-call waiting,
deadline completion, wasted calls, fairness and predictor overhead. Separate
one-time paid collection cost from logical per-policy inference/tool cost.
Clearly state whether model service capacity is unlimited or queued in the
simulation: fixed single-agent latencies do not establish real provider latency
under multi-agent load.

Use a small live multi-agent experiment after replay stabilizes to check quota
semantics, contention, exact reuse and answer correctness. Live results validate
the simulator; replay supports inexpensive controlled scheduling sweeps.

## Completed existing-recording export

The baseline was simplified and `quota_spec.stage_export` now accounts for all
296 requests, 1,299 events and 40 episodes, with complete recorded ranks and
explicit replay gaps. See [STAGE_EXPORT.md](STAGE_EXPORT.md) and the current
[root handoff](../next_steps.md). The retained paid inputs remain unchanged.

## Immediate next deliverable

Build the versioned complete stage/result/state recorder and validate a
network-blocked one-agent replay. The exporter is complete; its gaps must remain
explicit until a separately declared bank-completion mode supplies needed
alternatives. Only then compare matched single-agent schedules and proceed to
the shared-quota multi-agent/Jev experiment.
