> Preserved reference/extension documentation. The active concurrent baseline and
> current work order are [README](../README.md) and [next_steps.md](../next_steps.md).

The current prerequisite is the **single-agent Speculative Actions baseline**, before Jev or shared-quota experiments. Run `quota_spec.paper` for this stage. It never starts a forecast bank, admission controller or multi-agent study.

Current evidence is in [SINGLE_AGENT_RESULTS_2026-11-12.md](SINGLE_AGENT_RESULTS_2026-11-12.md): Gemini top-three reached the displayed 38.33% paper value, GPT-4.1 nano reached 36.67% versus 46.25%, and GPT-5 nano failed under the unchanged 100-token observation limit. Full three-model reproduction and live throughput remain unverified. Final validation has 142 passing tests with no skips.

The paper's [HotpotQA experiment and Appendix B.2](https://arxiv.org/html/2510.04371v2#S3.SS3) evaluate next-action agreement. They do not publish a HotpotQA throughput/latency improvement. The roughly 20% end-to-end result belongs to chess. Reproducing agreement, checking QA correctness and measuring live speed are separate tasks.

Figure 4 uses Gemini 2.5 Flash as the actor and these observation models:

| Observation model | Published top-one | Published top-three |
| --- | ---: | ---: |
| GPT-5 nano | 15.08% | 31.67% |
| GPT-4.1 nano | 18.75% | 46.25% |
| Gemini 2.5 Flash | 19.58% | 38.33% |

The authors' `run.py --getmetric2` and `Grapher.graph_metric3` compute both prefixes from the same candidate lists and average per-question accuracies, with standard error across questions. Each first action is excluded. Action-weighted micro accuracy and final-answer EM/F1 are different metrics. Our previous width-one, development/evaluation quota pilot was not this experiment.

The standalone baseline now uses the same tested, instrumented collector as canonical collection, with width three and raw candidate lists retained. It preserves the authors' prompts, action parser, observation-prediction-then-actor procedure, seven action iterations, dataset and intended seed-248 question order. Authoritative and hypothetical state remain isolated, including pre-tool Lookup state; failed generation episodes stop with partial evidence rather than becoming malformed successful traces. Timings include tool retries and actual reset indices are recorded.

For the active OpenRouter configuration in the authors' `run.py`, actor and speculative-actor requests use 1,000 output tokens, temperature 1 and top-p 1. Observation requests use 100 output tokens, temperature 0.1 and top-p 0.9. Both have the original system message. No new reasoning flags or JSON mode are inserted. The alternative native Gemini SDK path ignores those settings; it is not interchangeable with the OpenRouter path. The 100-token cap can truncate observation predictions and is reported rather than silently increased.

The upstream scorer has a separate caveat: `k=3` accepts any candidate in an over-width list. Our report preserves that upstream score **and** reports strict first-one/first-three scores and actual requested-width violations. Stateful Lookup and Finish are never treated as interchangeable cached Search results.

Public-reference verification is stored in [reference-audit.json](../results/paper-single-agent-audit/reference-audit/reference-audit.json). We downloaded 91 files at pinned commit `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c`, verified Git blob and SHA-256 identities, and exactly recomputed the stored scores of all 22 complete saved trajectories across six model/width cells. These are small public subsets, not the complete Figure 4 evaluation. None of the 22 folder IDs identifies its actual question; 21 actual questions were recoverable from their prompts and one was unresolved. This confirms the reset-index defect. Their subset averages also differ from the published chart. Exact historical sample/model-output reproduction therefore cannot be claimed from these files.

Key-free checks:

```sh
.venv/bin/python -m quota_spec.paper --prepare-only
make paper-offline PAPER_OUTPUT=results/single-agent-offline-fresh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests scripts
git diff --check
```

Single-agent actual-model collection, using a fresh output directory and an explicit request budget:

```sh
set -a
source .env
set +a
.venv/bin/python -m quota_spec.paper \
  --backend http --actor google/gemini-2.5-flash \
  --speculator google/gemini-2.5-flash --count 20 --width 3 \
  --max-requests 448 --output results/single-agent-gemini-fresh
```

A request cap is not a dollar guarantee. The current review uses a separate per-request dollar guard with a combined $0.50 ceiling across the previous pilot and this reproduction work; do not copy credentials into scripts or artifacts. Changing the observation model to `openai/gpt-4.1-nano` or `openai/gpt-5-nano` selects the other published pairings, subject to compatibility and the remaining budget.

Artifacts are `config.json`, `traces/collection_config.json`, raw `traces/tasks/`, all attempted calls in `traces/inference.jsonl`, `outcomes.json`, `summary.json` and `REPORT.md`. Answer scores stay null for mock runs. Raw lists, truncation, incomplete episodes, actual model/provider identity and billed costs remain auditable. Existing output directories are never replaced.

`summary.json` explicitly distinguishes a comparable configuration from an established reproduction. It also includes a **Search-only no-quota counterfactual timing diagnostic**, using measured dependency delays and exact candidate identities, with no additional model calls. This is an engineering diagnostic; it is not a measured live speedup or a result published for HotpotQA. Wrong-branch resource contention, live scheduling and full stateful-tool execution fidelity require separate validation.

The extension is not scientifically ready merely because unit tests pass or a point estimate resembles a chart bar. Review the complete model pairings, actual questions, candidate widths, macro agreement and uncertainty, QA outcomes and live timing evidence first. Preserve neutral or negative results. The earlier quota evidence remains intact in [INDEPENDENT_REVIEW_2026-11-12.md](INDEPENDENT_REVIEW_2026-11-12.md); it does not establish this prerequisite.
