# Canonical workload: upstream Speculative Actions HotpotQA

**Latest correction:** [SINGLE_AGENT_REPRODUCTION.md](SINGLE_AGENT_REPRODUCTION.md)
supersedes the earlier readiness interpretation below. Matching the authors'
OpenRouter request parameters is supported by their `run.py`; the separate
direct-Gemini SDK path has different defaults and is not interchangeable.
The public saved logs contain actual questions different from their folder IDs,
so the intended seed-248 sample is not a verified historical evaluation sample.
Figure 4's top-one and top-three scores are computed from the same candidate lists
by the authors' plotting path. A width-one quota pilot cannot reproduce that pair.

The controller is now connected through [PAPER_PIPELINE.md](PAPER_PIPELINE.md).
This document records the upstream agreement baseline and the workload alignment
audit. Use `quota_spec.paper_pipeline` for the paired multi-agent experiment;
`quota_spec.paper` is the separate serial upstream baseline.

The earlier local-BM25 pilot changed the retrieval environment, action schema,
prompts and speculation target. It is an integration test of that adaptation,
not a reproduction of the paper. Its latency regressions cannot be used to
assess the original HotpotQA experiment.

The October proposal explicitly selected a local HotpotQA subset and one search
endpoint. That explains the implementation history. The user's November 12
instruction supersedes that adaptation for the paper comparison: retain the
upstream workload and add shared quotas and cross-agent admission around it.

## What is held fixed

The baseline entry point is `python -m quota_spec.paper`. It downloads and verifies
the authors' files at commit `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c`, retaining
their Apache license and pristine source. Git blob and SHA-256 checks cover every
downloaded source, prompt and dataset file. Cached source is revalidated on reuse.

| Component | Canonical baseline |
| --- | --- |
| Dataset | Authors' `hotpot_dev_v1_simplified.json`, all 7,405 available rows |
| Sample order | Authors' seed 248 and permutation; first 20 indices |
| First two questions | 7107, then 5619 |
| Agent | Authors' ReAct runner and six-shot prompt |
| Tools | Authors' live Wikipedia Search, stateful Lookup, Finish |
| Speculator target | Predict the pending tool observation; actor reasons on that branch |
| Width | Original single- and three-candidate modes |
| Actor model | Gemini 2.5 Flash |
| Paper's Speculators | GPT-5 nano, GPT-4.1 nano, Gemini 2.5 Flash |
| Initial smoke pairing | Gemini 2.5 Flash in both roles through OpenRouter |
| Agreement scoring | Authors' metrics implementation, including its case folding |

The source paper's HotpotQA section reports next-action agreement up to 46%
with three candidates. It does not establish the end-to-end HotpotQA latency
reduction we previously implied. Today's model routing and live Wikipedia can
change outputs and timings; matching workload definitions is not a guarantee
of reproducing historical numerical results.

## Explicit compatibility fixes

The downloaded source is unchanged. Runtime adapters make these narrowly scoped
corrections, recorded in every run's configuration:

1. `HistoryWrapper.reset` originally drops the requested task index, causing
   NumPy to choose an unrelated question. Forwarding the index enforces the
   authors' intended seeded sample order.
2. Simulated tool calls originally overwrite the real Wikipedia page, lookup
   cursor and other environment state. Saving/restoring authoritative state
   prevents hypothetical observations from affecting the real trajectory.

An OpenRouter transport replaces SDK wiring, using the authors' OpenRouter
request parameters and original prompts. Credentials stay in environment
variables; each inference record retains costs and provider identity. The runner
uses Gymnasium 0.29.1 because its wrappers expect that version's attribute
forwarding behavior.

The upstream action parser can return more candidates than requested if the
model violates the prompt. This baseline retains that behavior and records raw
candidate lists. Consequently it must not be described as a strict top-three
implementation without checking candidate counts. The first smoke run had an
over-width first-step list, which the upstream metric excludes from scoring.

## Initial smoke result

Two tasks completed in the upstream environment, using 29 paid model requests
with zero inference failures and response-reported cost **$0.01497**. Question
7107 finished correctly in three actions. Question 5619 exhausted its seven
actions and failed, which remains in the results. This verifies the runtime
path, not answer quality or a speedup. The upstream script generates and scores
branches serially; its script wall time is not speculative execution latency.

Validation: 116 tests pass. New checks verify the upstream task order, reproduce
and correct index loss, keep simulated searches/lookups out of real state, and
confirm that the adapter preserves the real tool's observation. Ruff and
whitespace checks pass. The prepared baseline revalidates without network access.

Artifacts:

- [Configuration and file checksums](../results/paper-upstream-baseline-2026-11-12/config.json)
- [Question outcomes](../results/paper-upstream-baseline-2026-11-12/outcomes.json)
- [Inference summary](../results/paper-upstream-baseline-2026-11-12/summary.json)
- [Original two-question prompt and tool logs](../results/paper-upstream-baseline-2026-11-12/tasks)

The old direct-query model sweep was stopped after the user's correction. Its
partial responses are retained under `results/speculator-model-comparison-2026-11-12`
with a `STOPPED.json` marker, and are not used to select the canonical workload.

## Run the canonical baseline

```sh
.venv/bin/python -m pip install -e '.[paper]'
.venv/bin/python -m quota_spec.paper --prepare-only
set -a
source .env
set +a
.venv/bin/python -m quota_spec.paper \
  --actor google/gemini-2.5-flash --speculator google/gemini-2.5-flash \
  --count 2 --width 3 --max-requests 64 --output results/paper-baseline-next
```

Use `--width 1` for the upstream single-candidate condition. `--count 20` takes
the full original seeded sample; set an appropriate explicit request budget.
No existing run directory is overwritten. Inference and partial trajectories
are retained if a request fails.

## Boundary for the project contribution

The next extension comparison must keep these questions, tools, prompts and
observation-speculation branches fixed, and add concurrent independent agent
instances plus the shared search quota. No-speculation, original speculation,
fixed reserve and Jev-controlled cross-agent admission must use that same base.
The quota/replay schema now retains all ReAct actions and gates only Search.
`quota_spec.paper_pipeline` collects this workload and runs the shared controller
on frozen trajectories/candidates/forecasts. The standalone `quota_spec.paper`
and its older smoke test remain serial agreement measurements and do not claim
a latency win. A live upstream actor/gateway fidelity run remains separate work.

References: [paper](https://arxiv.org/html/2510.04371v2),
[upstream repository at the pinned commit](https://github.com/naimengye/speculative-action/tree/dc938b9ef7474caf07fe4ad16549c1fa8c7d268c/hotpotqa),
[project proposal](../CSE_585_Project_Proposal_oct_23.pdf).
