# Live HotpotQA latency comparison

The latest implementation and fresh pilot are documented in
[the async validation report](ASYNC_SPECULATION_VALIDATION_2026-11-13.md).

**November 13 repair:** `make live` now runs with no artificial model-submission
pacing. Its former hard-coded 1.1-second shared gate delayed authoritative calls
behind speculative requests. Paced collection is now `make capture` or
`--purpose capture --min-request-interval-s 1.1`; the default benchmark purpose
rejects this pacing before any requests or output creation. See
[the source comparison and regression evidence](SINGLE_AGENT_BASELINE_REPAIR_2026-11-13.md).

Run `make single-agent-check OUTPUT=results/single-agent-check-fresh` to check
the original chess timing calculation and all saved HotpotQA episodes offline.
This executes the actual async runtime with saved responses and a service-time
clock. It verifies scheduling, prompts and reuse without new model calls; it
is separate from a newly measured live provider benchmark.

The [November 12 measured results](HOTPOT_RUNTIME_RESULTS_2026-11-12.md) report
20 pairs, 40 real-model episodes and three exact prefetch hits. Observed mean
latency was 10.27% lower, but paired uncertainty includes zero and trajectories
differed; a reliable end-to-end benefit is not established.

`python -m quota_spec.hotpot_runtime` runs complete autonomous sequential and
speculative episodes on the paper's intended 20-question workload. This is a
new concurrent runtime around the pinned authors' prompts, action parser and
Wikipedia implementation. It replaces the serial evaluation driver for this
experiment. It uses no Jev, shared tool quotas, replay timings, or artificial
tool delay in HTTP mode.

```sh
.venv/bin/python -m pip install -e '.[paper,analysis,dev]'
.venv/bin/python -m quota_spec.upstream
.venv/bin/python -m quota_spec.hotpot_runtime \
  --backend mock --count 2 --output results/hotpot-runtime-smoke

set -a
source .env
set +a
.venv/bin/python -m quota_spec.hotpot_runtime \
  --backend http --count 20 --max-usd 0.50 --max-requests 800 \
  --output results/hotpot-runtime-fresh
```

Outputs must be fresh. The request budget and incremental dollar budget are
enforced before submission, including reservations for requests already in
flight. Every response, including failed or unused speculative requests, is
retained without authorization headers. Unknown costs block subsequent paid
requests. The runtime uses at most four concurrent inference requests; optional work
uses at most three, reserving capacity for the authoritative actor.

## Execution

Both modes use Gemini 2.5 Flash for authoritative and hypothetical reasoning,
and GPT-4.1 nano for observation prediction by default. They use the original ReAct six-shot prompt,
up to seven generated actions, the original retry limits and OpenRouter
parameters. Authoritative/speculative actors receive 1,000 output tokens,
temperature 1 and top-p 1. The observation speculator receives 100 output
tokens, temperature 0.1 and top-p 0.9. The `--speculator` option changes only
the observation model; hypothetical reasoning uses the actor model, as in the
original evaluation.

Sequential mode executes actor → tool → actor. Speculative mode starts the
same required Search alongside observation prediction. A hypothetical actor
predicts up to three next actions from the provisional observation; predicted
Search calls start immediately when predictions become available before the
answer, including during main-actor thinking and after intervening actions.
`--candidate-lifetime next_action` restores the historical next-action deadline. The real actor always sees only authoritative observations and makes
its own action decision. Exact Search arguments can reuse a completed result
or join an in-flight prefetch. Arguments are case-sensitive and are not
normalized. A cache hit does not open another speculation window, following
Algorithm 1. Duplicate candidates are deduplicated within the episode.

Lookup and Finish are local authoritative operations and are never cached or
executed speculatively. Each prefetch uses its own WikiEnv. Applying a cached
Search restores its real page and resets lookup state only when the original
Search implementation would do so. Failed exact-page searches preserve the
previous authoritative page. A failed prefetch falls back to required work.
Outputs arriving after answer readiness do not launch Searches. All started
work drains; it is included in resource time and cost.

## Measurement and interpretation

Each question runs once in each mode. Sequential-first and speculative-first
order alternate to reduce order effects. Runs are paired by question, not by
identical action tape: original actor sampling remains stochastic. Results
therefore include trajectory differences and provider/network variation.
The report includes action counts, identical-action pairs, answer EM/F1 and
paired uncertainty; a difference in aggregate runtime alone is not proof of
acceleration from cache reuse.

`completion_s` measures wall time from the start of the first actor call to
answer readiness, including all required actor/tool work and interference from
concurrent speculation. When the seven-action horizon is reached without
Finish, the episode is force-finished with an empty answer, as in the upstream
runner, and marked `forced_finish`.

`resource_s` also includes draining all started model/tool work after the answer.
Paid HTTP requests are drained rather than cancelled, so their costs can be
accounted for. Draining happens before the next episode, preventing leftover
work from contaminating the next condition. Resource-drain totals are the
appropriate denominator for this serial campaign's throughput. They are not
a multi-agent saturation-throughput result.

The summary reports mean, median and nearest-rank p95 answer latency; total
answer/resource time; answer scores; prefetch hits, unused calls and late
windows; costs and tokens by mode; and a 5,000-resample paired bootstrap 95%
interval for mean seconds saved. Positive saving favors speculation. With
only 20 pairs and independently sampled trajectories, uncertainty can be wide.

Artifacts include `config.json`, `pricing.json`, raw `requests.jsonl`, billed
`inference.jsonl`, timestamped `events.jsonl`, per-episode `tasks/`, and an
incrementally checkpointed `summary.json`. The configuration records all
source hashes and the checksummed upstream manifest. Mock runs have null QA
scores and `live_execution=false`; their controlled delays test mechanics and
are not evidence of a real-model latency benefit.

Regenerate the report and audit from frozen evidence without model calls:

```sh
.venv/bin/python scripts/report_hotpot_runtime.py results/hotpot-runtime-fresh \
  --output results/hotpot-report-fresh
```

The report writes separate derived files and never overwrites the live inputs.
For the retained paid run, `make report` additionally verifies its original source
snapshot. [The stage exporter](STAGE_EXPORT.md) inventories complete model logs,
all recorded candidate ranks and the missing state/tool coverage for replay.
