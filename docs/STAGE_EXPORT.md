# Exporting existing stage recordings

```sh
make export EXPORT_OUTPUT=results/hotpot-stage-export-fresh
# Equivalent explicit command:
.venv/bin/python -m quota_spec.stage_export results/hotpot-live-paired-20 \
  --output results/hotpot-stage-export-fresh
```

The exporter uses only the standard library and local evidence. It never calls
models, Wikipedia, or upstream preparation. Inputs remain unchanged. Outputs
must be fresh and outside the input tree.

## Version 1 outputs

| File | Contents |
| --- | --- |
| `graph.json` | Stage nodes and source-event-to-node mapping |
| `coverage.json` | Per-node missing fields, per-window gaps, per-rank candidate execution coverage |
| `COVERAGE.md` | Short human-readable coverage summary |
| `evidence/` | Byte-identical config, summary, model records, events and episode files |
| `manifest.json` | Evidence byte counts/SHA-256, upstream/source provenance and derived JSON hashes |

The graph has model-attempt nodes, authoritative action boundaries, Search
execution nodes, candidate/launch events, application records, answer readiness
and resource drain. Dependencies follow recorded execution and remain within
each episode. Validation rejects duplicate/missing request IDs, mismatched
request contexts, ambiguous tool identities, cycles, cross-episode edges and
known timing contradictions, including dependencies through untimed nodes.
Every source event maps to a node. Starts/completions of one execution map to
the same node; this is why node count differs from event count.

Model nodes retain the exact request payload/settings and response, billed
usage, service duration, submission/completion timestamps, role, branch and
attempt. `request_sha256` hashes canonical JSON for the entire request payload.
Repeated stochastic attempts remain distinct nodes even for identical payloads.
Candidate events retain every recorded action and its one-based rank; exact
Search arguments are not normalized. Only Search is eligible, with the current
required query excluded as in the runtime. Candidate coverage records all
rank entries, including duplicate/reused execution references and late branches.
These are coverage counts, not unique new-call or cost estimates.

Original timestamps are evidence in the recorded run's clock. They cannot be
used as readiness times under a different scheduler. Model service duration is
available; readiness and queue delay are null. Tool application records retain
displayed observations and measured waits, with null state and application end
times. The exporter does not infer full WikiEnv state from a displayed excerpt.

## Coverage of the retained paid run

Exported to `results/hotpot-stage-export-complete-2026-11-12/`:

- All **296 requests, 1,299 events and 40 episodes** accounted for in 1,024 nodes.
- All 20 speculative authoritative histories are canonical scheduling tapes.
  The 20 independently sampled sequential histories remain separate evidence.
- All 53 recorded candidate lists retain their 157 ranked actions.
- 163 Search executions have timing, including 24 prefetches and three exact hits.
  None has a saved full tool result or before/after WikiEnv state.
- Of 62 speculative Search boundaries before the action limit, 59 have
  observation predictions and 53 have hypothetical actor/candidate outputs.
  Six observation outputs arrived too late to trigger a hypothetical actor;
  three cache hits skipped the window entirely. Thus three observation and
  nine hypothetical/candidate entries are absent for a completed scheduling bank.
- 97 ranked candidates are eligible Search suggestions; 70 rank entries lack
  a corresponding speculative execution. Some ranks duplicate queries; these
  counts do not mean 70 distinct paid/model requests are necessary.

**This is not executable frozen replay.** The graph exposes saved evidence and
missing coverage. The next implementation is a versioned runtime recorder with
full immutable tool results and snapshots (page, observation, result titles,
lookup keyword/list/cursor, steps and answer), exact branch inputs/outputs and
readiness/queue/service timing. Unused prefetches must be captured too.

A separate bank-completion plan must enumerate unique exact missing contexts
on the canonical histories, including skipped/late windows, without using
future observations. Only then can the required alternatives be collected,
with their proposed cost shown separately from live benchmark timing. Frozen
replay must fail on missing entries and remain socket-blocked. The old
one-candidate replay engine is not used by this exporter. See
[FROZEN_REPLAY_PLAN.md](FROZEN_REPLAY_PLAN.md) and [next_steps.md](../next_steps.md).
