# Trace format and replay semantics

The CLI accepts a JSON list of tasks via `--trace`. Times are seconds
relative to experiment start. This is a serial-chain schema; its extensions
retain observed-state context, with corpus provenance in a separate manifest.

```json
[
  {
    "task_id": "agent-a",
    "arrival_s": 0,
    "deadline_s": 20,
    "steps": [
      {
        "think_s": 2,
        "query": "University of Michigan founding year",
        "duration_s": 1,
        "candidate_query": "University of Michigan founding year",
        "candidate_duration_s": 1
      }
    ]
  }
]
```

`task_id` must be unique. `deadline_s` is optional and absolute, not a relative
timeout. A task must contain at least one step. Each step begins when the prior
required result becomes available, or at task arrival for the first step.
`think_s` elapses before its required invocation is ready. `duration_s` is the
recorded tool execution time, excluding quota wait.

An optional `candidate_query` is an observed hint made available at step entry.
Omit it or set it to null to provide no candidate. `candidate_duration_s` defaults
to the required duration; exact-match candidates must have the same tool duration
as their required invocation. An incorrect candidate can have its own duration.
Synthetic traces construct these hints with a seeded match probability solely
to exercise replay. Real traces must record hints generated from observed inputs.

The initial schema supports only `search` with a single exact `query` argument.
There is no normalization of query text. Cache identity includes the task/agent,
tool, and canonical JSON arguments. The registry persists across the task's
steps, so repeated required searches can reuse earlier results even under no
speculation. All baselines share that behavior.

## Event order

At an equal timestamp, process tool completions, required readiness, step entry,
quota wakeups, then candidate decisions. Ties within a category use stable
insertion order. Required calls dispatch FIFO as soon as quota is available.
Quota windows are `[k * window_s, (k + 1) * window_s)` and each dispatch charges
one unit. Tool completion has no quota effect.

The event loop drains speculative completions even after all tasks finish.
Task completion metrics use the recorded task finish time, so unused work does
not extend the completed task's latency. Replay does not model cancellation or
failure events; the live gateway logs and tests them separately.

## Logs

Each JSONL event contains `time_s` and `event`. Depending on event type, it also
contains `task_id`, `step`, tool/argument identity, `speculative`, remaining
quota, or `admitted` and `eligible`. Events include step entry, candidate
decision, required readiness, dispatch, completion, refill, reuse, in-flight
join, and task finish. Ineligible candidates are logged as rejected and do not
invoke a predictor. The offline reference's internal counterfactual event logs
are discarded; the returned log records only the committed execution.

## Observed-state and measured-trace extensions

Tasks optionally carry `task_context`; each step optionally carries a
`result_excerpt` of its required search output. Missing fields default to empty
strings and old traces remain loadable. The current step's excerpt is hidden at
step entry and exposed only at the next step after completion. Ground-truth
required query/duration remain simulator-only. The data corpus and task splits
are identified by `data/manifest.json`; gold answers stay in `data/labels.json`.

An online `Observation.snapshot` holds timestamped active-agent states, recent
required readiness times, observed required queue, and execution registry. It
contains no future task arrivals or hidden dependency steps. Adapter context
limits are 2,048 task characters, eight calls and 1,024 excerpt characters.

Predictive `candidate_decided` events add sampled gain, owner gain, incremental
miss risk/denominator, sample count, horizon, max calls, reuse probability,
modeled overhead, measured decision wall time and fallback metadata. Replay
metrics also include per-agent completion, individual required waits, modeled
decision overhead and required ordering. Saved scheduler wall timing is nondeterministic. History/mock outcomes use
frozen modeled overhead; external model runs charge measured decision wall time
and must retain their measured artifacts.

Trace collection times are seconds relative to each task run. Evaluation supplies
controlled arrivals/deadlines without changing saved dependency durations. Live
logs use a monotonic origin at gateway construction. Candidate responses contain
only admission status, and required responses expose results on exact matching
invocation. Live tool failures and cancellation have explicit events and never
refund quota; failure/retry trajectories are not part of the replay trace schema.

Running execution finish times in policy snapshots are estimates based on prior
completed durations, falling back to `--expected-duration-s` (default 1 second).
The actual trace duration remains hidden until completion.
