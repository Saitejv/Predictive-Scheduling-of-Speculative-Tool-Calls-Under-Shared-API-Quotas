# Implementation plan

Updated October 28, 2026 against the October 23 proposal. Checked items have
local code or measured artifacts. Scripted retrieval traces are explicitly
identified; external model runs and LLM answer validation remain open.

## First milestone: replay and pilot

- [x] Initialize a local Git repository and preserve the original proposal.
- [x] Write architecture, trace, evaluation, and implementation documentation.
- [x] Implement fixed-window accounting, FIFO required dispatch, exact reuse,
  in-flight joining, and serial dependency-aware readiness.
- [x] Implement no speculation, current capacity, and fixed reserve baselines.
- [x] Implement a separate future-informed greedy reference.
- [x] Provide seeded synthetic comparisons and machine-readable artifacts.
- [x] Test accounting, reuse, same-time ordering, dependencies, and leakage boundary.
- [x] Collect 20 measured scripted retrieval pilot traces, with original task IDs
  and dataset provenance; the pilot is a subset of development tasks.
- [x] Audit Jev/Kev access, hardware and exact API contracts; select and resolve
  a pretrained Kev artifact. See `MODEL_ACCESS.md`.
- [ ] Measure actual Jev/Kev inference cost and latency on working model access.
  Blockers: no Jev credential, no Kev endpoint/runtime, limited local disk space.
- [x] Build and freeze a local search corpus from a HotpotQA subset.
- [x] Record candidates from one fixed observed-state generator, at most one per step.
- [x] Compare reserves/reference on the pilot; preserve synthetic cases showing
  useful reference admission, rejection under cross-agent harm, and no mean gain.

The November 2/4 checkpoint can demonstrate replay, quota/reuse tests, the pilot,
and comparisons. These retrieval traces do not replace the planned LLM pilot.

## Admission and history

- [x] Specify a bounded prediction schema and observed-state snapshot format.
- [x] Fit development-only history transitions and time-to-next-call distributions.
- [x] Implement paired simulation with fixed sample budget and horizon.
- [x] Include quota debt, reuse, predicted future required calls, and overhead.
- [x] Define and log the deadline-risk estimate and rejection fallback.
- [x] Add the recent-usage forecast reserve baseline.
- [x] With the predictor/scenario seed fixed, compare full and own-agent-only admission.
- [x] Add regression tests for prediction error, bursts, and horizon boundaries.

## Models and context ablations

- [x] Implement Jev and Kev HTTP adapters behind the bounded prediction schema.
- [ ] Run task/candidate, history, progress/excerpt and removal ablations with real
  Jev/Kev predictions. Context selection is implemented; access is unavailable.
- [x] Enforce observed-at timestamps, bounded excerpts/history, and total prediction timeouts.
- [x] Implement latency, token, monetary-cost and failure telemetry; compute held-out
  history calibration. Missing cost and external measurements remain null.
- [ ] Collect actual Jev/Kev telemetry and calibration after access is configured.
- [x] Keep the same candidate generator across speculative policies.
- [x] Report Jev unavailability without fabricated integration results.

## Experiments and live validation

- [x] Implement FastAPI/asyncio gateway with atomic reservation and call registry.
- [x] Run 12 live scripted retrieval tasks across three policies; compare replay
  timing and verify exact required-result equality and fixed-window budgets.
- [x] Implement bounded main-model HTTP QA integration and synthetic offline tests.
  Configuration and usage: `API_SETUP.md`.
- [ ] Run live **LLM** agents and measure answer correctness, inference/candidate
  cost and timing. The local harness does not generate QA answers.
- [x] Expand to 200 measured scripted task traces, split by task 100/100 into
  development/evaluation. Retain dataset IDs, labels, observations and checksums.
- [x] Freeze development-tuned configurations before held-out comparisons.
- [x] Run 1/2/4/8-agent, burst/staggered-arrival, quota-capacity, quota-period,
  and controlled prediction-error sweeps (12 settings, five seeds).
- [x] Add progress-aware required ordering as a separate controlled experiment.
- [x] Compute paired repeated-seed confidence intervals and report regressions.
- [x] Prepare sensitivity plots, limitations, reproducibility instructions, and an
  exploratory report with measured local results.
- [ ] Complete the final eight-page research report after real-model and LLM-agent
  evidence is available. The proposal's deadline is December 17, 1:00 p.m. EST.

## Remaining external work

1. Provide Jev access and a pretrained Kev serving environment with sufficient disk.
2. Run the implemented context ablations and collect actual external-model telemetry.
3. Collect LLM-agent traces and answer-quality results; repeat the frozen evaluation.
4. Finish the final report using those measurements, including negative results.

No hosted remote is configured. Publishing code was not part of the local task.
