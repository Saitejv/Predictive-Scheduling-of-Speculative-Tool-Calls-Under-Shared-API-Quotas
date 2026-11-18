# Testing quota awareness plus other-agent awareness

The combined `quota_team` query planner is **not a consistent improvement over quota-only planning** in this controlled test. At eight workers with fast Search, it cuts average queued-work latency by **5.03%** and batch time by **5.11%** relative to quota-only, in both question orders. At four workers with fast Search it is **6.33% slower** on queued-work latency, and slow-search differences versus quota-only are small or reverse between orders. Both quota-aware variants help in the slow-search scenarios relative to no speculation.

## Main result: time from submitting the workload to an answer

**Seconds, lower is better.** All 16 questions are treated as submitted at time zero, with four or eight active workers. This measure includes waiting for a free worker. Each cell averages two question orders, with new planner API samples in each order. The same authoritative paths, tool observations and answers are fixed across methods. Search response times are explicitly configured counterfactual values, not newly measured native Search times.

| Workers | Quota | Search | No speculation | Full speculation | Quota aware | Quota + agents |
|---:|:---|---:|---:|---:|---:|---:|
| 4 | 8/5s | 0.1s | 15.56 | 21.77 | 16.46 | 17.50 |
| 4 | 8/5s | 3s | 29.54 | 29.54 | 27.04 | 26.97 |
| 8 | 12/3s | 0.1s | 6.74 | 8.70 | 7.53 | 7.15 |
| 8 | 12/3s | 3s | 17.35 | 15.78 | 15.46 | 15.46 |

- **4 workers, 8 calls/5s, 0.1s Search:** extra peer context hurts. Quota-only averages four speculative searches per batch, three unused; the combined planner averages eight, five unused. The paired histories suggest that increased speculative quota use is a failure mechanism. This is an observation from the traces, not a separate causal isolation of that mechanism.
- **8 workers, 12 calls/3s, 0.1s Search:** combined improves over quota-only by 5.03%, but no speculation is still faster (**6.74 vs 7.15s**). Both question orders favor combined over quota-only on queued-work latency and batch time.
- **4 workers, 8 calls/5s, 3s Search:** combined improves on quota-only by just **0.27%** on queued-work latency, but its batch takes **0.45% longer**. The order-by-order result reverses. Both quota-aware styles beat no/full speculation on the aggregate mean and batch endpoints.
- **8 workers, 12 calls/3s, 3s Search:** queued-work latency is essentially tied between quota-only and combined (combined is **0.02% slower** before rounding). Combined's worker-relative latency looks 0.89% faster, which does not translate to a queued-work improvement. Full speculation has the shortest batch here.

These are two samples of question order and planner randomness on 16 reused evaluation questions. They establish neither a population-level effect nor a universal winning policy. No policy is selected as a new default from this test.

## Whole-batch completion time

This includes all started optional work, including unused searches and planner requests finishing after an answer. It measures how quickly resources are free for subsequent work.

| Workers | Quota | Search | No speculation | Full speculation | Quota aware | Quota + agents |
|---:|:---|---:|---:|---:|---:|---:|
| 4 | 8/5s | 0.1s | 29.23 | 41.55 | 31.77 | 31.77 |
| 4 | 8/5s | 3s | 58.04 | 55.65 | 51.30 | 51.54 |
| 8 | 12/3s | 0.1s | 12.39 | 17.73 | 14.48 | 13.74 |
| 8 | 12/3s | 3s | 33.86 | 29.82 | 31.80 | 31.59 |

For continuity with earlier reports, latency **after worker dispatch**, excluding waiting for a worker, is shown separately:

| Workers | Quota | Search | No speculation | Full speculation | Quota aware | Quota + agents |
|---:|:---|---:|---:|---:|---:|---:|
| 4 | 8/5s | 0.1s | 6.60 | 9.66 | 7.01 | 7.39 |
| 4 | 8/5s | 3s | 12.10 | 11.91 | 10.82 | 10.87 |
| 8 | 12/3s | 0.1s | 4.85 | 6.47 | 5.36 | 5.19 |
| 8 | 12/3s | 3s | 12.10 | 10.87 | 10.73 | 10.63 |

Do not compare the queued-work numbers in the first table directly to worker-relative numbers in earlier reports. Their starting clocks differ. Both are derived from the same unmodified schedules: queued-work latency is the mean of `task_finish_s` for a workload submitted at zero; worker-relative latency subtracts `task_start_s`. No timings were rescaled or outliers removed.

## What was tested

This uses the **actual query-generation prompt** shared by `--speculation-planner quota` and `--speculation-planner quota_team`. It is not the earlier fixed-candidate accept/reject gate. Gemini 2.5 Flash makes fresh Search proposals, without being restricted to previously saved candidate queries. Quota-only sees API state and worker counts; combined sees those same fields plus bounded observed peer questions, progress, phases, elapsed times, returned actions, real result excerpts and last returned intent. The main actor never receives that extra context.

Full speculation uses the same planner prompt with no quota/peer payload and admits every valid generated Search subject to the shared hard quota, duplicate suppression and required FIFO. It is quota-blind, rather than forced to issue three queries even when the model abstains. All three speculative styles use the same generation-step budget of four, width of three and exact-match reuse rules. No speculation does not run the optional branch.

The test covers four settings × three speculative styles × two orders: **24 paid planner schedules**, plus **eight no-speculation schedules**, for **32 schedules / 512 replayed episode completions** on **16 distinct questions**. The 16 questions are from the historical evaluation cohort, separate from the 20-question calibration/development set but already explored in previous work. This is not a fresh held-out confirmation. Order seeds are 248 and 249.

The actual query planner made **765 successful API calls** in the completed matrix. Its measured round-trip time is charged asynchronously: authoritative work advances while inference is outstanding, and a proposal cannot launch before its response arrives. The prior observation-prediction prefix and its measured latency are held fixed; the hypothetical query-generation stage is replaced by the current planner. API input/output records and exact prompt provenance are retained. There are no new main-actor API calls in this controlled matrix.

Every required Search and every fresh optional Search has the same configured response time within its cell. Unknown unused queries need no materialized tool observation because an actor never consumes them. Exact matches reuse the verified captured required-query observation; the main trajectory, including Lookup state and outputs, remains fixed. This is a scheduling sensitivity experiment with an unlimited simultaneous provider-service model, not a live end-to-end Wikipedia benchmark. The preceding native checks remain separate functionality evidence.

## Validation and implementation checks

The independent audit verifies all 32 schedules and **765 generation contexts**: fixed authoritative actions and answers, dataset/tool-result integrity, quota windows, required FIFO, observed peer state, exact archived prompt reproduction, raw model outputs and delayed launch after the real planner round trip. All current schema outputs are free Search query lists, rather than a fixed-candidate enum. Captured hypothetical prefixes come from verified earlier observation predictions, not hidden future action labels.

The test exposed an input-statistic mismatch: replay counted offered required Search actions including exact cache hits, while live execution counted only cache misses entering its queue. Live execution now counts offered Search demand at the returned-action event, matching replay. It does not double-count misses or consume quota for cache hits. A regression test checks both counts, and the live context audit verifies the new event-derived count. Historical recordings retain their archived earlier behavior.

All **291 tests pass**, and Ruff passes for **140 files**. The fresh-generation replay hook requires an explicit Search service assumption; tests reject an unspecified native timing and verify that slow planner inference cannot delay the authoritative path directly or inject future observations. Source snapshots and compressed schedules remain available.

## Provider errors, storage and costs

An initial unpaced attempt stopped on upstream shared-provider rate limiting. It retained one complete style case and part of the next: **58 API attempts**, including five HTTP 429 failures. That incomplete trial is not mixed into the completed comparison.

The completed matrix predeclares a 0.75-second collection gap after each finished request. That collector-only pacing is recorded separately and excluded from simulated planner service time. Actual API retry/backoff would remain charged; the paced matrix had **zero failures and zero retries**. This does not imply a deployed service would escape upstream limits.

New known API charges are **$0.35091159 across 823 total attempts**, including the stopped trial. They reconcile exactly with the provider's settled account-usage delta. Five failed attempts have no individual cost receipts and retain a conservative **$0.0354497** reservation; the total budget charge including that reservation is **$0.38636129**. No API key or provider limit was changed.

Low disk space was addressed by verified transparent filesystem compression of 27 older JSONL logs. Every original file path and SHA-256 content identity is preserved; no recording was removed. The two storage manifests retain hashes and physical allocation changes.

## Artifacts and reproduction

[Aggregate CSV](evidence/quota-team-test-2026-11-17/aggregate.csv), [per-order comparisons](evidence/quota-team-test-2026-11-17/order-comparisons.json), [independent audit](evidence/quota-team-test-2026-11-17/audit.json), [protocol](evidence/quota-team-test-2026-11-17/protocol.json), [costs including the stopped attempt](evidence/quota-team-test-2026-11-17/costs.json).

```sh
# Spends API budget using the configured OpenRouter environment:
.venv/bin/python scripts/test_quota_team.py --output results/FRESH-quota-team --count 16 --seeds 248 249 --max-usd 2
.venv/bin/python scripts/audit_quota_team_test.py results/FRESH-quota-team
.venv/bin/python scripts/report_quota_team_test.py results/FRESH-quota-team --output results/FRESH-quota-team-report
```

Raw matrix: `results/quota-team-test-2026-11-17-paced`. Stopped attempt: `results/quota-team-test-2026-11-17-controlled`. All source snapshots, source prefix checksums, raw API receipts, output queries, latencies, schedules and failures are retained. The combined planner remains available as an experimental option; this test does not justify replacing quota-only planning everywhere, or promoting it over Jev.
