# Implementation status

> Review note (October 28, 2026): numerical results below are historical, from
> before the correctness review. Current code fixes progress tracking, forecast
> state, execution-duration leakage, deadline censoring, inference overhead and
> aggregation. Regenerate studies before using old numbers as current evidence.
> See [API setup](API_SETUP.md) and [review validation](REVIEW_VALIDATION.md).

Updated October 28, 2026. The local implementation now includes observed-state
history forecasts, bounded paired admission, usage reserve and own-agent ablations,
a progress-ordering control, an atomic FastAPI/asyncio gateway, a frozen HotpotQA
search corpus, and measured scripted retrieval experiments.

- 41 tests pass, including concurrency, cancellation, failures, quota boundaries,
  FIFO refill ties, predictor timeouts and information-boundary regressions.
- 200 scripted tasks, split 100/100; 20 development tasks form the pilot.
- 12 held-out settings x five seeds x seven policies/controls: 420 aggregate rows.
- A full frozen-config repeat exactly reproduced metrics, intervals and calibration.
- 12 live tasks across three policies: identical required queries/results and
  no quota violations. LLM answer correctness is unmeasured.
- History Brier 0.0682; external-model measurements remain absent.

The experiments show useful one-agent reuse and small/inconsistent admission
benefits under contention. They do not establish a general predictive-policy
advantage over simple reserves. See the [exploratory report](REPORT.md),
[retained numeric summaries](evaluation-summary.json), and
[sensitivity plot](figures/sensitivity.png). Full events/outcomes are under
ignored `results/study/`; live evidence is under `results/live/`.

Five checklist items remain open: real Jev/Kev inference measurements, external
context comparisons and telemetry, LLM-agent answer validation, and the final
research report. See [model access](MODEL_ACCESS.md) for concrete access/runtime
blockers and [the checklist](IMPLEMENTATION_PLAN.md) for completed work.

The original synthetic smoke runs remain useful regression examples, but the
new measurements are still an exploratory engineering study using scripted
retrieval. No paid model call, model training, hosted deployment or remote Git
publication was performed.
