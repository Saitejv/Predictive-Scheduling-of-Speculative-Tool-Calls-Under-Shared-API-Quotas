# Speed by agent and quota scenario

**November 17 follow-up:** [Peer context and Search-time experiments](TEAM_CONTEXT_2026-11-17.md) add a counterfactual service-time sweep and a separate fixed-candidate language admission gate. The earlier live quota-aware query-generator rows below remain separate.

The main table compares four complete styles using the same eight questions,
the same actor seed (5851516), model settings and quota epoch. Every finite-quota
row uses **12 Search calls per aligned 3-second window** across all agents.
The 2/4/8-agent rows reuse the first-seed runs from the prior experiment; the
1-agent and 6-agent rows are newly measured. This avoids mixing seed counts.
The previous two-seed averages remain in the earlier scaling report.

## Live latency table — all four styles

Mean answer latency per question, seconds.

| Scenario | No speculation | Full speculation | Jev | Quota-aware |
|---|---:|---:|---:|---:|
| 1 agent, no quota | 4.00 | 3.36 | 3.07 | 3.43 |
| 1 agent, with quota | 3.66 | 3.47 | 3.43 | 3.36 |
| 2 agents, with quota | 3.01 | 3.44 | 2.83 | 3.06 |
| 4 agents, with quota | 3.32 | 2.52 | 3.50 | 3.51 |
| 6 agents, with quota | 3.78 | 7.01 | 3.59 | 3.57 |
| 8 agents, with quota | 3.18 | 3.84 | 3.46 | 3.59 |

Full speculation means allow-all eligible speculative Searches. Jev means the
calibrated cross-agent admission method. Quota-aware means the speculation
planner receives quota context and abstains or proposes queries without Jev.
Actual main-agent prompts receive no quota context. No accuracy score is used
as a performance objective or a speed–accuracy tradeoff here.

The no-quota control uses a nonbinding limit of 1,000,000 calls per window.
Every dispatch retained more than 999,000 calls: there was no quota throttling.
The one-agent quota case may also have slack at C=12; a configured quota is not
necessarily a binding bottleneck.

**Caution:** these are eight-question live observations, not a large-sample or
fixed-path causal comparison. Common seeds do not guarantee identical actor
paths or provider service times. The 6-agent/full-speculation result includes a
**30.218-second main-model call**. Its mean required quota wait was only about
0.017 seconds, so the large observed slowdown must not be blamed on quota
scheduling alone. No outlier was removed.

## Total workload time

This measures the time to finish the entire eight-question batch and drain all
started background work. Parallel agents can reduce batch time without reducing
individual question latency.

Seconds to complete the same eight-question workload, including background work.

| Scenario | No speculation | Full speculation | Jev | Quota-aware |
|---|---:|---:|---:|---:|
| 1 agent, no quota | 32.02 | 27.07 | 25.09 | 27.46 |
| 1 agent, with quota | 29.32 | 27.90 | 28.37 | 27.58 |
| 2 agents, with quota | 12.86 | 14.82 | 12.27 | 13.91 |
| 4 agents, with quota | 10.06 | 7.44 | 10.43 | 11.41 |
| 6 agents, with quota | 7.06 | 34.66 | 9.09 | 8.44 |
| 8 agents, with quota | 5.30 | 7.00 | 5.88 | 8.06 |

[Full live metrics and sources](evidence/speed-scenarios/report.json)
· [CSV](evidence/speed-scenarios/rows.csv)

## Controlled scheduling check — three styles

For a cleaner speed-only test, the following replay keeps the authoritative
paths, outputs, answers and native measured service times identical. It uses
80 saved evaluation questions and three paired order seeds, with sockets
blocked, zero forecast fallbacks and all started background work charged.
Existing 2/4/8-agent results were reused; 1/6-agent and no-quota replays were
added offline without API calls.

Fixed-path replay: mean question latency, seconds; same 80 questions, three order seeds.

| Scenario | No speculation | Full speculation | Jev |
|---|---:|---:|---:|
| 1 agent, no quota | 6.16 | 5.97 | 6.01 |
| 1 agent, with quota | 6.16 | 5.97 | 6.01 |
| 2 agents, with quota | 6.16 | 5.97 | 6.03 |
| 4 agents, with quota | 6.16 | 6.82 | 6.06 |
| 6 agents, with quota | 6.16 | 9.54 | 6.29 |
| 8 agents, with quota | 6.92 | 10.44 | 6.96 |

At this quota and workload, full speculation is fastest with one or two agents.
Its extra calls become harmful as concurrency grows. Jev is fastest at four
agents, but does not beat no speculation at six or eight. The eight-agent
Jev/no-speculation difference is small. This is conditional on the captured
service sample, not a live-provider throughput guarantee.

The quota-aware language planner is **not** included in this controlled table:
its generated queries depend on dynamic quota context, and an appropriate frozen
context bank has not been collected. A simple quota-reserve heuristic is not a
substitute for that language planner. Its only measurements above are live.

## Evidence and cost

All 12 new live batches completed: **96 new episodes**, plus 96 reused episodes
in the uniform live table. Captured-state, quota/FIFO, concurrency and prompt
isolation audits pass, including six real simultaneous agents. The no-quota
control was independently checked to remain nonbinding. Controlled replay
validation preserves all answers and has no network fallback.

New API charges: **$0.190243988**, matching the account delta. One recovered
transport attempt retains an unknown individual cost and a $0.0064369 upper
reservation; no individual unknown fee was silently set to zero.
[Cost record](evidence/speed-scenarios/costs.json).
**281 tests pass**, as do Ruff and whitespace checks.

Live raw data and frozen controller/source are under
`results/scenario-speed-2026-11-15-live`. The controlled additions are in
`results/scenario-speed-2026-11-15-controlled-*`; the combined tables are in
`results/scenario-speed-2026-11-15-report`. Existing results and unrelated local
changes were preserved. The controller extension accepts custom agent/quota
settings, and `scripts/report_speed_scenarios.py` rebuilds the uniform table.
