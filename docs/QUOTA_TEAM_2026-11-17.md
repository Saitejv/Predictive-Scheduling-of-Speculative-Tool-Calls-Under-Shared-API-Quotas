# Joint quota and other-agent awareness

**New controlled test:** [The actual query-planner comparison](QUOTA_TEAM_TEST_2026-11-17.md) holds main trajectories fixed and evaluates both quota-only and combined planning across two orders. The native check below remains separate.

The direct speculation planner now has an explicit combined mode:

```text
--policy current_capacity --speculation-planner quota_team
```

This uses the speculation language model directly, without Jev calls. `team` remains a compatible name for the same combined context. `quota` is retained as the quota-only comparison.

The optional planner receives remaining Search calls, capacity, refill timing, required queue size and bounded observed state for each other active agent: its question, phase, elapsed time, completed calls, recent returned actions, last real result and last returned actor intent. This extra information is never sent to the main actor.

The instructions now explicitly combine the two sources: estimate which peers may need Search before the next refill, reserve quota for that demand, and speculate only from the remaining headroom. The former unconditional reserve of one call per worker becomes a fallback for absent or uncertain peer information. Required calls still have FIFO priority and quota is rechecked at dispatch. Peer cache entries are not assumed to be reusable by another agent.

This follow-up updates the query-generation instructions; the earlier [peer-context report](TEAM_CONTEXT_2026-11-17.md) used the archived earlier prompt for its native query-generator check. Its fixed-candidate admission gate is a separate experiment. Do not attribute those earlier performance numbers to this updated prompt.

## Native functionality check

Eight new questions at dataset offsets 338–345 were run in both modes, with four workers and a shared quota of eight Search calls per five seconds. Both use the updated prompt, the same main-actor seed and the same generation-step limit. The difference is the supplied peer context.

| Optional planner | Mean answer latency | All-background batch time | Jev calls | Actor/optional failures |
|---|---:|---:|---:|---:|
| Quota only | 8.22s | 21.21s | 0 | 0 / 0 |
| Quota + other agents | 8.79s | 21.10s | 0 | 0 / 0 |

These are descriptive native timings, **not a causal speed comparison**: independent authoritative trajectories contained 37 versus 39 actions, and provider timing varies. The small batch-time difference does not establish a speedup; the combined mode did not improve observed mean latency. Both independent audits pass: quota, required FIFO/priority, optional context provenance and main-actor prompt checks. All 20 combined-planner snapshots contained both quota fields and observed peers.

The change is verified by **288 passing tests**, including the explicit combined CLI mode, rejection of fabricated peer intent, and reproduction of the updated prompt by the safe frozen-template audit. Ruff passes for 137 files. The new native check made 156 model requests; all usage receipts are known and total **$0.0687131**. No Jev requests were made.

The combined mode is implemented and available for subsequent experiments; it is not promoted over Jev as the default. Raw captures, source snapshots, usage receipts and audits are retained in `results/quota-team-2026-11-17-*`. The compact [live report](evidence/quota-team-2026-11-17/live-report.json) contains both audits and the accounting check. Next unused native workload offset: 346.
