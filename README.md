# Speculative tool calls under shared API quotas

CSE 585 project by Jack McClure, Saitej Velaga, and Angela Li.

**November 15: confirmed matched-replay wins over both baselines.** On 80 new
held-out questions, the locked 4-worker / 12-Search / 3-second setting reduces
mean completion by **1.57% vs no speculation** and **10.11% vs allow-all**;
whole-batch time falls **1.46% / 10.09%**. All ten paired orders and the 95%
question-bootstrap intervals favor the method. The 75-setting quota/refill map
retains losses: 13 settings beat both baselines on both endpoints. This is
measured replay evidence; the final live smoke verifies operation, not live A/B
speed. **275 tests pass; $1.439993844 additional API spend is reconciled.**
See [the full result, controls, quota maps and reproduction](docs/QUOTA_WINS_2026-11-15.md).

**Quota-aware speculation experiment:** the optional speculative branch can now
receive remaining calls, capacity, refill timing and competing required work
without sending that context to the main agent or calling Jev. The final pilot
contains 240 clean episodes on 16 unique questions across three quota regimes. It reduces unused calls,
but does not establish a win over both baselines; Jev remains the default.
281 tests pass; additional known API charges are $1.256674044, reconciled to the
settled account delta. See [the experiment, controls and results](docs/QUOTA_PROMPT_2026-11-15.md).

**Live multi-agent integration is implemented and tested.**
[`multi_agent.py`](src/quota_spec/multi_agent.py) runs the pinned ReAct agent with
shared Search quota and an asynchronous Jev context engine. It supports observed
task/history/progress inputs, forecast caching, full/own admission, development-only
calibration, exact-query reuse, required FIFO priority and complete cost accounting.
The November 15 campaign includes **236 live episodes**, real 2/4/8-agent
concurrency and **216 matched offline replays**. Cross-agent admission protects
other workers, and the later locked replication now demonstrates the replay wins described above.
Read [the integration results and commands](docs/MULTI_AGENT_CONTEXT_2026-11-15.md).

```sh
make multi-agent-offline COUNT=8 OUTPUT=results/multi-agent-mock-fresh
make multi-agent-live COUNT=16 OFFSET=98 AGENTS=8 MAX_USD=.7 OUTPUT=results/multi-agent-live-fresh
make multi-agent-audit EVIDENCE=results/multi-agent-live-fresh
```

The live command spends API credit and requires the private environment settings
described in the integration guide. Mock mode needs no paid recordings or keys.

The underlying single-agent baseline is [`hotpot_runtime.py`](src/quota_spec/hotpot_runtime.py): one
real ReAct actor using Wikipedia, with asynchronous speculative Searches.
Observation prediction uses **GPT-4.1 nano**; authoritative and hypothetical
reasoning use **Gemini 2.5 Flash**. Both are configurable.

Speculation keeps running while the main actor thinks. Prediction windows now
remain open until the answer, so a prediction can also help after an intervening
Lookup or another action. Required queries and existing cache entries suppress
duplicates. The real actor always uses true observations; it reuses a completed
prefetch or joins its remaining work. Optional inference leaves one serving slot
for the real actor. Every started request is drained and recorded.

On identical saved paths, speculation reduces mean answer time by **0.20 s**.
The separate live pilot observed **7.01 s → 6.25 s**, but its actor paths and
service times differ and its paired interval includes zero. That observed delta
does not establish an isolated throughput improvement. Read
[the throughput reconciliation](docs/THROUGHPUT_REPAIR_2026-11-13.md) for the
common-work comparison, quota limits and scheduler repairs; the earlier
[live validation](docs/ASYNC_SPECULATION_VALIDATION_2026-11-13.md) retains the
original recordings, costs and endpoint checks.

## Setup and offline checks

```sh
make setup
make prepare
make offline OUTPUT=results/smoke-fresh
make test
make lint
```

Python 3.11+ is required. Preparation downloads checksummed public upstream files;
mock runs and tests require no model credentials. Output directories must be fresh.

## Live benchmark and recording

Set `OPENROUTER_API_KEY` in the environment, then explicitly run:

```sh
make live OUTPUT=results/live-fresh MAX_USD=.50
```

This requests paid inference for 20 paired questions, alternates mode order, and
has no artificial model-submission pacing, Search quota or Jev gate. The dollar
limit reserves concurrent request costs before dispatch. Override `ACTOR`,
`SPECULATOR`, `COUNT` or `OFFSET` when needed. The benchmark rejects artificial
pacing; `make capture OUTPUT=results/capture-fresh` explicitly selects paced data
collection instead. Historical expiry is available with `--candidate-lifetime next_action`.

To verify a new recording without inference:

```sh
.venv/bin/python -m quota_spec.capture_audit results/live-fresh
```

The audit checks immutable stage blobs, exact model prompts, real environment
transitions, request inventories, episode timing endpoints, cache counts and
prefetch launches inside actor-thinking spans. Raw requests, responses, costs,
unused work and failures remain in the recording; credentials are excluded.

## Replay and project extension

- [`single_agent_reference.py`](src/quota_spec/single_agent_reference.py) executes
  the actual async agent with saved outputs and checks a separate scalar timing
  calculation. `make single-agent-check OUTPUT=results/reference-fresh` requires
  the retained 50-question bank and pristine original source checkout.
- [`capture_bank.py`](src/quota_spec/capture_bank.py) completes missing alternatives
  separately from the live benchmark. Its `--plan` command is offline; HTTP
  completion is a separate paid operation with its own explicit budget.
- [`frozen_replay.py`](src/quota_spec/frozen_replay.py) compares multiple agents
  under one shared Search quota. Its CLI follows recorded candidate lifetimes by
  default. The `overlap` scheduling profile generates during required quota wait,
  retries ready candidates after reset, and releases workers at answer while
  counting all background work. `--scheduling legacy` retains dispatch-triggered
  generation, one-shot admission and release after drain. Use
  `--cache-required-results` to give both conditions the same ordinary cache.
  Legacy recordings retain legacy expiry; new ones retain episode windows.
- Jev/quota studies are scheduling extensions, separate from the single-agent
  speed benchmark. Kev remains deferred. Historical drivers are retained for
  reproducibility and are not imported by the active runtime.

Start with [next_steps.md](next_steps.md). [Architecture](docs/ARCHITECTURE.md),
[the runbook](docs/RUNBOOK.md) and [research history](docs/RESEARCH_HISTORY_2026-11-13.md)
provide details. The [original-paper check](docs/SINGLE_AGENT_BASELINE_REPAIR_2026-11-13.md)
reproduced the authors' chess timing result; their HotpotQA figure measures action
agreement and is a separate experiment.

`results/`, `.env`, downloaded upstream data and temporary checkouts are Git-ignored.
Keep paid evidence bundles separately from a code checkout. Existing recordings
are never overwritten by reports, replay or a new benchmark.

`make throughput-check OUTPUT=results/throughput-check-fresh` reconciles the
retained live pilot with fixed-path playback, checks a separate quota lower
bound, and runs paired legacy/overlap and finite/repeated-workload controls.
It makes no paid calls and requires the retained pilot evidence locally.
