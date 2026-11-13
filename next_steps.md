# Current handoff

Updated November 13, 2026. Work in this repository; preserve paid recordings and
unrelated local changes. The detailed earlier handoff is retained in
[research history](docs/RESEARCH_HISTORY_2026-11-13.md).

## Active implementation

- `src/quota_spec/hotpot_runtime.py`: actual async one-agent benchmark, true actor
  observations, exact-query speculative cache and full background drain.
- Default observation model: GPT-4.1 nano; actor/hypothetical model: Gemini 2.5 Flash.
- Windows remain valid until the answer. Generation and tool execution continue
  during actor thinking and after intervening actions; duplicate requested/cached
  queries are suppressed. `next_action` explicitly selects historical expiry.
- Main actor has a reserved inference slot. Benchmark requests are unpaced;
  capture pacing requires explicit capture purpose.
- Recorder endpoint fields reconcile answer/resource/drain times. Actor spans,
  prefetch launches, successful cache reuse/joins and all paid requests are recorded.
- New completed tapes retain candidate-lifetime metadata; replay follows it.
  Mixed lifetimes require an explicit replay selection rather than silent coercion.

## Validation

Read [the current validation report](docs/ASYNC_SPECULATION_VALIDATION_2026-11-13.md).
The new paired live pilot covers the first 20 intended questions, in two blocks
of ten, with a combined authorized model-spend cap of $0.50. Live answer times
are exploratory; stochastic paths and provider variability prevent assigning
all observed speedup to prefetching. Keep answer and all-work metrics separate.

The source tests demonstrate dispatch during actor thinking, in-flight joining,
retention across a Lookup, duplicate suppression, reserved actor capacity, full
background accounting and rejection of corrupted recording times. The actual
runtime, frozen scheduler and an independent scalar calculation are compared
on retained complete tapes. Synthetic tool scaling is explicitly labeled.

Fresh evidence is under `results/async-agent-cleanup-2026-11-13/`; old paid data
and earlier audit bundles remain unchanged. `scripts/verify_live_speculation.py`
recomputes live timing, request, cost and cache evidence from the recorded files.

## Useful commands

```sh
make offline OUTPUT=results/smoke-fresh
make test
make lint
make live OUTPUT=results/live-fresh MAX_USD=.50
.venv/bin/python -m quota_spec.capture_audit results/live-fresh
make single-agent-check OUTPUT=results/reference-fresh
```

The live command is paid; other commands above use mocks or saved evidence after
public source preparation. Bank completion over HTTP is also paid and needs a
separate explicit budget. Earlier permission for this task covered a total of
$0.50; do not treat it as a standing authorization for later experiments.

## Next research work

Confirm the single-agent effect on fresh questions before claiming a general
speedup. Then evaluate shared-quota admission on the same recorded paths,
retention and costs. Existing Jev banks remain native-timing forecasts with
phase-entry elapsed=0; avoid silently using uncovered persistent contexts.
Kev is deferred. The historical quota/cache studies are not replacements for
the one-agent no-quota benchmark.
