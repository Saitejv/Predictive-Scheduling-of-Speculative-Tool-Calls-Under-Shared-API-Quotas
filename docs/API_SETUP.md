# Run now, connect models later

Everything in the first section runs without API keys, paid inference, model
weights, or a dataset download. Run commands from the repository root.

## Offline verification

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[live,analysis]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m quota_spec.preflight --output results/access-offline
.venv/bin/python -m quota_spec.cli --trace data/evaluation.json --history-trace data/development.json --predictor mock --capacity 3 --window-s .1 --expected-duration-s .015 --horizon-s .3 --samples 4 --skip-reference --output results/mock-api
.venv/bin/python -m quota_spec.qa --backend mock --count 4 --output results/mock-qa
```

Installing packages requires an internet connection unless they are already
cached. The commands after installation do not. Replay, history, the in-process
gateway and mock QA use the standard library; mock System One serialization and
the HTTP server require the `live` extra. Preflight only fetches public metadata
when explicitly given `--online` and never performs inference.

`--predictor mock` exercises the real System One request serialization and
response validation with `httpx.MockTransport`. Probabilities are fixed fixtures.
QA mock answers are synthetic; answer-quality scores remain null. Neither mock
is evidence of Jev/Kev calibration or real QA accuracy.

## Environment

```sh
cp .env.example .env
# Edit .env locally, then export its values into this shell:
set -a
source .env
set +a
```

The application deliberately does not load `.env` implicitly. The example is
tracked; `.env` and other `.env.*` secret files are ignored. No real credential
is included. Environment changes affect subsequently started processes.

## Demand predictors: Jev and Kev

Jev requires `TYPESAFE_API_KEY`. `JEV_BASE_URL` and `JEV_MODEL` can override its
endpoint and model. The adapter follows the official
[System One contract](https://docs.typesafe.ai/api/system-one).

Kev requires `KEV_BASE_URL` pointing at a running
[Kev System One server](https://github.com/jaredpalmer/kev).
`KEV_API_KEY` is optional for servers protected with bearer authentication;
`KEV_MODEL` selects the request model. A Jev key does not provide a Kev server.
Both base URLs may include `/v1`; the adapter adds the remaining endpoint once.
Keep the actual server/weight revision with experiment records.

```sh
.venv/bin/python -m quota_spec.cli --trace data/evaluation.json --history-trace data/development.json --predictor jev --context progress --capacity 3 --window-s .1 --expected-duration-s .015 --horizon-s .3 --samples 4 --skip-reference --output results/jev
# Substitute --predictor kev to use the configured Kev server.
```

This command makes real calls only when `jev` or `kev` is selected. Start with a
small disjoint trace when checking new credentials. Missing configuration fails
at startup. HTTP errors, invalid probabilities, oversized responses and timeouts
reject speculation and are recorded in `inference.jsonl`; a fallback is never
reported as successful model inference. `metrics.json` includes failure counts.

Use `--timeout-s` for each request and `--decision-timeout-s` for the combined
forecasting budget across all agents in a decision. External runs charge measured
decision latency, including failures, to replay. History and mock runs use frozen
modeled overhead and remain reproducible. Real model runs must be retained as
measured artifacts; they are not deterministic reruns.

Token usage is recorded where supplied. Monetary cost remains null unless both
`--input-usd-per-million` and `--output-usd-per-million` are specified. Set zero
explicitly for a free token category. Credentials and response error bodies are
not written to telemetry. Task queries and tool results are experiment data and
are intentionally present in run artifacts.

## Predictive live gateway

Set these values in `.env`, export them, and restart the gateway:

```sh
QUOTA_POLICY=predictive
QUOTA_PREDICTOR=history
QUOTA_HISTORY=data/development.json
```

Use `mock`, `jev`, or `kev` for `QUOTA_PREDICTOR` to switch providers. Other
available policies are `no_speculation`, `current_capacity`, `fixed_reserve`,
`usage_forecast`, and `own_agent_only`. See `.env.example` for quota, horizon,
risk, timeout and price settings.

```sh
.venv/bin/python -m uvicorn quota_spec.gateway:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

`POST /observe` accepts `task_id`, `task_context`, `completed_calls`,
`result_excerpt`, and optional `deadline_s` measured from gateway startup.
`POST /required` and `/candidate` accept `task_id` and `query`. Candidate replies
contain only admission status. Each task is a serial chain: concurrent identical
required calls join, while conflicting concurrent required calls return 409.
Concurrent duplicate waiters count as one progress transition. A later completed
cache request is a new logical step; clients needing retry idempotency across
completed responses should track their own step IDs.

Call `POST /finish/{task_id}` when an agent exits. This removes its progress and
cached results and cancels unused running speculation without refunding quota.
Use a new task ID for independent tasks. At most one eligible candidate is
considered for each observed completed-call count. Call progress cannot move
backwards, and `/observe` cannot replace progress during a pending required call.
One worker is required: ledger/registry state is process-local.

## Main QA agent

Jev and Kev forecast demand; the main QA model is a separate integration. Set:

- `QA_CHAT_URL`: complete chat-completions URL, including its path.
- `QA_MODEL`: an available model supporting text chat completion.
- `QA_API_KEY`: bearer token, or empty for a local unauthenticated service.

The endpoint must accept `model`, `messages`, and `max_tokens`, and return
`choices[0].message.content` with the JSON action requested in the prompt.
Provider-specific APIs or models requiring different request parameters need a
small adapter change; no provider account has been tested locally.

```sh
.venv/bin/python -m quota_spec.qa --backend http --count 4 --agents 2 --max-calls 3 --output results/qa-http
# To use the environment-selected predictor with the main model:
.venv/bin/python -m quota_spec.qa --backend http --policy predictive --count 4 --output results/qa-predictive
```

The default comparison covers three baseline policies. Search budgets, contexts,
response bytes and total request time are bounded. The same observed-state
candidate generator is used across policies. Gold labels are loaded after the
agents finish and never enter model prompts. Actual answers get normalized exact
match and token F1; failed tasks count as zero. Per-task outcomes, gateway events,
main-model telemetry and predictor telemetry are saved separately. These are
independent live runs whose model choices can differ, not paired frozen replay
or a guarantee of equal final answers. Collection of frozen LLM trajectories and
real Jev/Kev context-ablation measurements remains experimental work.
