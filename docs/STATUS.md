# Current implementation status

**Quota-aware speculation experiment:** the optional speculative branch can now
receive remaining calls, capacity, refill timing and competing required work
without sending that context to the main agent or calling Jev. The final pilot
contains 240 clean episodes on 16 unique questions across three quota regimes. It reduces unused calls,
but does not establish a win over both baselines; Jev remains the default.
281 tests pass; additional known API charges are $1.256674044, reconciled to the
settled account delta. See [the experiment, controls and results](QUOTA_PROMPT_2026-11-15.md).

**November 15: confirmed matched-replay wins over both baselines.** On 80 new
held-out questions, the locked 4-worker / 12-Search / 3-second setting reduces
mean completion by **1.57% vs no speculation** and **10.11% vs allow-all**;
whole-batch time falls **1.46% / 10.09%**. All ten paired orders and the 95%
question-bootstrap intervals favor the method. The 75-setting quota/refill map
retains losses: 13 settings beat both baselines on both endpoints. This is
measured replay evidence; the final live smoke verifies operation, not live A/B
speed. **275 tests pass; $1.439993844 additional API spend is reconciled.**
See [the full result, controls, quota maps and reproduction](QUOTA_WINS_2026-11-15.md).

**November 15: live multi-agent Jev integration works end to end.**
The new driver runs real 2/4/8-agent workloads with shared quota, asynchronous
observed-state forecasting, exact reuse and atomic admission. The campaign
retains 236 live episodes (including two failed runs that exposed repaired
provider-handling bugs), 216 matched replays and a complete 3,054-context bank.
The final eight-worker confirmation has zero actor/optional failures; 266 tests
pass. Known costs match the $0.841052284 account delta; unknown-attempt reservations
raise the conservative bound to $0.847911884. Cross-agent protection is measured,
but a general gain over no speculation remains unproven. See
[the integration report](MULTI_AGENT_CONTEXT_2026-11-15.md) and
[current handoff](../next_steps.md). Entries below are historical checkpoints.

**Latest throughput repair:** request-triggered generation, candidate retry at
quota resets and answer-time worker release are now the named `overlap` replay
profile. Historical controls remain reproducible. The live answer-time delta
is reconciled separately from same-path overlap and shared-quota throughput.
See [the repair report](THROUGHPUT_REPAIR_2026-11-13.md).

**November 13 async cleanup:** episode-long prediction windows, reserved actor
capacity and endpoint/event accounting are active. The fresh 20-question pilot
measured 7.01 → 6.25 seconds per answer; same-path scheduling accounts for
0.20 seconds per question. Live uncertainty includes zero. See
[the current validation report](ASYNC_SPECULATION_VALIDATION_2026-11-13.md) and
[current handoff](../next_steps.md). All entries below describe earlier checkpoints.

**Earlier: 50-question capture and scheduling bank complete.** All 100 live
episodes and 436 authoritative state transitions/prompts passed verification.
The completed bank has 151 windows, 441 ranked candidates and no missing eligible
Search results. Socket-blocked 1/2/4/8-worker replay and 3,378 prepared predictor
contexts are available. Jev/Kev calls remain the next step. 170 tests and Ruff
checks pass. Known collection charges were $0.396111, matching the account usage
delta. See [the current checkpoint](CAPTURE_RESULTS_2026-11-12.md). Entries below
are historical and may describe earlier incomplete capture/replay versions.

Baseline cleanup and existing-recording export are complete. The runtime now
imports focused upstream, transport and artifact helpers; README/Makefile/CI
select the concurrent HotpotQA baseline. A checksummed source/evidence archive
preserves the pre-refactor checkpoint. Offline auditing regenerates the original
paid summary exactly and verifies its source snapshot. The exporter accounts
for all 296 model requests, 1,299 events and 40 episodes, retaining 157 candidate
ranks. Replay remains incomplete because full Search results/WikiEnv states and
skipped alternatives were not recorded. See [export coverage](STAGE_EXPORT.md)
and [the current handoff](../next_steps.md). Verification: 159 tests passed with
no skips, Ruff lint/format passed, the four-episode offline smoke completed, and
all 118 protected evidence files match their checkpoint. No new inference was
requested. The dated entries below are history.

Live end-to-end HotpotQA, November 12: all 20 paired questions (40 episodes)
ran through the new concurrent runtime, with no inference failures. Mean
sequential/speculative answer latency was 6.659/5.975 s, an observed 10.27%
reduction; the paired 95% saving interval [-0.217, 1.568] s includes zero.
Three of 24 prefetched searches were reused. Independent trajectories and
different answer scores prevent a reliable causal speedup claim. New spending
was $0.142458; 154 tests passed. See
[live runtime results](HOTPOT_RUNTIME_RESULTS_2026-11-12.md).

Direct upstream cross-check, November 12: a full pristine checkout and the
authors' actual `HotPotQARun.webthink` completed 20 Gemini questions through
OpenRouter, with explicit task/state fixes and no collector/replay/quota/Jev.
Top-one/top-three agreement was 21.17%/36.50%, versus 19.58%/38.33% in Figure 4.
This reproduces the qualitative agreement behavior; live throughput remains
unmeasured. The new harness and a separate GPT-5 nano compatibility probe cost
$0.11588810; combined recorded work is $0.469644574. All 145 tests passed.
See [direct upstream results](UPSTREAM_RESULTS_2026-11-12.md) and
[reproduction commands](UPSTREAM_BASELINE.md). Older status entries below are
historical snapshots.

**Current priority: single-agent reproduction before extension.**

The latest user direction defers Jev/multi-agent work until the Speculative
Actions baseline is established. See [single-agent results](SINGLE_AGENT_RESULTS_2026-11-12.md)
and [reproduction guide](SINGLE_AGENT_REPRODUCTION.md). Gemini top-three agreement
matched the displayed 38.33% paper value on 20 intended seeded questions;
GPT-4.1 nano reached 36.67% versus 46.25%. GPT-5 nano failed its first observation
with no visible response at the unchanged 100-token cap. Full reproduction and
live throughput validation remain incomplete. 142 tests pass with no skips;
combined review/reproduction spending is $0.353756474, within the original $0.50
limit. Historical status entries below are retained as evidence.

Canonical pipeline refactor, November 12: `quota_spec.paper_pipeline` now connects
the pinned upstream workload to frozen forecasts and the existing multi-agent
admission study. Replay retains stateful Lookup/Finish as non-quota actions and
supports proposals released from the preceding tool dispatch. Only Search is
cached and charged against quota. Full/own-agent comparisons share the same
inputs and forecast banks. See [PAPER_PIPELINE.md](PAPER_PIPELINE.md).
Current local verification: 124 tests pass. Independent model testing is handed
off in [NEXT_AGENT_TESTING_PROMPT.md](NEXT_AGENT_TESTING_PROMPT.md); no paid tests
were run for this refactor. The canonical path currently validates timing through
frozen replay, not through independently scheduled live actor runs.
A network-blocked eight-task mock run completed all five forecast contexts,
12 settings and two seeds (432 aggregate rows), with zero prediction fallbacks.
Evidence is in `results/paper-refactor-offline/` and
`results/paper-refactor-tests.log`.

The alignment notes and older pilot results below are historical.

Workload alignment correction, November 12: the local-BM25/direct-query pilot
must not be used as a paper reproduction. `quota_spec.paper` now runs the
authors' pinned HotpotQA code with its original data, prompt templates and live
Wikipedia tools. A two-task smoke test completed with 29 inference requests
and no inference failures. See [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md).
The controller connection was subsequently implemented in the canonical pipeline
described above; the original two-task smoke itself remains an agreement check.

Updated November 12, 2026. The real OpenRouter pilot completed collection,
five Jev context banks, 648 frozen replay rows and live validation using
DeepSeek V4.1 Flash and GPT-OSS 120B. Kev was omitted. All inference succeeded
and all live quotas were valid. See [the pilot results](OPENROUTER_PILOT.md)
for costs, timing, answer quality and the absence of a measured speedup.
The final source passes 110 tests and a full mock pipeline with network access
blocked. Late drafts and queued admissions are cancelled at main-action
completion; neither optional stage blocks required searches. OpenRouter billed
costs, reasoning/JSON options and latency routing are supported.

The November 5 and October 29 notes below are historical snapshots.

Updated November 5, 2026. A separate small-model Speculator now proposes searches
in parallel with main QA inference. HTTP collection and live QA default to it;
Jev/Kev retain their demand/reuse forecasting role and the controller still decides
admission. The original heuristic is an explicit ablation. Configure the separate
`SPECULATOR_*` settings described in [RUNBOOK.md](RUNBOOK.md).

Current verification: 104 tests pass, including HTTP fixtures for proposals,
abstention, malformed responses, timeouts, context bounds, label isolation,
parallel timing, admission/reuse, separate cost accounting and resume identity.
A 20-task mock pipeline completed all stages with socket connections blocked
(two seeds, five contexts and 12 scheduling settings). No real Speculator or
other model endpoint was invoked. New collection/pipeline checkpoints are version
3 and require a fresh output directory when switching from older source/configs.

The October 29 verification below describes the earlier implementation.

The project has a complete executable path from QA
trace collection through frozen predictor/context experiments, scheduling sweeps,
live validation and generated reports. See [RUNBOOK.md](RUNBOOK.md).

Verified without credentials:

- 94 tests pass with optional HTTP dependencies installed.
- Standard-library-only run: 87 tests reported, eight skipped for optional HTTP
  integrations (the skipped HTTP test class accounts for the test-count difference).
- A 20-task mock pipeline completed all five contexts, 12 settings, five seeds,
  and 18 policy configurations: 1,080 aggregate rows.
- Ten live mock policy runs (four tasks each): zero QA/predictor failures,
  valid quota budgets and null answer-quality scores as intended.
- The original 200-task scripted workload completed 480 aggregate rows.
- Resume completed with QA and predictor request methods patched to fail if called;
  no successful collection or forecast request was repeated.
- The complete mock pipeline ran with socket connections blocked.
- Ruff lint/format checks, editable installation and wheel build passed.
- Sensitivity PNGs and rendered PDF output were visually inspected.

Full validation details and reproducibility evidence are in
[REVIEW_VALIDATION.md](REVIEW_VALIDATION.md). Generated evidence remains under
ignored `results/final-audit-*` directories; source tests, run instructions and CI
are tracked.

No real QA model, Jev account or Kev server was invoked. Those measurements require
credentials/endpoints. The implementation does not claim successful authentication,
real answer accuracy, external calibration, cost measurements or a predictive-policy
advantage. The existing corpus/trajectories remain scripted retrieval; mock traces
are explicitly synthetic.

`docs/REPORT.md`, `docs/evaluation-summary.json`, and `docs/figures/` retain earlier
exploratory results with historical warnings. Use newly generated study artifacts
for current analysis. The final course paper still needs actual experiments and
interpretation; the generated report supplies results tables and limitations.
