# Proposal implementation checklist

Updated October 29, 2026. Software readiness and empirical measurements are
separate: no real model inference was performed during this credential-free work.

## Implemented and ready to run

- [x] Fixed-window quota ledger with no refunds on completion/cancellation.
- [x] Atomic asyncio/FastAPI gateway, FIFO required priority, exact caching and joining.
- [x] Dependency-aware replay with observed-only policy inputs.
- [x] Paired cross-agent admission with horizon/sample bounds and estimated risk guard.
- [x] No-speculation, current-capacity, fixed-reserve and usage-reserve baselines.
- [x] Own-agent ablation; separate progress-ordering controls with and without speculation; privileged greedy reference.
- [x] Development-only history transitions and time distributions.
- [x] Bounded Jev/Kev HTTP adapters, timeouts, response validation and failure telemetry.
- [x] Five predictor/context configurations and frozen-response policy comparisons.
- [x] Held-out reuse/next/continuation calibration and token/cost recording.
- [x] Checksummed local corpus and source dataset attribution.
- [x] Main QA integration and resumable, checksummed LLM trajectory collection.
- [x] Final answer generation, no-search answers and terminal candidates in replay.
- [x] Candidate timing, inference timing and stale-dispatch revalidation.
- [x] Frozen development tuning and all 12 focused sensitivity settings.
- [x] Paired seeds and multi-metric bootstrap intervals, including full versus own.
- [x] Live QA answer EM/F1 and quota/latency/failure reporting.
- [x] One-command workflow, mock modes, resume, reports, plots and CI smoke coverage.

## Empirical work that starts after access is configured

- [ ] Authenticate the chosen QA endpoint, Jev account and pretrained Kev server.
- [ ] Run the real 10–20-task pilot and choose the experiment timescale on development.
- [ ] Collect 100–200 successful LLM task traces and actual inference costs.
- [ ] Freeze Jev/Kev forecasts and run held-out context/scheduling comparisons.
- [ ] Inspect real live answer accuracy and replay/live discrepancies.
- [ ] Write the final course paper from those measurements, including negative results.

The question/top-title candidate generator is an explicit heuristic substitution
for a learned generator. The core contribution is the cross-agent admission rule,
not reproduction of an external candidate-generation system. Forecast-bank
contexts freeze phase-entry elapsed time; adaptive elapsed-state behavior is
covered separately by the live gateway and CLI. The fixed-window, serial-chain,
single-process scope remains intentional.

See [RUNBOOK.md](RUNBOOK.md) for the exact commands and [REVIEW_VALIDATION.md](REVIEW_VALIDATION.md)
for key-free evidence. Existing numerical reports are historical until regenerated.
