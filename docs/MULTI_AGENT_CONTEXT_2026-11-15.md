# Live multi-agent context engine — November 15, 2026

The Jev-controlled multi-agent system now runs end to end against real models
and Wikipedia. Eight authoritative agents can work concurrently under one shared
Search quota. Offline auditing verifies their exact prompts, true observations,
state transitions, quota ledger and Jev inputs. Performance remains a research
result: cross-agent admission avoids substantial harm from speculation, but these
experiments do not establish a general throughput advantage over no speculation.

## Implementation

- `multi_agent.py` runs the pinned upstream ReAct actor through the existing
  `hotpot_runtime.Runtime`. Required observations remain authoritative; hypothetical
  Lookup/Finish actions cannot alter the environment.
- `context_engine.py` maintains each active task's observed phase, completed-action
  count, recent calls and bounded result excerpt. Optional Search results never
  enter this registry before the actor requests them. Evaluation answers are not
  passed to Jev or admission.
- Forecasts run asynchronously and in parallel, outside the event loop. Identical
  in-flight requests are coalesced. A bounded 1,024-entry cache retains forecasts
  within an unchanged logical phase for at most 0.5 seconds by default. Its key
  omits elapsed time; the saved request retains the actual elapsed time at the
  cache miss. This is an explicit short-lived approximation, not an exact-time
  forecast. Owner candidate strings remain part of the cache key.
- `--context task|history|progress|no_history|no_progress` controls Jev inputs.
  The scheduler still sees the same observed quota and registry. Both full and
  own rules forecast every active agent; only the gain objective differs.
- The final, synchronous claim checks current quota usage, reset window, required
  queue and agent revisions. Concurrent sibling approvals cannot spend against
  the same old ledger. Changed contexts receive at most one fresh forecast round.
  Ready candidates can survive quota resets until their owning episode ends.
- Required Search requests retain FIFO priority. Each dispatch consumes quota
  exactly once, including failed executions. Completion never refunds it. Cache
  identity is the exact, case-sensitive query within an episode; ordinary caching
  of required results and cross-episode sharing are disabled for these live runs.
- Workers take new questions when answers are ready. Every started background
  request drains, remains costed and contributes to resource makespan. Optional
  inference has its own concurrency limit; one global serving slot per actor is
  reserved from optional requests.
- Unsent drafts whose owners have answered are skipped before HTTP dispatch.
  Started requests are drained. HTTP 429/502/503/504, transport failures, malformed
  gateway JSON and empty provider output receive at most two retries by default.
  Each attempt has its own immutable capture node and request record.
- A request with missing cost metadata is charged its conservative reservation
  against the budget, while its actual cost stays **unknown** in telemetry.
  A provider error therefore cannot silently receive free retries or disable all
  later actors. Dollar/request reservations remain atomic across concurrent calls.

The original single-agent defaults are preserved. The new driver enables the
multi-agent coordination and retry behavior. `--draft-actor` and `--width 1` are
explicit candidate-generator ablations; the default remains the upstream-style
three-candidate hypothetical actor with Gemini 2.5 Flash. Observation prediction
uses GPT-4.1 nano. The requested Jev model was `typesafe/jev-1.14`; responses
identified `typesafe/jev-1.14-20261014` through OpenRouter's decisions endpoint.

The source framework is [Speculative Actions](https://arxiv.org/html/2510.04371v2).
Jev's structured probability interface is documented by
[TypeSafe](https://docs.typesafe.ai/api/system-one) and
[OpenRouter](https://openrouter.ai/blog/insights/what-is-jev/).
Our cross-agent shared-quota rule is a project extension, not a result claimed
by that paper.

## Validation and live experiments

**266 tests pass**, including quota races, FIFO cancellation, reset retention,
expired candidates, background drain, forecast single-flight, concurrent dollar
reservations, observed-state isolation, context ablations and calibration-label
isolation. A full HTTP-fixture run injects a non-JSON 502 response, recovers through
a separately recorded retry, and passes the independent context/capture audit.
Ruff lint, formatting and whitespace checks pass.

The campaign retains **236 paid live episodes**. Twelve episodes failed during
two earlier runs: one provider 502 with no cost metadata caused the old transport
to block 11 later episodes, and a separate non-JSON gateway response exposed the
JSON parsing/retry bug. Both runs remain intact and are excluded from performance
comparisons. The final repeated eight-worker run completed all 16 episodes with
zero actor or optional failures. There are **200 episodes in fully successful,
independently audited runs**, plus the initial four-episode integration probe.
Successful episodes inside the two failed runs remain recorded but are not used
as complete-run performance evidence.

The initial four-worker comparison used 12 questions at seeded offsets 54–65,
shared quota 12 calls/10 seconds, width three, and two optional inference slots.
These are **independent live paths**, with different model outputs and service
latencies. The reserve control reserves exactly one slot; it is not tuned.

| Policy | Mean completion s | All-work batch s | Prefetches | Exact hits | EM |
|---|---:|---:|---:|---:|---:|
| No speculation | 8.616 | 31.828 | 0 | 0 | .667 |
| Current capacity | 16.386 | 60.537 | 38 | 3 | .500 |
| Fixed reserve 1 | 21.484 | 73.921 | 45 | 0 | .500 |
| History full | 9.446 | 32.775 | 3 | 0 | .667 |
| Jev own | 9.346 | 35.842 | 7 | 0 | .500 |
| Jev full | 9.553 | 35.521 | 5 | 0 | .667 |

This established live admission and protection from excess optional work. It did
not establish a cache benefit for Jev: both Jev runs had zero useful prefetched
results. Optional inference queueing averaged about two seconds in the full-Jev
run, motivating the explicit serving-capacity repair.

A second, original eight-worker cohort used offsets 66–81 and 12 calls/10 seconds.
It includes the provider-502 failure described above. All original results,
including that failed run, remain in the campaign report.

The repaired eight-worker cohort used offsets 82–97, 12 calls/5 seconds, one
optional inference slot per worker plus actor reservations, and all the final
transport fixes. The last fast-Jev row is the successful repeat after correcting
the non-JSON error handling.

| Policy / candidate variant | Mean completion s | All-work batch s | Prefetches | Exact hits | EM |
|---|---:|---:|---:|---:|---:|
| No speculation | 9.111 | 24.133 | 0 | 0 | .375 |
| Calibrated full Jev / original width 3 | 8.539 | 23.747 | 5 | 0 | .563 |
| Current capacity / nano draft, width 1 | 13.883 | 36.667 | 27 | 5 | .375 |
| Calibrated full Jev / nano draft, width 1 | 9.845 | 27.827 | 2 | 0 | .375 |

The small live latency delta in the second row cannot be attributed to useful
prefetching: it has zero hits. Different authoritative paths, quality and provider
service times remain confounders. The fast generator produces useful predictions
in its ungated control, but its unused calls still harm shared-quota completion.
No confirmatory live speedup claim or confidence interval is made.

## Development-only calibration

`probability_calibration.py` fits decile bins with Beta(1,1) smoothing and weighted
monotone pooling, using **only the original 20 development questions**. The
separate 30-question cohort is used for scoring, never for fitting maps. Conditional
reuse and continuation are scored only where a future Search actually exists.
Evaluation-label mutation tests verify that fitting does not read held-out labels.

| Forecast | Evaluation raw Brier | Calibrated Brier |
|---|---:|---:|
| Exact candidate reuse | .242090 | .127697 |
| Another Search needed | .163339 | .165157 |
| Continuation after next Search | .246641 | .257426 |

Reuse improves substantially; the other two scores regress slightly. Calibration
is an explicit option, not an unqualified improvement. It was trained on
phase-entry elapsed=0 contexts; transfer to live elapsed times and persistent
candidates is approximate. Live runtime checks model, context mode and development
IDs before applying an artifact. Raw provider probabilities remain saved alongside
transformed probabilities.

## Same-work replay: cross-agent protection is real, baseline win is limited

A complete **3,054-context** episode-window bank was assembled by reusing 1,885
saved contexts and purchasing 1,169 missing ones. All calls succeeded; new bank
collection cost **$0.034534206**. Replay makes no inference requests.

The matched study uses the same historical 20-development/30-evaluation cohort,
measured native Search times, identical saved actor/candidate outputs and answers,
and the repaired overlap scheduler. It evaluates three quotas, worker counts
1/4/8, three paired order seeds and eight policies: **216 complete replays**.
All run with sockets blocked, with zero forecast fallbacks. Each logical forecast
still incurs its saved latency and cost. No synthetic tool slowdown is added.
Reserve selection uses development questions only. Native service times assume
unlimited provider concurrency in replay; this is distinct from the measured
live serving-capacity controls.

Mean task completion, seconds; means of three paired order seeds:

| Quota | Workers | No speculation | Tuned reserve | Raw own | Raw full | Calibrated own | Calibrated full |
|---|---:|---:|---:|---:|---:|---:|---:|
| 12 / 5 s | 4 | 10.546 | 10.574 | 11.542 | 10.892 | 11.066 | 10.613 |
| 12 / 5 s | 8 | 13.287 | 13.287 | 16.173 | 13.305 | 15.095 | 13.287 |
| 12 / 10 s | 4 | 12.883 | 13.163 | 16.272 | 13.619 | 14.394 | 12.988 |
| 12 / 10 s | 8 | 20.700 | 20.700 | 26.617 | 20.811 | 24.323 | 20.700 |

At eight workers and 12/5 seconds, raw full admission improves mean completion
about **17.7% versus raw own-only**; calibration plus full admission approaches
no-speculation latency. At 12/10 seconds the raw full-versus-own reduction is about
**21.8%**. These are protection effects against harmful own-only speculation,
not improvements of that size over no speculation.

With nonbinding quota and one worker, raw Jev reduces matched mean completion
10.543 → 10.413 seconds, about 1.2%, with roughly 6.7 useful hits per 30 questions.
At multiple workers, the retained 150-second actor outlier dominates batch tails;
mean task saving does not imply equal batch-throughput saving. Full raw schedules,
per-question outcomes, logical costs and background drain are retained. This
already-explored historical cohort is diagnostic, not fresh confirmatory evidence.

## Costs and retained evidence

All campaign calls reconcile to an OpenRouter account usage increase of
**$0.841052284** (1.259235835 → 2.100288119). This exactly matches the sum of known
provider costs, including new forecast-bank collection and failed-run attempts
with reported cost. Two failed requests have individually unknown cost; their
conservative reservations total **$0.006859600**, giving an accounting upper bound
of **$0.847911884**. The account-level reconciliation does not rewrite either
request's unknown cost to zero. Final reported remaining limit: **$4.158947716**.

- Full campaign, costs, every run and evidence hashes:
  `results/multi-agent-context-2026-11-15-report/`.
- Primary live arms: `results/multi-agent-context-2026-11-15-pilot-*`.
- Repaired eight-worker recordings and independent audits:
  `results/multi-agent-context-2026-11-15-repaired-*`.
- Failed runs are retained under `eight-calibrated` and `repaired-fast_jev`.
- Complete bank: `results/multi-agent-context-2026-11-15-episode-bank/`.
- Same-work schedules, tuning and validation:
  `results/multi-agent-context-2026-11-15-matched/`.
- Calibration: `results/multi-agent-context-2026-11-15-calibration.json`.
- Unit/fault-injection logs: `results/multi-agent-context-*.log`.

Raw model requests/responses, immutable blobs, full stage graphs, source snapshots,
all started attempts, model/provider identities and unknown costs are retained.
Credentials are not written to these artifacts. Existing paid banks and unrelated
working-tree changes were preserved; nothing was committed or published.

## Reproduction

Prepare the pinned upstream source and dependencies as described in README.
Mock mode needs no paid recordings:

```sh
make multi-agent-offline COUNT=8 AGENTS=4 OUTPUT=results/context-mock-fresh
make multi-agent-audit EVIDENCE=results/context-mock-fresh
make test
make lint
```

For real calls, explicitly load the private environment. This driver currently
uses OpenRouter catalog prices for both chat and Jev cost reservations:

```sh
set -a
source .env
set +a
# OPENROUTER_API_KEY and TYPESAFE_API_KEY are private.
# JEV_MODEL=typesafe/jev-1.14
# JEV_BASE_URL=https://openrouter.ai/api/alpha
.venv/bin/python -m quota_spec.multi_agent \
  --backend http --policy jev_full --agents 8 --count 16 --offset 98 \
  --capacity 12 --window-s 5 --max-usd .7 --forecast-max-usd .1 \
  --calibration results/multi-agent-context-2026-11-15-calibration.json \
  --output results/context-live-fresh
.venv/bin/python -m quota_spec.live_context_audit results/context-live-fresh
```

The total dollar cap is partitioned between chat and forecasts; it is not an
extra forecast allowance on top of `--max-usd`. Unknown attempts consume their
reservation from that partition. Change `--optional-slots`, `--model-retries`,
`--context`, `--width` or `--draft-actor` only as declared ablations. A failed
question causes the CLI to exit unsuccessfully after all started work drains.
Each output directory must be fresh.

Regenerate the matched study and account report without inference:

```sh
.venv/bin/python -m quota_spec.matched_context_study results/hotpot-dataset-50 \
  --bank results/multi-agent-context-2026-11-15-episode-bank/bank.json \
  --calibration results/multi-agent-context-2026-11-15-calibration.json \
  --output results/context-matched-fresh
.venv/bin/python scripts/report_multi_agent_context.py \
  --output results/context-report-fresh
```

Next research should target candidate precision and launch timeliness, then test
on genuinely fresh question streams with a preregistered quota and baseline.
Changing speculative model/width and tuning on these observed live results must
be labeled exploration. For now the defensible result is a functioning,
auditable Jev integration and measured cross-agent protection, with limited
native end-to-end acceleration.
