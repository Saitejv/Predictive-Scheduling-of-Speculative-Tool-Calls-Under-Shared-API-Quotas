# Throughput discrepancy and scheduler repair — November 13, 2026

Two multi-agent scheduler restrictions were fixed. The larger apparent
contradiction came from comparing independent live answer latencies with
fixed-work shared-quota batch throughput. No new model or Wikipedia calls were
made. The [manifest](THROUGHPUT_REPAIR_MANIFEST_2026-11-13.json) retains numerical
results and evidence hashes.

## Reconcile the live headline

| Accounting step | Mean seconds per question |
|---|---:|
| Independent live no-speculation run | 7.010763 |
| Speculative run’s saved path, executed without overlap | 6.395083 |
| That same saved path with speculative overlap | 6.193250 |
| Independent live speculative run | 6.246971 |

The observed 0.763792-second difference reconciles as
**0.615680 + 0.201832 − 0.053720 seconds**. The first term combines changed
authoritative paths and measured service times. The second is the fixed-path
scheduling effect. The final term is live versus service-playback overhead and
queueing. This is algebraic accounting, not causal attribution of the uncontrolled
path/provider difference. The original live paired interval remains −0.278 to
+2.002 seconds and includes zero.

The live campaign’s full resource time was 140.237 seconds without speculation
and 136.325 seconds with it. Its 15.276-second summed answer-latency reduction
therefore does not establish an equivalent throughput reduction. Both sets of
live paths and all original measurements remain immutable.

## Scheduler repairs

1. **Generation during quota waiting.** Prediction can start when the
   authoritative Search is requested, using the already-known query/history.
   Previously it waited for that Search to obtain quota. Full recorded
   generation service is still paid.
2. **Candidate retry.** Ready predictions blocked by required work or empty
   quota survive for reconsideration after dispatch/reset. Required calls retain
   priority. Requested/cached duplicates and candidates belonging to answered or
   expired questions are removed. An unused retry timer cannot inflate resource
   finish time.
3. **Main-worker release.** The named `overlap` profile takes a new question at
   answer readiness while retaining every started background operation and its
   cost/resource time. This existing capability is now exposed and selected by
   the multi-agent CLI. `legacy` retains release after drain.
4. **Oracle eligibility.** The old lateness-pruning proof applies to generation
   triggered at tool dispatch. Generation triggered at request can use source
   quota wait, so that pruning is disabled. This cohort has 27 conservatively
   useful candidate decisions in the new architecture, versus the old pruned 10.

A hand-calculated two-agent, 1-call/10-second fixture finishes in **22.1 seconds
before** and **21.1 seconds after** the first two repairs. Prediction starts at
request time 0.2 seconds, becomes ready at 12.2 seconds and launches at the
20-second reset. Its source itself obtained quota only at 10 seconds. Starting
generation at source dispatch misses this opportunity. Tests also cover expiry,
required priority, duplicate suppression, background drain and historical modes.

## Same work, corrected profile, 20 questions

These are native saved durations, equal ordinary exact-query caching on both
sides, and means of three paired orders. Times cover the entire batch and every
started background operation. The gate column is a **feasible ideal pipeline
admission schedule**, found using future recorded actions. Selected generation
and tool service are fully charged. Large gate searches are **not certified
global optima**; no performance ceiling is inferred from a best-found result.

| Shared Search quota | Agents | No speculation s | Feasible ideal gate s | Seconds saved | Throughput change |
|---|---:|---:|---:|---:|---:|
| Nonbinding | 1 | 126.306 | 122.269 | 4.037 | +3.301% |
| Nonbinding | 2 | 66.023 | 63.287 | 2.736 | +4.300% |
| Nonbinding | 4 | 34.398 | 33.518 | 0.880 | +2.662% |
| Nonbinding | 8 | 20.098 | 20.070 | 0.027 | +0.147% |
| 12 per 30 s | 1 | 164.584 | 164.366 | 0.218 | +0.136% |
| 12 per 30 s | 2 | 158.088 | 157.321 | 0.767 | +0.486% |
| 12 per 30 s | 4 | 155.484 | 154.954 | 0.529 | +0.336% |
| 12 per 30 s | 8 | 155.119 | 154.006 | 1.113 | +0.717% |
| 6 per 60 s | 1 | 661.221 | 661.221 | 0.000 | +0.000% |
| 6 per 60 s | 2 | 661.174 | 661.174 | 0.000 | +0.000% |
| 6 per 60 s | 4 | 660.670 | 660.662 | 0.008 | +0.001% |
| 6 per 60 s | 8 | 661.059 | 661.059 | 0.000 | +0.000% |

The same audit retains ungated controls and legacy controls. More overlap alone
can hurt under a shared quota: wrong predictions now have more opportunities
to consume capacity. The improvements above require ideal admission; they are
not demonstrated benefits of an online learned gate.

## Small-batch tails versus repeated workload

Twenty questions can end on a slow question with no useful predictions. In the
nonbinding eight-agent seed-248 case, question 2038 finishes last. Its own
9.160509-second duration is unchanged; speculation starts it only 0.082270
seconds earlier, while mean per-question latency improves by 0.201832 seconds.
Mean question latency and final batch completion therefore respond differently.

This diagnostic repeats the same 20 saved questions 15 times, assigning a fresh
episode-local cache to each repetition. It reuses the 20-question gate selection.
It is **synthetic repetition of the recorded mix**, using native service times
and no added tool delay. It is not 300 fresh questions, a live benchmark, or a
global optimum for the repeated stream.

| Nonbinding quota, agents | No speculation, 300 questions s | Feasible gate s | Seconds saved | Throughput change |
|---:|---:|---:|---:|---:|
| 1 | 1894.584 | 1834.034 | 60.550 | +3.301% |
| 2 | 949.920 | 918.930 | 30.990 | +3.372% |
| 4 | 476.310 | 461.129 | 15.181 | +3.293% |
| 8 | 240.949 | 233.805 | 7.144 | +3.056% |

With nonbinding quota, the throughput improvement persists near 3% across worker
counts, consistent with the controlled per-question saving. The repeated 12/30 s
controls range from +0.009% to −0.056%; repeated 6/60 s controls have zero gain.
Reusing a small-batch selection does not tune a sustained-stream policy.

## Independent quota limit

These fixed paths require **67 distinct episode/query executions**, even with
ordinary caching and perfect useful speculation. Speculation can move those
executions earlier but cannot erase their quota consumption. With an empty
initial cache and a full aligned initial quota window:

```text
last mandatory dispatch >= floor((67 - 1) / capacity) × reset period
full batch finish >= last mandatory dispatch + minimum available Search service
```

The minimum eligible recorded service is approximately 0.231 seconds. This gives
batch lower bounds of **150.231 seconds at 12/30** and **660.231 seconds at 6/60**.
The two-agent 6/60 baseline averages 661.174 seconds, leaving at most about
0.943 seconds of batch reduction under this conservative bound. Even an
unrestricted ideal scheduler within this fixed-call/cache/quota model cannot
produce an 11% throughput gain there. Actor dependencies, generation availability
and FIFO priority can make the actual optimum slower than this bound.

A pre-reset token can help when it would otherwise go unused; the separate hand
fixture verifies that mechanism. The tight-quota baseline already dispatches its
final mandatory execution at the earliest possible reset. Completion never
refunds quota.

## Validation and evidence

- **249 tests passed**, with Ruff lint/format checks. New tests cover quota-wait
  overlap, reset retries, stale timers, unchanged historical behavior, equal-work
  reconciliation, quota bounds and episode-local repeated-stream caches.
- **270 saved legacy schedules reproduce every prior metric with zero
  residual**, including duplicate counts and resource finish time.
- **72 setting/order/profile cases**, 288 policy rows and 36 repeated-stream
  cases validate quotas, worker limits and preserved answers. Aggregates were
  independently recalculated; all schedules respect the separate quota bound.
- Evidence is retained under
  `results/speculation-throughput-repair-2026-11-13/release-verified/`: stage-level
  live accounting, source/configuration, full event schedules, raw per-order rows,
  aggregate summaries and repeated-stream summaries. The repair root retains
  protected input hashes, test logs and the historical reproduction result.

Replay holds saved model/tool service fixed and assumes unlimited provider
concurrency beyond the Search quota. It does not measure live serving contention
or changed answer quality. No Jev/Kev calls were made. Ideal schedules use future
knowledge for diagnosis and are not deployable admission policies.

## Reproduction

```sh
make throughput-check OUTPUT=results/throughput-check-fresh
.venv/bin/python -m quota_spec.frozen_replay \
  results/async-agent-cleanup-2026-11-13/pilot-dataset \
  --output results/multi-agent-fresh --agents 1 2 4 8 \
  --capacity 12 --window-s 30 --scheduling overlap --cache-required-results
make test
make lint
```

These commands use local saved evidence and require no paid inference.
`--scheduling legacy` retains the older worker/generation/admission architecture.
