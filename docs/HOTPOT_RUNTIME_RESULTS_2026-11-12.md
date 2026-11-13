# Live HotpotQA runtime results, November 12, 2026

**The full 20-question sequential/speculative comparison is complete. Mean
answer latency was 10.27% lower with speculation in this sample, but the paired
uncertainty interval includes zero. This does not establish a reliable
end-to-end latency benefit.**

This is actual concurrent execution, not the earlier serial agreement run or
a modeled timing replay. Forty real-model episodes used Gemini 2.5 Flash as
the actor and observation speculator through OpenRouter, the original prompts
and sampling settings, live Wikipedia Search, and the paper's seven-action
limit. Mode order alternated by question. No Jev, shared tool quotas or
artificial tool delay were used.

| Metric | Sequential | Speculative |
| --- | ---: | ---: |
| Mean answer latency | 6.659 s | 5.975 s |
| Median answer latency | 5.512 s | 4.956 s |
| p95 answer latency | 11.959 s | 11.221 s |
| Total answer time, 20 questions | 133.179 s | 119.495 s |
| Total resource time, including drain | 133.184 s | 124.809 s |
| Mean generated actions | 4.60 | 4.60 |
| Answer exact match | 35% | 30% |
| Answer F1 | 47.02% | 38.69% |
| Forced empty finishes at action cap | 5 | 7 |
| Inference requests | 92 | 204 |
| Billed model cost | $0.04765277 | $0.09480523 |

The mean paired saving was **0.684 seconds**, with a 5,000-resample paired
bootstrap 95% interval of **[-0.217, 1.568] seconds**. Positive saving favors
speculation. Resource-inclusive throughput was 1.067x sequential throughput
for one agent with work fully drained between episodes; this is not a
multi-agent saturation-throughput measurement.

Both modes ran the real actor on true observations. Original actor sampling
is stochastic: the action sequences were identical for only 9 of 20 pairs,
despite equal overall mean action counts. Differences in trajectory, quality,
network latency and provider timing prevent attributing the observed 13.684 s
aggregate difference solely to speculation. Empty forced finishes are retained
in the timing/QA outcomes and must not be interpreted as successful answers.

## What speculation accomplished

Speculation launched **24** Wikipedia searches and produced **3** exact cache
hits; **21** searches were unused. All three useful searches had completed
before the authoritative actor requested them. Their measured execution
overlap was **1.934 seconds**, and the resulting required-call waits were about
20–25 microseconds. This demonstrates useful live prefetching, but that local
overlap is far smaller than the overall observed runtime difference and is
not an independent causal estimate of end-to-end savings.

There were 59 observation-prediction requests and 53 speculative-actor
requests, costing $0.04588918 beyond the speculative run's authoritative actor
calls. **47** windows arrived too late to launch useful next searches.
Median authoritative actor latency was about 0.83 s in both modes; median
required Search latency was 0.74 s sequentially and 0.61 s speculatively.
Predictor/actor latency and variable live search latency leave limited useful
overlap. The original 100-token observation setting was preserved.

## Implementation and verification

The new [concurrent runtime](../src/quota_spec/hotpot_runtime.py) uses pinned
upstream prompt templates, action parsing and Wikipedia behavior. It isolates
prefetch environments, matches Search arguments exactly including case, joins
pending matching work, and applies real page state before authoritative
Lookup. Lookup/Finish are never executed on hypothetical state. Required work
does not await a late prediction. In-flight paid calls are drained for complete
billing, and leftover work cannot spill into the next episode.

All 40 episodes finished execution with **zero inference failures**, no
optional-operation failures and no unknown billed costs. Five sequential and
seven speculative episodes exhausted the action horizon. Peak observed paid
request concurrency was three.

The full suite passed **154 tests**, including real scheduling overlap under
controlled mock delays, late-observation/late-actor behavior, exact identity,
state isolation, optional-failure fallback and atomic concurrent dollar
reservations. An offline audit regenerated the saved summary exactly, verified
all runtime source hashes, and checked **184 authoritative prompt prefixes**
against their true observed histories. All started inference was drained.
Ruff and whitespace checks pass.

Total new spending was **$0.14245800**, below the separate $0.50 budget for
this user-requested experiment. Settled account usage increased by exactly
that amount, leaving **$4.334298405** in credit. No additional paid run was
started.

## Implication for the project

The runtime now demonstrates actual useful speculation, but this run is not
evidence that adding Jev will improve global throughput. The apparent 10.27%
mean reduction is uncertain and accompanies different QA outcomes and almost
double model cost. Preserve it as an inconclusive end-to-end result with a
small confirmed prefetch effect. A follow-up should separate provider/tool
variation and stochastic trajectories from the scheduling effect, and compare
faster observation models or explicitly labeled tool-latency regimes before
making the shared-quota throughput claim.

## Reproduction and evidence

- [Latency comparison chart](../results/hotpot-live-paired-20/latency-comparison.png)
- [Runtime commands and measurement semantics](HOTPOT_RUNTIME.md)
- [Generated report](../results/hotpot-live-paired-20/REPORT.md)
- [Machine-readable summary](../results/hotpot-live-paired-20/summary.json)
- [Prompt/timing/source audit](../results/hotpot-live-paired-20/audit.json)
- [Individual episodes](../results/hotpot-live-paired-20/tasks/)
- [Timestamped execution events](../results/hotpot-live-paired-20/events.jsonl)
- [Raw requests/responses](../results/hotpot-live-paired-20/requests.jsonl)
- [Settled cost audit](../results/hotpot-live-audit/account-final.json)
- [Exact paid source snapshot](../results/hotpot-live-audit/source-snapshot/)
- [154-test log](../results/hotpot-live-audit/tests-154.log)
