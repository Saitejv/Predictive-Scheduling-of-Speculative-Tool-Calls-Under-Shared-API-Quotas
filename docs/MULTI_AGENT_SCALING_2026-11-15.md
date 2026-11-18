# Multi-agent scaling comparison — November 15, 2026

We ran **384 clean live episodes**: 2/4/8 simultaneous agents, two shared Search
quotas, four policies and two actor seeds. Each batch uses the same eight fresh
questions (seeded offsets 322–329); each policy/setting therefore has 16 attempts
on eight unique questions, not 16 independent questions.

Mean 8-question batch time in seconds; parentheses show exact matches across 16 attempts.

| Agents | Shared quota | No speculation | Allow-all | Jev | Quota-aware |
|---:|---|---:|---:|---:|---:|
| 2 | 8 calls / 5s | 16.40 (9/16) | 18.88 (8/16) | 16.25 (9/16) | 13.98 (8/16) |
| 2 | 12 calls / 3s | 15.81 (10/16) | 16.53 (9/16) | 15.48 (9/16) | 14.44 (8/16) |
| 4 | 8 calls / 5s | 11.73 (8/16) | 12.68 (8/16) | 12.04 (9/16) | 12.78 (8/16) |
| 4 | 12 calls / 3s | 10.28 (9/16) | 9.18 (9/16) | 10.12 (9/16) | 10.82 (9/16) |
| 8 | 8 calls / 5s | 9.84 (9/16) | 17.91 (8/16) | 11.87 (9/16) | 11.10 (8/16) |
| 8 | 12 calls / 3s | 5.94 (8/16) | 7.75 (9/16) | 6.95 (10/16) | 6.59 (8/16) |

Quota-aware planning had lower average batch time than Jev in **4/6 settings**.
Jev scored higher on exact match in **5/6**, with a tie in the remaining setting.
No speculation was fastest in three settings, allow-all in one, and quota-aware
planning in two. The two quota-aware wins have lower exact-match scores than
no speculation. Neither advanced style consistently beats both baselines while
preserving accuracy. These are exploratory observations, not confirmed causal
speed or accuracy gains.

## Measurement and controls

Each batch shares one fixed-window Search quota and releases workers when their
answers are ready. Batch time includes every started background operation. The
main agent never receives quota information. Jev uses the existing frozen
calibration and cross-agent admission; the direct planner receives observed
quota context and makes no Jev requests. Both retain the step-4 speculative
generation budget. Allow-all retains unrestricted generation.

The comparison now resets the quota clock at batch dispatch, after catalog,
account and client setup. The main actor receives a common best-effort sampling
seed derived from replication, question and step; policy, agent count and quota
do not enter that seed. Actual paths can still differ. Policy/configuration order
was independently shuffled in each replication. Recovery pauses were 60 seconds
in the first matrix and 30 in the repeat, entirely outside batch timing.

The eight-agent case has only one wave of eight questions. This is a short-batch
pilot, not sustained throughput. Only two batches per cell and eight unique
questions are insufficient for strong confidence claims. The full data retains
both batch times/ranges, mean per-question completion, exact match, F1, cache
hits, unused prefetches, required quota waits and API charges. No tail was trimmed.

[Full metrics](evidence/multi-agent-scaling-2026-11-15/report.json)
· [CSV](evidence/multi-agent-scaling-2026-11-15/rows.csv)
· [First protocol](evidence/multi-agent-scaling-2026-11-15/final-protocol.json)
· [Repeat protocol](evidence/multi-agent-scaling-2026-11-15/repeat-protocol.json)

## Verification and spending

All 48 final runs passed their independent capture/state/context/quota/FIFO
audits. The audit verified actual 2/4/8-agent concurrency, **1,233 actor requests'
seed settings**, **2,832 archived source files**, and zero quota-context leaks to
the main actor. There were zero final actor, optional or forecast failures.
**281 tests pass**, including delayed-setup clock alignment and actor seed
consistency across speculative/sequential modes. Ruff and whitespace checks pass.
[Audit](evidence/multi-agent-scaling-2026-11-15/audit.json).

The first attempt stopped on disk exhaustion. It is retained and excluded from
performance comparisons. Storage was recovered using content-verified hardlinks
for identical immutable blobs and transparent filesystem compression. Every
recording path and byte content was preserved; the two already-incomplete blobs
from the failed attempt were left unchanged. Subsequent paid runs check free
space before dispatch. A separate two-batch, 16-question budget probe is also
retained and excluded from the final matrix. It projected beyond the remaining
allowance, so the final eight-question cohort was fixed before its results were
observed. The second matrix was added under a budget-only condition with frozen
policies, not by choosing successful settings.

Total additional account charges are **$0.953237138**, including all attempts.
Model receipts account for $0.952628338; $0.0006088 is an account-only aggregate
charge from the storage-failed attempt without an individual receipt. That gap
is explicit. The 384 clean comparison episodes have $0.793951798 in complete
provider-reported charges. [Cost reconciliation](evidence/multi-agent-scaling-2026-11-15/costs.json).

Raw data and executed source/controller snapshots remain in the ignored local
`results/multi-agent-2026-11-15-*` directories. The earlier locked 80-question
matched-replay evidence remains a separate experiment; this pilot does not
replace it or turn its conclusions into live A/B guarantees.

## Reproduction and next checkpoint

The controllers and reporting tools are `scripts/run_multi_agent_scaling.py`,
`scripts/report_multi_agent_scaling.py`, and `scripts/audit_multi_agent_scaling.py`.
Use fresh output directories. The two recorded actor seeds are 5851516 and
5851517. The captured controller/protocol files preserve exact execution details.
For genuinely new seeded questions, the next unused offset is **330**.
Future confirmation should use more questions and batches larger than the agent
pool, with controlled actor trajectories or dynamic-planner matched replay.
