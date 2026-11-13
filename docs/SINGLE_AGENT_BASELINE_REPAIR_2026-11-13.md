> Historical next-action reproduction. The newer runtime defaults to episode-long
> windows; select `--candidate-lifetime next_action` to reproduce the timing
> figures below. See [current validation](ASYNC_SPECULATION_VALIDATION_2026-11-13.md).

# Original single-agent baseline: source check and repair

**Found and fixed: the default `make live` benchmark inserted a shared 1.1-second delay between model requests.** Speculation adds requests, so that gate lets optional work delay the authoritative actor. This was capture pacing being used as the benchmark default.

The previous agent-count table also answered the wrong baseline question: it imposed a shared Search quota and used a common required-result cache. It was not the original one-agent, no-quota comparison. Those extension results remain preserved, but must not stand in for the baseline.

## What changed

- `make live` now selects `--purpose benchmark` and removes artificial submission pacing.
- `make capture` explicitly selects capture purpose and retains adjustable collection pacing, defaulting to 1.1 seconds.
- The CLI rejects positive HTTP submission intervals under benchmark purpose **before output creation, source downloads, credentials or requests**. Collection requires explicit `--purpose capture`.
- `make single-agent-check OUTPUT=...` now runs the source comparison and saved-data validation offline.
- The Runtime accepts an optional clock and local-step adapter for deterministic testing. Live defaults remain the normal clock and upstream environment. The prefetch, joining and authoritative actor algorithm is unchanged.
- README/runbook/handoff now distinguish the single-agent baseline, paced collection and shared-quota experiments. The primary original-style baseline retains the speculative-result cache; caching required results too is a separately labeled ablation.

A regression using the actual `LiveChat` transport, a mock HTTP endpoint and a deterministic clock demonstrates the bug directly. It keeps the same two authoritative requests, with or without one optional request during the required Search:

| Submission configuration | Actor completion without optional request | With optional request |
|---|---:|---:|
| Old shared 1.1 s gate | 1.11 s | 2.21 s |
| Fixed benchmark, no artificial gate | 0.06 s | 0.06 s |

These are controlled fixture seconds, not new provider measurements. They isolate the extra delay introduced by the shared submission gate.

## Checked against the authors' actual code

Read [the original paper](https://arxiv.org/html/2510.04371v2) and the pinned [authors' repository](https://github.com/naimengye/speculative-action/tree/dc938b9ef7474caf07fe4ad16549c1fa8c7d268c). The public checkout remains unchanged at `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c`.

The paper's approximately 20% time-saving result is from **chess**. HotpotQA's Figure 4 evaluates next-action agreement. They are different experiments, so that timing improvement is not a published HotpotQA target.

The new check executes the authors' unchanged `analyze_with_truncation` function from `chess-game/guess_analysis.py` on their five public top-three chess samples, at 30 steps. An independently written two-call recurrence gives identical sequential and speculative times for every sample:

| Original chess sample | No speculation, seconds | Speculation, seconds | Seconds saved |
|---|---:|---:|---:|
| 32831f2d… | 6,445.209 | 5,481.155 | 964.054 |
| 4c277d18… | 5,538.728 | 4,336.878 | 1,201.850 |
| 53456583… | 7,947.414 | 5,487.005 | 2,460.409 |
| cd188ca0… | 7,169.380 | 5,909.643 | 1,259.737 |
| dd15e5bd… | 6,152.448 | 5,382.062 | 770.385 |

The mean of the five per-run time-saving percentages is **19.5416%**, recovering the paper's approximately 19.5% result. The timing check therefore recovers a large improvement when run on the actual original timing workload. No new chess inference was performed.

For a correct prediction, the independent reference groups two calls as `max(current_call, prediction + next_call)`; a hit skips the next speculation window, matching the authors' implementation. It also checks misses and a slow predictor that loses time. This is checked against the actual original function, not a rewritten copy presented as upstream.

## Checked the actual HotpotQA Runtime, independently of its event simulator

The new playback adapter calls **`Runtime.episode`**, the same asynchronous code used by the live baseline. It supplies the exact saved model prompts/responses, original parser, true Wikipedia result states and recorded service times. It uses an asyncio service-time clock to avoid new paid requests or long sleeps; this is saved-output execution, not a new live speed measurement.

All 50 canonical HotpotQA paths run in both sequential and speculative modes. Every executed model prompt must match its saved prompt exactly; every authoritative action and final answer must match its tape. Both completed reuse and in-flight joins execute through the real runtime. Answer time, drain time, prefetch counts and cache hits match the separate quota-free scheduler; the independent scalar recurrence also matches.

**All 100 task/mode checks match, with zero timing residual and zero optional failures.** This verifies the concurrent pipeline rather than merely trusting the previous simulator.

The restored baseline uses one agent, no Search quota, no Jev, no artificial submission pacing and the original speculative-only result cache:

| Fixed 50-path HotpotQA comparison | No speculation | Speculation | Saving |
|---|---:|---:|---:|
| Mean answer seconds per question | 8.902 | 8.749 | 0.153 s |
| Sum of answer seconds across the 50 paths | 445.096 | 437.466 | 7.630 s |

This genuinely small native scheduling benefit remains after the benchmark is separated correctly. Its concrete cause is timing: recorded Search service averages **0.707 s**, while observation prediction plus hypothetical reasoning averages **1.855 s**. On these 151 prediction windows, 54 match the next authoritative action exactly; 37 are correct next Searches, and only 10 of those meet the original one-step generation deadline. Correct Finish/Lookup predictions do not hide Search work. These opportunity counts are not the number of eventual cache hits, since farther-ahead candidates and repeated reuse also exist.

The paper's framework assumes a faster predictor and an expensive pending API. The chess data satisfy that useful overlap regime much more often. Our subsecond Wikipedia calls often finish before the two model stages can generate a useful Search. Correct code cannot turn late predictions into earlier results.

The pacing bug affects paced live/capture wall times and the old default live command. It does **not** explain away the small fixed-path result: frozen replay already excluded local collection queues. The new actual-runtime check confirms that distinction. Removing pacing repairs the benchmark protocol; it does not retroactively create a 20% HotpotQA speedup in saved data.

## Validation and retained evidence

- **228 tests pass**, including 12 new source/timing/benchmark regressions; lint and formatting pass.
- The actual async runtime recovers controlled overlap: **8.7 → 4.7 seconds** for completed reuse, and **11.7 → 10.4 seconds** for an in-flight join. Late generation never blocks the authoritative answer.
- The old 20-question unpaced paid result remains unchanged: **6.659 → 5.975 seconds** observed mean answer time, with differing actor paths and an uncertainty interval including zero. It remains measured evidence, not a guaranteed scheduling effect.
- All protected paid data and earlier audit artifacts remain unchanged. Source before/final snapshots and exact traces are under `results/upstream-speculation-repair-2026-11-13/`.
- No new paid inference, model spend or external Wikipedia requests. A newly measured live improvement after this fix has **not** been claimed.

Offline reproduction, using a fresh output directory:

```sh
make single-agent-check OUTPUT=results/single-agent-check-fresh
make offline OUTPUT=results/hotpot-smoke-fresh
.venv/bin/python -m unittest discover -s tests -q
make lint
```

Future paid execution uses `make live OUTPUT=results/hotpot-live-fresh`. Paced collection uses `make capture OUTPUT=results/hotpot-capture-fresh`. Neither command was run against a real provider during this repair.
