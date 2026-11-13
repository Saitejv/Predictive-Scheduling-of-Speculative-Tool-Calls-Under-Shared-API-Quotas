# Next steps: simplify the baseline, then build the project extension

Last updated: November 13, 2026.

**Read this file first when resuming this project after a usage/session reset.**
This is the main implementation handoff. It describes the desired clean starting
point, the code and evidence to preserve, and the order of future work. The
baseline cleanup, complete capture, bank completion, Jev integration and exact
shared-quota gate analysis are complete. Kev remains deferred per the user.

All paths below are relative to the project root.

## Current checkpoint: original single-agent baseline repaired (November 13)

Read `docs/SINGLE_AGENT_BASELINE_REPAIR_2026-11-13.md` first. The previous simple
agent-count table was a shared-quota/common-cache extension, not a reproduction
of the original single-agent experiment.

- Found and fixed a benchmark-entry-point bug: `make live` hard-coded a shared
  1.1-second model submission interval, making optional inference delay the true
  actor. `make live` is now unpaced. `make capture` explicitly retains pacing.
  `--purpose benchmark` rejects positive HTTP submission intervals before any
  paid call or output creation; capture requires explicit `--purpose capture`.
- Read the actual upstream code and paper. The public five chess samples recover
  19.5416% mean time savings with the authors' original analysis, independently
  matched by a two-call overlap recurrence. HotpotQA Figure 4 evaluates action
  agreement, not that chess latency result. Keep those workloads separate.
- `quota_spec.single_agent_reference` runs the actual async HotpotQA Runtime
  against exact saved model prompts/responses and tool results using an asyncio
  service-time clock. All 100 task/mode checks match the quota-free scheduler and
  independent recurrence exactly, including result reuse and outstanding work.
  Fixed-path native mean is 8.902 → 8.749 s; generation averages 1.855 s versus
  0.707 s/Search. There is no missing prefetch overlap in these checked paths.
- Primary paper-style baseline: one agent, no Search quota, no Jev, no artificial
  pacing, original speculative-result cache. Common-required-result caching is
  a separate ablation, not a silent replacement for Algorithm 1's baseline.
- No new paid calls. Existing paid data, original checkout and historical output
  remain unchanged. Fresh evidence: `results/upstream-speculation-repair-2026-11-13/`.

## Historical checkpoint: independent timing and latency audit (November 13)

Read `docs/INDEPENDENT_SPECULATION_AUDIT_2026-11-13.md` and
`docs/INDEPENDENT_LATENCY_TABLES_2026-11-13.md` before interpreting the older
performance checkpoints. This audit supersedes their attribution of gains.

- No scheduler timing/overlap/quota arithmetic error was found in the audited
  cases. Both quoted original-cache scenarios reproduce exactly. However, the
  original engine caches speculative results and discards ordinary required
  results: the 6.32% gain at 2 workers, 6/60 s disappears under a common cache.
  No-speculation time becomes 845.767 s; the exact pipeline optimum is also
  845.767 s. This is a cache/control confound, not a 6.32% pure overlap gain.
- Matched-cache, no-quota eval30: perfect next-Search prediction with measured
  generation saves 1.47% native answer latency, then 5.95%/16.15%/23.85% at
  synthetic 2×/5×/10× Search durations. Original-window recorded-gate bounds
  are 1.20%/3.65%/8.19%/11.43%. Zero-generation and stronger full-lookahead
  references are separate; an eager zero-overhead quota policy is not a global
  upper bound. Do not call a recorded-candidate gate a perfect-predictor ceiling.
- 19,200 main policy executions cover 8 durations, 5 quotas, 1/2/4/8 workers,
  both release rules and retention controls; 1,728 repeated-stream diagnostics
  separate finite tails from 300-instance throughput. Native original-window
  global gates and all per-task no-quota bounds are exact; larger synthetic
  global gates are explicitly best-found, not exact optima.
- `FrozenReplay` adds opt-in required-result caching and generation on reuse;
  defaults retain old behavior. All started work remains charged under answer
  release. A separate full-generation perfect predictor also charges terminal
  windows that predict no further Search. Saved Jev probabilities/latency stay
  native-frozen; only development timing distributions follow synthetic tools.
- 216 tests and lint/format pass. Independent recurrences match exactly; 384
  old/new complete schedules are identical with new options disabled. All
  7,239 protected files are unchanged. No new paid inference; Jev only.
- Fresh evidence: `results/independent-speculation-audit-2026-11-13/`; scripts
  and full reproduction commands are linked from the report. Prior paid data
  and historical result directories remain intact.

Cache-matched comparisons isolate overlap; original-paper comparisons must also
retain the original cache policy as their primary baseline. Label release rules
and predictor lookahead/generation costs explicitly. Current Jev
does not consistently capture available quota opportunity; the old 6.32% example
is no longer an appropriate missed-opportunity target after cache matching.
Kev remains deferred; no live validation or new paid calls were made.

## Historical checkpoint: exact global gate analysis (November 13)

Read `docs/FULL_GATE_ANALYSIS_2026-11-13.md` and its two table appendices first.
This supersedes performance interpretation in the older checkpoints below.

- Same main-agent messages/results/service durations under every gate. Main:
  21 quotas × four worker counts × three orders; extended lifetime: five quotas
  × four worker counts × three orders. Total 4,248 policy runs and 749,568 exact
  counterfactual schedules, with every useful candidate subset enumerated.
- All-50 no-quota answer time: 8.902 → 8.749 s (1.71%) with original lifetime;
  8.664 s (2.67%) with one extra action or whole-episode retention. Native tool
  timings only. An independent recurrence matches all 100 task/mode checks.
- Current all-agent Jev's best original-window throughput gain is 0.21%, with
  zero useful hits; no broad predictive throughput win. A perfect Search gate
  reaches 6.32% at six calls/60 s with two workers by selecting only question
  6031's step-2 rank-1 candidate and avoiding a refill boundary. Gate optimum is
  conditional on recorded candidates, declared lifetime, no-unused Search,
  FIFO required calls and immediate optional dispatch, not arbitrary scheduling.
- More candidate lifetime increases quota harm: at 12 calls/30 s, two workers,
  extended ungated loses 38.34%, Jev loses 14.59%, perfect pipeline gains 0.82%.
  Separate answer-latency and full resource-throughput optima are retained.
- Source: `perfect_gate.py`, `gate_study.py`, `gate_lifetime_study.py`;
  `scripts/audit_gate_study.py` and `scripts/report_gate_study.py` regenerate
  arithmetic, evidence checks and charts. Results are in
  `results/full-gate-analysis-2026-11-13/` and
  `results/full-gate-analysis-extended-2026-11-13/`.
- 203 tests pass, lint/format pass. Prior capture/data and Jev evidence checksums
  match (14,816 + 40 + 27 files). No new inference or model spend in this work.

**Next research target:** a generation screen plus deadline-aware quota admission,
using time to refill and competing required demand. Tune on development data;
beat both no speculation and the tuned reserve. Use the 6031 reset opportunity
and extended-lifetime harm schedules as concrete targets. Confirm on a fresh
paired live cohort before claiming a general runtime speedup. User authorized
Jev only; do not provision Kev without new direction. Preserve all paid evidence.

## Current checkpoint: speedup discrepancy audited (November 13)

Read `docs/SPECULATION_DISCREPANCY_2026-11-13.md` before interpreting the strategy
charts or starting another performance run. The user correctly questioned why
those charts did not resemble the earlier live speedup.

- The old chart's baseline was a **prefetch-disabled counterfactual on the saved
  speculative actor paths**, not the original live sequential run. Chart labels
  now say fixed-path service-time replay and numerical quotas; no "loose" label
  is assumed. Pre-correction figures/scripts are preserved in the audit folder.
- Original live 20 pairs: **6.659 -> 5.975 s** (10.27% observed, paired interval
  includes zero). New same-path all-50 no-quota control: **8.902 -> 8.749 s**
  (1.71% modeled). These are different comparisons, not a replication failure.
- **43 later capture pairs added shared 1.1 s model-request submission pacing.**
  Local actor queueing totals are 16.555 s sequential versus 190.659 s speculative.
  Another 150-second actor outlier occurs only on the later speculative path.
  These account for nearly all the later live capture's much larger wall time.
  Its raw wall times are not an unpaced baseline replication.
- An independent serial timing recurrence agrees with all 100 task/mode unlimited-
  quota engine checks, with zero completion residual and identical hits. It finds
  16 hits and 7.630 total answer seconds saved on the all-50 frozen paths.
  There is no evidence of missing prefetch overlap in this checked schedule.
- The original live run logged only 1.934 s of useful prefetch overlap despite
  13.684 s of aggregate answer-time difference. Independent actions/service
  durations and provider variability prevent assigning all 10.27% to speculation.
- New runtime/config/summary outputs identify shared model submission pacing.
  Offline reports infer it for old configurations and prominently warn when
  paced. Original raw summaries still regenerate exactly; paid evidence is
  unchanged. No model settings, pacing policy or paid behavior were changed.
- **196 tests pass**, Ruff lint/format pass. There were no new paid requests.
  `speculation_audit.py` and `scripts/plot_speculation_reconciliation.py`
  reproduce the audit. Results are in
  `results/speculation-discrepancy-audit-2026-11-13/`.

**Next performance gate:** distinguish original live benchmark, paced capture,
fixed-path replay and artificial tool-delay regimes. Use an explicitly verified
nonbinding Search quota as a control, and repeat actual paired live measurements
with a declared consistent model submission regime before extending claims about
real speculation or Jev throughput. Existing Jev sweeps remain conditional
scheduling experiments on the completed frozen bank, not live speedup results.

## Current checkpoint: asynchronous gating and persistence tested

See `docs/JEV_ASYNC_RESULTS_2026-11-12.md` for the latest follow-up. The user asked
whether Jev could keep gating after the main actor resumes. It already overlapped
that actor; windows expired when the actor returned its next action. We now also
support one additional returned-action lifetime and an explicit nonblocking
admission objective. All defaults preserve the original scheduling behavior.

- `AdmissionConfig(nonblocking=True)` leaves authoritative demand readiness
  independent of Jev, charges measured latency through delayed optional launch,
  and removes the extra flat inference-latency hurdle. No inference is free.
- `FrozenReplay` supports bounded candidate persistence, duplicate suppression,
  quota/reset revalidation, a reserve before optional generation, and optional
  worker release at answer with background work fully accounted for.
- `results/hotpot-jev-persistent-progress-50/` holds **1,885 exact forecasts**:
  1,186 reused and 699 new successful Jev contexts. Incremental provider-reported
  cost was **$0.019654908**. No additional Kev work was performed.
- **7,098 new replays**: 6,000 native, 756 synthetic slow-Search, 216 early-budget
  comparisons and 126 longer-stream diagnostics (300 repeated tape instances).
  `async_study.py`, `scripts/run_async_stream.py` and
  `scripts/report_async_study.py` reproduce these studies without network calls.
- Correct overlap alone changes aggregate multi-agent native throughput by
  **-0.004%** versus the old Jev rule. Persistence increases launches but about
  **90.6%** are unused; its native geometric mean throughput is 0.65% below the
  classic tuned reserve, with one setting 19.45% worse.
- Cross-agent protection matters within the extended policy: at 12/30 s and
  four workers, persistent own/full means are **32.828/28.352 s**, but the
  classic reserve is **28.254 s**. No general Jev advantage is established.
- A cheap reserve screen before optional model generation cuts those model-call
  counts about **89.5%** in the focused native sweep. Budgeted Jev throughput is
  essentially matched by the cheaper reserve. This is the strongest practical
  resource-efficiency improvement, not a proven general speedup.
- A 150-second actor outlier dominates the finite 30-question makespan. The
  repeated 300-instance diagnostic still does not establish an overall Jev win:
  the budgeted Jev hybrid improves 1.24% over a classic reserve in one cell,
  while remaining slower than no speculation there. Repeated traces are not
  fresh questions or independent model trials.
- **191 tests pass**, Ruff lint/format pass. Replay blocks network, checks quota,
  worker accounting, answers and context coverage. Paid captures and all older
  banks/results remain unchanged. Keep the new credential-free bundle identified
  by `docs/JEV_ASYNC_MANIFEST.json` with the earlier bundles.

**Practical direction:** retain required-call priority, pre-generation quota
screening, asynchronous optional gates and dispatch-time revalidation. Treat Jev
as optional advisory work with a budget, rather than requiring it for every
candidate. A fresh cohort and live multi-agent check are still needed. Background
per-agent demand forecast caching is a possible future experiment, not a tested
feature. Keep Kev deferred per the user's instruction.

The checkpoint below describes the earlier conservative objective and is retained
as history. Its numbers are not results for the new asynchronous variants.

## Current checkpoint: Jev integration and quota experiments complete

See `docs/JEV_RESULTS_2026-11-12.md` for the complete protocol, figures,
reproduction commands and caveats. **Use Jev for now**, per the latest user
instruction; Kev is deferred.

- `tape_forecasts.py` enumerates both running-parent and following-thinking
  candidate contexts, fits development-only Search timing/history, collects
  resumable model outputs and enforces exact offline context coverage.
- `results/hotpot-jev-progress-50/` holds **1,186 successful real Jev forecasts**
  from `typesafe/jev-1.14-20261014`. Mean/p95 client latency is 0.296/0.535 s.
  Cost including the access probe is **$0.030114672**, provider-reported.
- `forecast_study.py` integrates the existing PredictiveAdmission full/own
  objectives with all candidate ranks and the persistent shared quota. Actual
  measured predictor and scheduler latency is included. Parallel and serial
  request assumptions are explicit; no paid fallback occurs in replay.
- The final native study is
  `results/hotpot-forecast-quota-native-full-reserves/`: **4,000 paired replays**,
  capacities 1/2/3/6/12, resets 1/5/10/30/60 s, 1/2/4/8 workers, five order seeds,
  eight policies. Every integer reserve through capacity is eligible for tuning
  on development data. Native Jev full-versus-own gains peak at **0.66%** and
  do not show an advantage over a properly tuned cheap reserve.
- **1,284 additional sensitivity replays** cover synthetic 5-second Searches,
  forecast latency and a 90-second rollout horizon. Full admission improves
  mean completion by 18-21% over own-only under some slow-refill contention,
  but often still loses to no speculation or a tuned reserve. These are
  exploratory workload sensitivities, not measured live Search improvements.
- Equal nominal call rates can behave differently with different reset batches.
  Jev exact-reuse calibration is worse than development history on this cohort;
  demand prediction is somewhat better. Do not claim a general Jev win.
- **180 tests pass**, Ruff lint/format pass. Every reported replay checks quota,
  worker drain, frozen answers and no fallback with network sockets blocked.
  Prior captured evidence remains checksum-identical.
- The phase-entry elapsed=0 approximation remains. This is the already explored
  20/30 split on fixed authoritative tapes, with unlimited provider concurrency.
  No new answer-quality or live serving-capacity claim is justified.
- Two public-demo Kev three-question responses are retained as access checks;
  the public ZeroGPU limit prevented a complete bank. No Kev scheduling result
  is presented. Do not resume Kev unless asked.

**Next work:** improve candidate lead time and exact-reuse calibration using
only development data, test a cheap reserve-plus-prediction rule, and obtain a
new question cohort plus a small live multi-agent validation before stronger
claims. Raw results are Git-ignored; preserve the local bundle identified by
`docs/JEV_STUDY_MANIFEST.json` alongside the capture bundle.

The capture checkpoint below remains as historical handoff context. Statements
there that Jev has not been called are superseded by this section.

## Current checkpoint: complete 50-question capture

Completed November 12, 2026, following the requested 20-question validation and
expansion to 50. See `docs/CAPTURE_RESULTS_2026-11-12.md` and
`docs/CAPTURE_REPLAY.md` for evidence and commands.

- `results/hotpot-dataset-50/` contains 50 canonical speculative tapes plus
  independent sequential evidence: 100 successful live episodes. Full version 2
  capture records 436 authoritative state transitions, model/tool durations,
  queues, exact inputs/outputs, costs, full WikiEnv states and unused prefetches.
- Separate bank completion filled skipped/late windows and missing Search
  alternatives using only frozen pre-tool histories. The complete bank has 151
  windows, 441 ranked candidates and all 247 eligible Search candidate ranks
  covered by full results/states. No new inference is needed to simulate it.
- `results/hotpot-shared-quota-50/` runs no speculation/current capacity/fixed
  reserve with 1/2/4/8 continuous workers and one persistent Search quota.
  `frozen_replay.py` supports every candidate rank and recomputes dependency
  readiness; it reuses existing quota and observed-policy/model interfaces.
- `results/hotpot-predictor-inputs-50/` prepares 3,378 exact unique contexts
  (939 progress contexts) and 4,695 case references through `bounded_context`.
  Development/evaluation task IDs are disjoint (20/30); labels remain separate.
  **Jev/Kev have not been called.** Contexts retain phase-entry `elapsed=0`.
- Socket-blocked validation checks all 50 answers across policies, worker limits
  and quota windows. All 436 authoritative state transitions/prompts pass pinned
  restore/parser checks. Recorded stage DAG timing reproduces within 1 microsecond.
  This verification uses observed DAG/state replay and virtual-time scheduling;
  a separate wall-clock-sleep playback adapter has not been implemented.
- 170 tests passed with no skips; Ruff lint/format passed for 64 Python files.
  The original paid summary reproduces exactly, and all 118 protected old files
  remain byte-identical to the earlier checkpoint.
- Known new charges total $0.396111, matching the observed account usage delta.
  Two aborted early requests keep unknown individual cost fields; the original
  aborted runs and every started request remain preserved. The successful 13-
  and 30-question paced runs have no unknown charges. Long provider latency
  outliers remain in the data.

Baseline cleanup remains complete: `artifacts.py`, `upstream.py` and
`transport.py` keep the active runtime isolated from historical experiment
drivers. `capture.py`, `capture_audit.py`, `capture_bank.py` and
`capture_cohort.py` now provide versioned capture, validation, completion and
cohort assembly. The old `stage_export.py` is retained for the original
incomplete recordings; its `replay_ready=false` result does not apply to the
new completed 50-question bank.

The earlier 218-file pre-cleanup archive and tracked manifest remain
`results/baseline-checkpoint-2026-11-12/baseline.tar.gz` and
`docs/BASELINE_CHECKPOINT.json`. The new data bundle is described by
`docs/CAPTURE_50_MANIFEST.json`. Results, archives and downloaded upstream are
Git-ignored: keep the bundle separately from an ordinary checkout.

**Immediate next task:** integrate history/Jev/Kev forecasts with the completed
multi-candidate tapes. Validate endpoint/model availability; start on development
progress contexts, freeze exact-context responses and measured latency/cost,
then compare full cross-agent versus own-agent admission on the same banks.
Never silently fetch an uncovered context during replay. Preserve or explicitly
extend the elapsed=0 approximation. Do not interpret fixed single-agent service
durations as measured provider capacity under multi-agent load.

The sections below retain the original design rationale and research order;
cleanup, capture, finite bank completion and basic multi-agent replay are now
implemented. Predictor integration and the live multi-agent check remain open.

## 1. The vision

Get to one understandable, reproducible HotpotQA baseline that uses the parts
of the authors' implementation we need and the parts of our implementation we
need. Keep a small, clear active code path. Retire competing legacy entry points
so a new session does not need to rediscover which experiment is current.

That baseline is the foundation for:

1. Saving complete stage outputs and replaying them without repeated inference.
2. Simulating multiple agents sharing a Search quota.
3. Adding Jev and Kev to predict demand/reuse for our admission controller.
4. Testing whether cross-agent scheduling improves global throughput over
   speculative execution alone.

Simplify around the working baseline before integrating more features. Preserve
existing useful extension code so it can be brought back deliberately.

## 2. What currently works and which codebase it uses

**The latest live latency experiment uses our asynchronous runtime, with actual
components imported from the authors' pinned code. This repository is the
primary codebase to continue from.**

| Part | Keep from |
| --- | --- |
| ReAct instructions, examples, observation/action prompts | Authors' implementation |
| Action extraction and thought/action parsing | Authors' `HotPotQARun` methods |
| Wikipedia Search and local Lookup/Finish behavior | Authors' `WikiEnv`, with our state/application adapter |
| Dataset, intended question order, answer normalization/F1 | Authors' data and conventions/functions |
| Async execution, speculation windows, cache/in-flight joining | Our `src/quota_spec/hotpot_runtime.py` |
| OpenRouter transport, spending guards, logs, paired measurements | Our implementation |
| Future shared quotas, scheduling/admission, replay and predictor adapters | Our existing project modules, to integrate after cleanup |

The upstream repository is `https://github.com/naimengye/speculative-action` at
revision `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c`. The full local clone is
`tmp/speculative-action-upstream/`; checksummed imported files are under
`data/raw/speculative-action/<revision>/`. Keep provenance and the upstream
Apache license. No GitHub fork has been created.

The earlier direct agreement check called the authors' serial `webthink`
runner. The latest live latency test uses our episode loop instead, while
reusing the authors' components. Do not confuse those two drivers or replace
the concurrent baseline with the serial evaluator during cleanup.

The latest run used **Gemini 2.5 Flash for both the authoritative actor and
observation predictor**. Actor calls had a 1,000-token cap; observation calls
had a 100-token cap. This was not yet a genuinely large/small model pairing.
The hypothetical actor also used Gemini. Jev/Kev demand prediction is a
separate future function, not the current observation predictor.

## 3. Baseline evidence to preserve

The complete end-to-end experiment ran 20 questions in each mode, with the
paper's seven-action limit:

| Metric | Sequential | Speculative |
| --- | ---: | ---: |
| Mean answer latency | 6.659 s | 5.975 s |
| p95 answer latency | 11.959 s | 11.221 s |
| Answer exact match | 35% | 30% |
| Forced finishes at action limit | 5 | 7 |
| Inference requests | 92 | 204 |

Speculation produced three exact hits from 24 prefetched searches. Those hits
overlapped 1.934 seconds of Search work. The observed mean latency reduction
was 10.27%, which is encouraging, but the paired 95% saving interval
[-0.217, 1.568] seconds includes zero. Only 9/20 pairs followed identical action
sequences. Preserve the baseline as a working system with useful live
prefetching and a positive measured point estimate, not a proven general
speedup or a full reproduction of all paper results.

All 40 episodes finished execution with zero inference failures. Some ended
with empty answers at the action limit, as shown above. The run cost
$0.142458; the configured environment passed 154 tests at this checkpoint.

Preserve these files/directories unchanged:

- `results/hotpot-live-paired-20/`: raw requests/responses, timings, events,
  episode trajectories, configuration, summary, audit, report and chart.
- `results/hotpot-live-audit/`: exact paid source snapshot, cost audit and tests.
- `results/upstream-direct-gemini-20/`: independent authors' runner comparison.
- `docs/HOTPOT_RUNTIME_RESULTS_2026-11-12.md`: detailed live result interpretation.

The latest capture already contains **all 296 model requests/responses**, 1,299
events, and 40 episode files. We do not need to pay again to inspect or rescore
those outputs. Full frozen replay is not implemented yet.

`results/`, `tmp/` and downloaded source are Git-ignored. Make the retained
baseline reproducible from the pinned download plus an explicit evidence
manifest/archive; do not assume an ordinary Git checkout contains local data.

## 4. First priority: simplify to one active baseline

### A. Preserve the checkpoint and map dependencies

- Inspect the working tree first. It currently contains substantial uncommitted
  work; do not reset it or delete files indiscriminately.
- Preserve a baseline source/evidence manifest before moving code. Keep paid
  source snapshots immutable even when active source changes.
- Trace imports from `hotpot_runtime.py` and the report script. Some small
  helpers currently come from much larger historical modules: `write_json`
  from `collect_qa.py`, source hashing from `experiments.py`, and upstream
  loading from `paper.py`. Identify the minimal required dependency chain.

### B. Extract a small active core without changing behavior

Keep the current package rather than introduce a second implementation. A
reasonable target split is:

| Responsibility | Target |
| --- | --- |
| Episode orchestration and speculation semantics | `hotpot_runtime.py` |
| Pinned upstream preparation/imports and workload access | A small `upstream.py` adapter |
| Async OpenRouter calls and concurrent request/dollar budgets | A focused transport module |
| JSON/source manifests and complete stage recording | Small artifact/capture modules |
| Usage/metrics | `telemetry.py` and focused reporting helpers |
| Offline report/audit | `scripts/report_hotpot_runtime.py` |

The new module names above are proposed boundaries, not files that already
exist. Extract shared helpers with compatibility imports where necessary so
future extension code is not accidentally broken. Keep authors' algorithms
and parsing behavior pinned; do not silently rewrite their semantics.

Preserve these baseline rules: authoritative actors see real observations;
speculative state stays isolated; exact Search arguments determine reuse;
in-flight calls can be joined; Lookup/Finish remain authoritative and local;
late predictions do not gate required work; all started paid work is accounted
for, including background drain and errors.

### C. Remove competing default paths and organize future code

- Keep one documented live command, one offline smoke command and one report
  command. Keep the original-runner comparison as an explicit reference check.
- Review the older local-BM25/direct-query pipeline, scripted collectors,
  exploratory scripts and superseded report entry points. Archive or remove
  genuinely unused paths only after checking imports and preserving the
  checkpoint. They should not remain competing defaults for this workload.
- Preserve useful quota/replay/admission/predictor modules as a clearly marked
  future extension, outside the baseline execution path. Do not wire them into
  the baseline merely because they already exist.
- Simplify README, Makefile and command registration around the active path.
  In particular, today's default `make offline` invokes the older pipeline;
  do not present that as the canonical HotpotQA runtime. Ensure baseline setup
  installs its required `paper` dependencies.
- Keep relevant baseline tests and extension tests clearly separated. Update
  documentation links and imports alongside moves; remove stale active
  instructions without erasing historical experiment evidence.

**Cleanup is done when:** a fresh session can identify the active implementation
from README, run its offline smoke test, regenerate the existing paid report
without inference, and understand where each core component comes from. The
refactor must preserve recorded behavior and pass applicable checks; it does
not require another paid benchmark just to validate file moves.

## 5. Save complete stages, then make frozen replay the next building block

Before another collection run, add a versioned recorder around these natural
boundaries. They are asynchronous events, not barriers that force waiting:

1. True actor completes and produces a required action.
2. Required Search starts while observation prediction starts in parallel.
3. Observation predictor finishes and produces a provisional observation.
4. Hypothetical actor finishes and produces up to three candidate actions.
5. Real/prefetched tool completes; the next true actor selects an action and
   exact-match reuse is validated.

Save node/agent/step/branch/attempt IDs, dependency edges, exact inputs/outputs,
model settings, state hashes, readiness/start/end times, service versus queue
time, costs/tokens, errors/truncation, and complete ranked candidate lists.
Store full tool results and before/after WikiEnv state, including page content,
result titles and lookup cursor, for both used and unused searches.

Existing logs contain model outputs and observed trajectories, but not every
full tool state or every counterfactual branch. The old replay schema also
supports only one candidate per step; it cannot faithfully represent the new
three-candidate runtime without extension.

Start by exporting the existing recordings into a dependency graph and a
coverage report. Use the 20 speculative episodes' authoritative trajectories
as the initial fixed tapes because their recorded candidates belong to those
same histories. Keep independent sequential episodes separate. Do not match
responses by question/step alone when their exact prompt histories differ.

Enumerate missing entries, then fill only those needed for the declared
scheduling experiment in a separate collection mode. This can include windows
originally skipped because of lateness or cache hits. Use only information
available at the original boundary. Keep bank completion outside the live
latency benchmark so it does not distort measured runtime.

**Replay is done when:** a socket-blocked one-agent run consumes saved outputs,
reproduces the recorded schedule/cache hits/answers within declared timing
tolerance, and can compare scheduling policies on the same fixed outputs.
Missing data must be explicit, never silently fetched through paid inference.
Changing the model, prompt or generated reasoning path may require new data;
frozen scheduling replay does not cover arbitrary new agent behavior.

See `docs/FROZEN_REPLAY_PLAN.md` for the detailed schema, coverage constraints
and acceptance gates. This root file is the main handoff; that document is the
technical supplement.

## 6. Extend the clean baseline to multiple agents

After one-agent replay is validated:

- Extend our existing `replay.py`, `models.py` and `workload.py` to represent
  multiple candidates and dependency-triggered work faithfully.
- Run 1/2/4/8 agents with common arrivals, seeds, frozen outputs and service
  durations under one shared fixed-window Search quota.
- Recompute readiness as dependencies finish. Do not replay absolute original
  timestamps when quota waiting, joining or reuse changes an agent's progress.
- Compare no speculation, current-capacity admission, fixed reserve and history
  forecasting before introducing external predictor calls.
- Reuse the existing quota, policy and admission modules where verified.
  Cancellation must not restore already-consumed quota. Keep required-call
  ordering fixed when comparing admission rules.

Report completion latency, p95, makespan/throughput, required-call waiting,
wasted calls, per-agent fairness and overhead. Keep fixed inference-capacity
assumptions explicit: replaying recorded single-agent model durations does not
measure a provider's actual multi-agent serving capacity.

## 7. Add Jev and Kev as predictors, then test our contribution

Jev and Kev forecast upcoming demand and candidate reuse from observed agent
progress. Our admission controller uses those forecasts to weigh an optional
call's benefit against delays imposed on other agents. They do not replace
the authoritative actor or automatically generate speculative tool candidates.

- Bring forward the existing adapter and forecast-bank interfaces deliberately.
  Verify current Jev access and Kev serving/model availability when integrating;
  neither is validated end to end through the new runtime yet.
- Keep history, Jev and Kev behind the same bounded predictor interface.
- Cache forecast outputs once per exact declared context/model configuration
  and replay their measured latency/cost. The existing bank's `elapsed=0`
  phase-entry assumption must be labeled or explicitly extended.
- With forecasts fixed, compare full cross-agent admission against the same
  rule considering only the proposing agent. This isolates our contribution.
- Make missing model/context coverage explicit. Keep unavailable Kev/Jev work
  marked incomplete rather than silently omitting a planned comparison.
- Use development data for tuning. These already explored 20 questions are a
  pilot, not fresh held-out evidence. Expand toward the proposal's larger
  disjoint development/evaluation workload after capture/replay is trustworthy.
- Finally, use a small live multi-agent check to validate replay assumptions,
  quota accounting, real contention and answer correctness.

## 8. Resume checklist for the next session

- [x] Read this file and inspect the working tree and retained paid evidence.
- [x] Preserve the baseline checkpoint and map the actual dependency graph.
- [x] Simplify the active runtime/imports/commands without changing semantics.
- [x] Make README point to one baseline and one clear future extension path.
- [x] Export existing stage records and report missing replay coverage.
- [x] Add complete capture and a versioned output/state store.
- [x] Validate network-blocked one-agent frozen replay.
- [x] Add faithful multi-candidate, multi-agent shared-quota replay.
- [x] Integrate history/Jev forecasts and full versus own-agent admission; Kev deferred.
- [ ] Validate selected conclusions with a small live multi-agent experiment.

**Immediate next task:** follow the Jev result checkpoint at the top of this file;
forecast freezing and own/full quota sweeps are complete.

Current verification commands (use a fresh output path for the smoke run):

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests scripts
.venv/bin/python -m quota_spec.hotpot_runtime \
  --backend mock --count 2 --output results/resume-smoke-fresh
.venv/bin/python scripts/report_hotpot_runtime.py results/hotpot-live-paired-20 \
  --output results/resume-report-fresh \
  --source-snapshot results/hotpot-live-audit/source-snapshot
.venv/bin/python -m quota_spec.stage_export results/hotpot-live-paired-20 \
  --output results/resume-export-fresh
```

These checks do not intentionally request new model inference. The offline
runtime expects pinned upstream files to have been prepared already. Preserve
credentials in the existing environment/configuration, never in traces or docs.

Current completed-bank commands (fresh output directories required):

```sh
.venv/bin/python -m quota_spec.frozen_replay results/hotpot-dataset-50 \
  --agents 1 2 4 8 --capacity 3 --window-s 10 --output results/replay-next-fresh
.venv/bin/python -m quota_spec.frozen_forecasts results/hotpot-dataset-50 \
  --development-count 20 --output results/predictor-inputs-next-fresh
```
