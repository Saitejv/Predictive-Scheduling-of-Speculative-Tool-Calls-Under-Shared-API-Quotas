# Correctness review and offline validation

Reviewed October 28, 2026 against both pages of the project proposal. No real
model inference, API credential, model download or new dataset download was
used. Public provider documentation was checked for the System One contract.

## Changes

- Canonical JSON call identity with exact query text; invalid and blank arguments
  fail early. Numeric budgets, timestamps, probabilities and prices are validated.
- Quota time cannot move backwards within a window, and invalid initial debt is
  rejected. Completion/cancellation continue to retain the dispatch charge.
- Duplicate in-flight required requests advance observed progress once. Progress
  finishes even after all client waiters disconnect. Joined speculation appears
  as running work, failed work can be retried, and pre-start worker cancellation
  cannot leave a poisoned cache entry.
- Required tasks enforce serial chains, stale observations cannot reset progress,
  candidates are limited to one per observed step, and forecasts are revalidated
  against state/window changes. Prediction stays outside the quota lock.
- Explicit task completion releases state/cache and cancels unused speculation
  without refunds. Optional results remain hidden until an exact required call.
- Replay skips stale candidates and exposes estimated running finish times based
  on completed observations, rather than hidden true execution durations.
- Models receive actual completed-call counts. History estimates demand after
  pending work instead of assuming another call always exists.
- Forecast identities cannot collide with real search queries. Overdue execution
  estimates cannot move simulated time backwards. Deadline censoring preserves
  misses at the exact horizon boundary.
- Jev/Kev accept configured endpoints, model names and optional Kev bearer auth.
  Versioned base URLs do not duplicate `/v1`. Requests/responses, request timeouts,
  total decision inference time and token/cost telemetry are bounded or checked.
- External inference latency, including failures, is charged to replay. Usage
  survives malformed answer validation; missing prices remain unknown. CLI
  metrics and inference records identify the policy and failures.
- Mock System One requests use the actual serializer and parser without network.
  Preflight is offline unless explicitly asked to fetch public metadata.
- The environment-driven live factory can select all implemented admission
  policies and history/mock/Jev/Kev predictors without a custom Python factory.
- The new bounded main QA agent supports a configurable chat-completions service,
  real-answer exact-match/F1 scoring, telemetry and an explicitly synthetic mock.
  Gold answers remain outside the model and scheduler inputs.
- Required waiting is aggregated per request, not weighted by task count. Frozen
  runs skip new tuning and validate the corpus as well as trace identities.
- Small pilot collections remain within development; collection refuses to
  overwrite manifested datasets. Incorrect candidate durations are benchmarked
  independently in new v2 collections. Frozen v1 data is preserved and labeled.
- Search score accumulation is deterministic across hash iteration orders. CLI
  provenance works without Git. Optional plotting can be disabled.
- Added configuration examples, API setup instructions, offline CI and consistent
  code formatting. Historical report numbers are explicitly marked as predating
  the corrections.

## Verification

- **67 unit/integration tests passed** with socket connections disabled, including
  Jev/Kev bearer/header/path contracts, malformed/oversized responses, timeouts,
  failures, cancellation races, duplicate requests and no-future-data boundaries.
- A standard-library-only run also passes, with optional HTTP contracts skipped.
- Ruff checks, formatting checks and Python bytecode compilation pass.
- Synthetic CLI comparison, including the privileged reference, runs without keys.
- System One mock replay ran on all 100 held-out tasks. The QA mock ran four tasks
  under each of three policies with zero failures and null quality scores.
- The scripted live harness ran 12 tasks under three policies. Every policy kept
  the fixed-window budget and returned identical required search evidence.
- The study completed 12 settings, two seeds and seven policies (168 aggregate
  runs). Frozen repetition produced identical `runs.json`, `comparisons.json`
  and `calibration.json`. Plot generation was omitted in this verification run.
- Missing Jev/Kev configuration exits with a concise error before creating run
  artifacts. Default preflight makes no network calls.
- A wheel builds with the declared isolated build environment. The existing
  virtual environment lacks setuptools, so an intentionally unisolated build
  was not usable; normal isolated packaging handles its declared dependency.

Local evidence is in `results/review-tests.log`, `results/review-study/`,
`results/review-repeated-study/`, `results/review-live/`, `results/review-mock/`,
`results/review-qa-final/`, `results/review-synthetic/`, and
`results/review-preflight/`. These generated artifacts are ignored by Git.

## Remaining empirical work

No claim is made that an unavailable provider account has been authenticated or
that real model quality/latency has been measured. Jev needs its credential; Kev
needs a separately running server. The optional main QA model needs its own
compatible endpoint/model and any required credential. Provider-specific request
formats may require adapter changes; the generic chat-completions contract is
covered by mocked HTTP tests.

The frozen data is still scripted retrieval, with v1 candidate-duration estimates.
The fixed candidate generator remains the documented observed-title heuristic,
not a reproduced learned generator from Speculative Actions. The live QA runner
performs independent model runs, not frozen paired LLM replay. Collecting real
LLM trajectories, running Jev/Kev context ablations and calibration, evaluating
answer quality, and producing the final research report still require experiments.
The core quota model remains fixed-window, serial-chain and single-process.
