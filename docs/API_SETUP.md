# API setup

Use the [complete runbook](RUNBOOK.md) for the tested installation, no-key pilot,
credential setup, real-data collection, Jev/Kev context study and resume commands.

The main QA model (`QA_CHAT_URL`, `QA_MODEL`, `QA_API_KEY`) generates searches and
answers. Jev (`TYPESAFE_API_KEY`) and Kev (`KEV_BASE_URL`, optional `KEV_API_KEY`)
forecast demand. They are separate integrations. A Kev server must already be
running. `.env.example` lists optional token limits, model revision and prices.
Export `.env` explicitly; the application does not load it implicitly.

`python -m quota_spec.preflight` reports configuration without inference or
network calls. `--online` only fetches public Kev metadata. `--backend mock` and
`--predictor mock` never call external models. HTTP errors, malformed JSON,
invalid probabilities, excessive response sizes and timeouts are recorded without
credentials or response bodies. HTTP status codes are retained for diagnosis.

`quota_spec.collect_qa` and `quota_spec.forecast_bank` support atomic checkpoints
and `--resume`. `quota_spec.pipeline` connects collection, forecast banks, frozen
studies, the privileged reference, live validation and report generation.
Use a new output directory for new experiments; do not mix checkpoints after
changing code, corpus, model settings or task splits.

Adaptive one-off predictor replay remains available through `quota_spec.cli`:

```sh
.venv/bin/python -m quota_spec.cli --trace data/evaluation.json \
  --history-trace data/development.json --predictor jev --context progress \
  --capacity 3 --window-s .1 --horizon-s .3 --samples 4 --skip-reference \
  --output results/jev-adaptive
```

This performs new inference in each policy run; use forecast banks for the fixed
prediction full/own comparison. `--timeout-s` bounds an individual predictor
request; `--decision-timeout-s` bounds the combined decision inference. Missing
configuration fails before a run starts. Provider failures reject optional work
and remain visible in telemetry; they are not reported as successful predictions.
