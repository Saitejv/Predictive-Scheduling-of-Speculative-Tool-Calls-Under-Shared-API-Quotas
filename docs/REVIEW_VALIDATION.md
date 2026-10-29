# Credential-free correctness and workflow validation

Updated October 29, 2026. Tests and workflow runs below use no real API credentials.

## Main fixes and completed paths

- Replay no longer reserves quota before inference finishes. Delayed admissions
  recheck state/window/required-queue eligibility and reject stale snapshots.
  Prediction is serialized while unrelated tools and required work continue.
- Traces retain final model generation, no-search answers, final unused candidates
  and candidate-generation delay. These affect completion and deadline outcomes.
- History models represent termination and condition remaining delays on observed
  elapsed time. Required-call timing estimates in studies come from development.
- Conditional candidate reuse and next-call probability are distinguished;
  calibration uses the joint probability for eventual reuse.
- `collect_qa` records actual-model trajectories, answers, observations, service
  timings and cost telemetry, preserving original task splits. Atomic checksummed
  task files support resume; failed tasks cannot disappear from evaluation.
- `forecast_bank` implements all five contexts for Jev/Kev/mock, request previews,
  deduplication, resume, observed-only inputs and held-out calibration. The runtime
  predictor removes labels and charges frozen latency within a total decision budget.
- Studies compare full/own-agent rules on fixed predictions and write paired
  intervals for all primary metrics. Sources, data and banks are fingerprinted;
  stale frozen configurations are rejected.
- The live QA runner overlaps main-model and admission inference, records quota
  waits and unused work, scores answers, and reports predictor failures explicitly.
- `pipeline` joins collection, forecasts, tuning, evaluation, reference, live QA,
  plotting and a generated report. Nonempty outputs are protected. Interrupted
  study/live stages are preserved, and resume behavior is documented.

## Additional audit fixes

- Corrected usage-reserve accounting at fractional refill boundaries.
- Every cached required request contributes zero wait; failed unused speculative
  calls stay in waste counts without refunding quota.
- Added progress ordering with the same current-capacity candidates in replay and
  the live gateway, alongside the no-speculation ordering control.
- The no-progress ablation removes only count/phase/elapsed and retains evidence.
  Other-agent forecasts omit the owner's irrelevant candidate.
- Added paired model/context/reserve contrasts and aggregate prediction fallbacks.
- Validated corpus, labels, source hashes and all resumed model configurations
  before inference. Forecast checkpoints are checksummed and incomplete banks rejected.
- Live QA publishes deadlines to the policy and uses development service estimates;
  the gateway updates duration estimates only after observed completions.
- Failed QA/predictor attempts survive retries. `inference_summary.json` separates
  actual provider usage from modeled replay and preserves unknown prices/usage.
- CI checks formatting/lint plus Python 3.11/3.13 with and without optional extras.

## Automated checks

```sh
.venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=src .venv/bin/python -S -m unittest discover -s tests -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
git diff --check
.venv/bin/python -m pip wheel . --no-deps --wheel-dir results/final-wheel
```

94 tests passed with optional dependencies. With site-packages disabled, 87 tests
were reported and eight optional integrations skipped. Existing tests cover atomic
reuse, cancellations, failures, fixed-window boundaries, FIFO priority, bounded
forecasts and hidden-duration isolation. Added tests cover delayed dispatch,
stale-window rejection, terminal generation, zero-search tasks, collection resume,
label isolation, frozen inference budgets and exact repeated-study outputs.

Both the generic QA HTTP backend and System One adapters were exercised using
`httpx.MockTransport`, including successful parsing, authorization headers,
monetary-cost arithmetic, errors, timeouts and response-size limits. A successful
mocked HTTP QA collection produced correctly scored answers without giving gold
labels to the model. This verifies client contracts, not real provider access.

## End-to-end evidence

`results/final-audit-pipeline/` was generated using the mock backend, mock predictor,
20 source tasks, all five contexts, a .1-second base quota window and default
five seeds/eight samples. Socket connection methods were patched to raise for
the entire run. It completed:

- Ten development and ten evaluation trajectories.
- Five forecast banks and 1,080 aggregate study rows.
- Development-only privileged reference diagnostics.
- Ten live policy configurations, four tasks each, zero failures and valid quotas.
- Main and predictor-context sensitivity PNG/PDF figures and `REPORT.md`.

The same pipeline command with `--resume` completed while both QA decisions and
System One requests were patched to raise. No inference was repeated.

`results/final-audit-scripted/` reran all 200 supplied scripted trajectories,
12 settings, five seeds and eight policies (480 rows). The scripted live check in
`results/final-audit-live/` ran 12 tasks across three policies: all quota budgets
were valid and required query/evidence outputs matched exactly.

The frozen bank repetition is retained under `results/final-audit-repeat/`, using
the same bank argument order and saved configuration. `runs.json`,
`comparisons.json`, `metric_comparisons.json`, `calibration.json` and
`forecast_calibration.json` are compared byte-for-byte. Measured diagnostic
scheduler wall times in event logs are intentionally not expected to reproduce.

`results/final-audit-preflight/preflight.json` confirms no QA endpoint, Jev credential
or Kev endpoint was configured. Public model metadata lookup was not requested.

## Remaining empirical boundaries

Real access, provider compatibility, model quality, inference prices/latencies
and QA correctness remain unmeasured. The candidate generator is a documented
question/top-title heuristic. Frozen bank contexts fix elapsed time to phase entry;
live adaptive forecasts use real elapsed progress. The rollout estimates tool-chain
completion rather than predicting final answer-generation duration. The gateway
remains single-process and the quota model fixed-window. These limitations are
stated in the runbook and generated report rather than hidden by mock results.
