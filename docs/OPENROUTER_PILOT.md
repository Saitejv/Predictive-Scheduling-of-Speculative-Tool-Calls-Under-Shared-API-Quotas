# OpenRouter preliminary pilot: November 12, 2026

**Scope correction:** this is the local-BM25/direct-query adaptation, not a
reproduction of Speculative Actions. Its negative result does not establish
anything about the paper's HotpotQA pipeline. The replacement canonical workload
and initial upstream smoke test are documented in [PAPER_ALIGNMENT.md](PAPER_ALIGNMENT.md).

The hosted integration works, but this pilot does not establish a speculation
speedup. Proposals arrive early enough; exact search-query agreement is poor.
Kev was omitted as requested. Credentials are held only in the private,
Git-ignored `.env`, not in experiment artifacts.

## Models and timing

| Role | Requested model | Configuration |
| --- | --- | --- |
| Main QA | `deepseek/deepseek-v4.1-flash` | Low reasoning, JSON mode, 4096 output tokens, 60 s timeout |
| Speculator | `openai/gpt-oss-120b` | Low reasoning, JSON mode, 512 output tokens, latency routing, 5 s timeout |
| Demand/reuse | `typesafe/jev-1.14` | OpenRouter Decisions API, 5 s request timeout |

The initial three-prompt comparison measured median full proposal latency of
0.936 s for GPT-OSS 120B and 1.586 s for GPT-OSS 20B. The observed routes were
BaseTen and CoreWeave respectively. Provider deployment mattered more than total
parameter count. This is a small routing snapshot, not a provider benchmark.
The probe preceded the added instruction to search before answering without
evidence, so its main-model timings are not pooled into the pilot.

For completeness, median output tokens divided by full request time was about
77 tokens/s for 120B and 146 tokens/s for 20B in the probe. These figures include
reasoning tokens, input processing and network time; they are not isolated decode
throughput. 120B produced fewer tokens and delivered its proposal sooner. The
pilot's live stages also exercised two concurrent agents.

In the ten-task collection, median full request latency was 0.838 s for the
Speculator versus 1.820 s for DeepSeek. All 22 Speculator calls completed before
the main action; 20 proposed queries and two abstained. Only one of the 12
required searches had an exact matching proposal; that match was in development.
None of the six held-out required searches matched a proposal.

## Fixes and execution semantics

- Main inference and the Speculator start from the same observed history.
  The Speculator is cancelled when the main JSON action completes. It is not
  stopped when the main request starts or when its first token arrives.
- An on-time proposal starts admission while main inference continues. Required
  searches never wait for optional proposal or admission work. Replay follows
  the same timing rule and rejects stale inference results.
- Pending admission tasks are cancelled at every phase boundary, preventing a
  queued proposal from being applied to a later agent step. Prediction threads
  are drained safely; Python cannot interrupt an already running thread.
- Jev accepts an `/api/alpha` base and calls `/decisions`. OpenRouter fractional
  `usage.cost` is recorded independently from integer token counts and takes
  precedence over token-price estimates. Provider/model identifiers, truncation
  reasons, cancellation and failures are retained without credentials.
- Reasoning effort, JSON mode and provider sorting are configurable and included
  in checkpoint identity. QA is instructed to obtain search evidence before
  answering. Mock QA has a small synthetic delay so the offline pipeline still
  exercises speculation.

Cancellation closes the local HTTP request; it does not guarantee that upstream
compute stops or becomes free. Missing cancellation usage remains unknown.
Cancellation paths were tested with controlled transports; no paid request in
this pilot required cancellation. Complete JSON actions are consumed, without
token streaming or time-to-first-token measurements.

## Experimental results

Collected ten tasks, split five development/five evaluation, with at most three
required searches per task. Exact match and F1 were both 60% across all ten,
80% on development and **40% on the five held-out tasks**. Wrong and no-search
answers remain in the data; gold answers never enter model inputs.

Five Jev context banks used 129 unique requests in total. Frozen replay evaluated
18 policies across 12 quota/load settings and three seeds: 648 aggregate rows.
The base condition uses four-agent batches and three dispatches per 10 s window.

| Policy | Mean completion (s) | Delta from no speculation (s) |
| --- | ---: | ---: |
| No speculation | 10.7301 | 0 |
| Current capacity | 15.7941 | +5.0640 |
| Fixed reserve | 12.2955 | +1.5654 |
| History predictive, full | 11.1755 | +0.4454 |
| History predictive, own agent | 13.4076 | +2.6775 |
| Jev progress, full | 10.7301 | 0 |

Jev rejected every candidate in the base setting for all five contexts, avoiding
wasted quota and matching no speculation. The full history rule reduced harm
relative to its own-agent ablation, but still did not beat no speculation.
The generated report retains paired seed intervals. Five evaluation questions
and three seeds are insufficient for broad statistical conclusions.

The initial live validation ran two held-out tasks under each of ten policies:
20 task executions, zero QA/Speculator/predictor errors, and valid quotas in all
runs. Each policy obtained 50% exact match/F1 on those two questions.
After tightening cancellation at every phase boundary, a separate final check
repeated those two tasks under no speculation, current capacity and Jev full:
six more task executions, no inference failures, valid quotas, and 50% EM/F1.
These are independent stochastic model runs and are not causal latency comparisons.

Final verification: **110 unit tests passed**, Ruff lint/format and whitespace
checks passed, and a complete four-task mock pipeline with five context modes,
12 settings and live validation passed with socket connections blocked.

## Cost and artifacts

Total spend is approximately **$0.03**. The account snapshot after testing reported
$0.02744 used and $4.97256 remaining from the $5 limit. Saved response costs total
$0.02875 including probes, pipeline and the final check; the account snapshot and
individual response costs are retained separately rather than forced to agree.
There were 304 measured inference requests overall, including probes, with zero
inference errors. The pipeline plus final validation accounts for 294 requests
and $0.02623 of response-reported charges. No unknown response costs remain in
these runs. Frozen replay incurred no new model charges.

- [Generated experiment report](../results/openrouter-pilot-2026-11-12/REPORT.md)
- [Original pipeline configuration](../results/openrouter-pilot-2026-11-12/pipeline_config.json)
- [Final validation source identity](../results/openrouter-pilot-2026-11-12/final_validation_config.json)
- [Inference totals, including final validation](../results/openrouter-pilot-2026-11-12/inference_summary.json)
- [Final live validation](../results/openrouter-pilot-2026-11-12/live-final/summary.json)
- [Latency probe](../results/openrouter-preliminary/latency-probe.json)
- [Account snapshot](../results/openrouter-preliminary/account-after.json)

Original pipeline artifacts preserve the source hashes used for that run. The
later phase-boundary cancellation fix has its own source identity and live check;
it does not rewrite collection or replay provenance. The retained pipeline
directory cannot be resumed with changed source. Use a fresh directory:

```sh
set -a
source .env
set +a
.venv/bin/python -m quota_spec.pipeline \
  --backend http --predictors history jev --count 10 \
  --contexts task history progress no_history no_progress \
  --max-calls 3 --window-s 10 --seeds 7 17 27 --samples 4 \
  --live-count 2 --qa-timeout-s 60 --predictor-timeout-s 5 \
  --max-requests 200 --output results/openrouter-next-pilot
```

The next experiment should improve query agreement and retrieval answer quality
before increasing task count. Exact argument matching is intentional: semantic
similarity alone cannot authorize reuse of a different tool call.

API references: [OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev),
[Decisions contract](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request),
[DeepSeek model](https://openrouter.ai/deepseek/deepseek-v4.1-flash),
[GPT-OSS 120B model](https://openrouter.ai/openai/gpt-oss-120b).
