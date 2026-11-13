# Speculative tool calls under shared API quotas

CSE 585 project by Jack McClure, Saitej Velaga, and Angela Li.

The active agent is [`hotpot_runtime.py`](src/quota_spec/hotpot_runtime.py): one
real ReAct actor using Wikipedia, with asynchronous speculative Searches.
Observation prediction uses **GPT-4.1 nano**; authoritative and hypothetical
reasoning use **Gemini 2.5 Flash**. Both are configurable.

Speculation keeps running while the main actor thinks. Prediction windows now
remain open until the answer, so a prediction can also help after an intervening
Lookup or another action. Required queries and existing cache entries suppress
duplicates. The real actor always uses true observations; it reuses a completed
prefetch or joins its remaining work. Optional inference leaves one serving slot
for the real actor. Every started request is drained and recorded.

The fresh 20-question pilot measured **7.01 s → 6.25 s mean answer time**. It is a
small exploratory result: the paired interval includes zero, and actor paths can
differ. Answer latency and total time including background work are reported
separately. See [the validation report](docs/ASYNC_SPECULATION_VALIDATION_2026-11-13.md)
for the recording checks, exact seconds, budget and fixed-path calculations.

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
  default. Legacy recordings retain legacy expiry; new ones retain episode windows.
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
