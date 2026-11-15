# Jev quota wins, November 15, 2026

The calibrated cross-agent method beats **both no speculation and allow-all** on
80 new held-out HotpotQA questions in matched replay. The primary setting was
locked using 20 development questions before evaluating these 80: **4 workers,
12 Search calls per 3-second fixed refill window**. Every started background
operation and the measured Jev request latency are charged.

| Policy | Mean task completion (s) | Whole-batch resource time (s) |
| --- | ---: | ---: |
| No speculation | 6.16362 | 126.70459 |
| Allow all | 6.74907 | 138.87022 |
| Our calibrated cross-agent method | **6.06693** | **124.85655** |

This is **1.57% / 1.46% less time than no speculation**, and **10.11% / 10.09%
less than allow-all**, respectively. These are time reductions, not inverted
throughput percentages. All ten paired question orders favor the method on both
endpoints against both baselines. Answers and authoritative trajectories remain
identical across policies; there is no ordinary required-result cache.

## Uncertainty and scope

We resampled complete questions 100 times and reran all three policies on each
resampled batch. The 95% question-bootstrap intervals for savings are:

| Baseline | Mean task saving (s) | Whole-batch saving (s) |
| --- | ---: | ---: |
| No speculation | [0.0313, 0.1605] | [0.3634, 3.6468] |
| Allow all | [0.3316, 1.0917] | [5.9883, 23.2227] |

The primary confirmation contains 240 saved schedules (three settings, eight
policies, ten orders) plus 300 question-bootstrap executions. It uses measured
native tool/model service and measured pooled Jev RTT, with sockets blocked,
zero forecast fallbacks and no latency scaling or outlier trimming. Collection
pacing and its mutex queue are excluded from tool service. Independent timing
checks cover all 542 Searches in the new 80-question capture.

These intervals condition on the fixed trained predictor, captured candidates
and measured service sample. They do **not** establish a live A/B gain under
changing providers or changed model trajectories. A separate four-question live
run of the final implementation passed its observed-context/quota audit: four
concurrent actors, 34 actual Jev calls, no actor/optional/forecast failures, one
exact prefetch hit. That is functional live evidence, not a paired speed test.

## What changed

- Reuse a persistent HTTPX AsyncClient for Jev on a dedicated event loop, with
  bounded concurrent calls and proper shutdown. A 32-pair development probe
  measured mean RTT 0.320 to 0.199 seconds. Model outputs were stochastic; we
  recollected pooled forecasts and charged their actual RTT rather than scaling
  the old bank or assuming identical predictions.
- Fit probability calibration only on the 20 development questions, matching
  the full episode-window context distribution used during admission.
- Stop starting speculative generation after observed ReAct step 4. Already
  generated candidates retain their episode lifetime; required actor execution
  is unchanged. This limit was selected on development data only.
- Retain observed-state cross-agent admission, exact-query reuse, required FIFO,
  answer-time worker release and accounting for all background work.

The primary averages 14.8 exact cache hits and 2.2 in-flight joins per 80-question
batch, with 126.5 unused speculative Searches versus allow-all's 254.4. More hits
alone are not the objective: avoiding quota interference matters.

## Controls and negative results

| Control at the primary setting | Mean (s) | Whole batch (s) |
| --- | ---: | ---: |
| Same generation budget, allow-all admission | 6.35764 | 130.83245 |
| Calibrated method, no generation budget | 6.07151 | 125.18464 |
| Uncalibrated pooled Jev | 6.19098 | 127.72337 |
| History-only admission | 6.11290 | 126.03275 |
| Development-tuned fixed reserve | 6.06322 | 125.09425 |

The fixed reserve slightly beats our mean, while our method slightly beats its
batch time. We do not establish superiority over this strong simple control.
Most of the gain survives without the generation budget; that budget alone
with allow-all admission does not recover the full improvement.

The first clean confirmation at 4 workers / 16 calls / 5 seconds **failed**
against no speculation. That primary failure remains in `native-confirmation`.
Actor-intent context was also explored on development questions and did not
consistently improve the fair calibrated comparison; it is excluded here.
An earlier apparently favorable confirmation had collection mutex wait included
in tool service. It is explicitly invalidated with `INVALID_TIMING.json`,
retained, and excluded by the dataset loader. Both timing and source data were
recollected before this result. Initial public Wikipedia 429 failures are also
retained and included in the cost total.

## Quota capacity and refill period

The fixed method was then mapped over **75 settings**: 2/4/8 workers, capacities
4/8/12/16/24, refill periods 1/2/3/5/10 seconds. All three policies were run on
three paired orders: **675 executions**. This is an exploratory held-out map;
it did not select or replace the locked primary confirmation.

It beats both baselines on both time endpoints in **13/75 cells**: 3/25 with two
workers, 6/25 with four, 4/25 with eight. These are descriptive mean comparisons,
not 75 separate significance claims. Wide quotas can favor unrestricted
speculation; long refill windows can make speculative mistakes costly. With
four workers, 24 calls / 10 seconds loses 17.23% mean time to no speculation,
while still beating allow-all. Capacity divided by refill period does not fully
characterize burst behavior.

![Four-worker quota/refill map](../results/quota-win-2026-11-15-replication-surface/quota-surface-4-workers.png)

[Two-worker map](../results/quota-win-2026-11-15-replication-surface/quota-surface-2-workers.png)
· [Eight-worker map](../results/quota-win-2026-11-15-replication-surface/quota-surface-8-workers.png)

## Evidence, cost and reproduction

[Locked protocol](../results/quota-win-2026-11-15-replication-protocol.json),
[confirmation result](../results/quota-win-2026-11-15-replication-confirmation/result.json),
[independent schedule/split audit](../results/quota-win-2026-11-15-final-report/audit.json),
[complete quota rows](../results/quota-win-2026-11-15-replication-surface/rows.json).
The confirmation directory preserves the exact executed source snapshot.

Additional API spending for this campaign is **$1.439993844**, including failed
and invalidated attempts and negative explorations. Actual request costs match
the account usage delta within floating-point precision; seeded forecast costs
are counted only at their original collection. [Itemized costs](../results/quota-win-2026-11-15-final-report/costs.json).
Final verification: **275 tests pass**, Ruff checks/formatting and whitespace
checks pass. Existing unrelated workspace changes remain intact; no commit or
publication was made.

Offline reproduction (choose fresh output directories):

```sh
.venv/bin/python -m quota_spec.quota_confirmation \
  results/quota-win-2026-11-15-replication-cohort \
  --bank results/quota-win-2026-11-15-replication-forecasts/bank.json \
  --calibration results/quota-win-2026-11-15-replication-calibration.json \
  --protocol results/quota-win-2026-11-15-replication-protocol.json \
  --bootstrap 100 --output results/quota-confirm-reproduction

.venv/bin/python -m quota_spec.quota_surface \
  results/quota-win-2026-11-15-replication-cohort \
  --bank results/quota-win-2026-11-15-replication-forecasts/bank.json \
  --calibration results/quota-win-2026-11-15-replication-calibration.json \
  --scope evaluation --agents 2 4 8 --capacities 4 8 12 16 24 \
  --windows 1 2 3 5 10 --seeds 248 249 250 --samples 32 \
  --generation-step-budget 4 --output results/quota-surface-reproduction
```

For a subsequent live experiment, use `quota_spec.multi_agent` with `--pooled-jev`,
`--generation-step-budget 4`, `--samples 32`, the replication calibration and
history dataset, and the chosen quota. Offsets through 241 have been used;
242 is the next unused seeded offset. A future live comparison should randomize
paired policy blocks and retain the simple tuned-reserve control.
