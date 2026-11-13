> Preserved reference/extension documentation. The active concurrent baseline and
> current work order are [README](../README.md) and [next_steps.md](../next_steps.md).

Latest user direction supersedes this earlier quota-study handoff: **establish the
single-agent Speculative Actions baseline first; defer Jev and multi-agent work**.
Read [SINGLE_AGENT_REPRODUCTION.md](SINGLE_AGENT_REPRODUCTION.md) and the latest
single-agent results before proceeding. The instructions below are retained as
the historical handoff that produced the earlier independent review, not a new
authorization to launch another Jev/shared-quota pilot.

Work in `/Users/saitejvelaga/Documents/umich/cse585/project`.

Independently review and test the refactored canonical HotpotQA shared-quota
experiment. Read `docs/PAPER_PIPELINE.md`, `docs/PAPER_ALIGNMENT.md`,
`docs/ARCHITECTURE.md` and the relevant code before running paid experiments.
The workspace contains pre-existing uncommitted changes: preserve them, do not
reset/clean the repository, and do not commit or publish unless requested.

The research question is whether cross-agent admission improves system-wide
completion time relative to an otherwise identical owner-only rule. Preserve the
authors' pinned HotpotQA data/order, ReAct prompts, Wikipedia Search/Lookup/Finish,
and observation-prediction-then-actor speculation. Jev forecasts demand/reuse;
our controller decides whether a proposed optional Search should spend shared
quota. This is bounded approximate optimization, not a guaranteed global optimum.

The implementation entry point is `python -m quota_spec.paper_pipeline`:
`paper_collect.py` collects fixed top-one branches, `paper_pipeline.py` freezes
forecasts and runs `experiments.run_study`, and `replay.py` retains all ReAct
dependencies while charging/caching only Search. `quota_spec.paper` separately
runs the upstream serial agreement baseline. The old `quota_spec.pipeline` and
local-BM25 results are legacy fixtures and must not be used for the new results.

First review and run local checks:

```sh
.venv/bin/python -m pip install -e '.[paper,live,analysis,dev]'
.venv/bin/python -m quota_spec.paper --prepare-only
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests scripts
git diff --check
.venv/bin/python -m quota_spec.paper_pipeline \
  --backend mock --count 8 --predictors mock \
  --contexts task history progress no_history no_progress \
  --seeds 7 17 --samples 4 --window-s .1 --no-plots \
  --output results/paper-independent-offline
```

Use fresh output names if any directory exists. Ensure the optional upstream
integration tests actually run rather than all being skipped. Verify the mock
pipeline with sockets blocked after the public source has been prepared.
The implementation turn passed 124 tests; independently verify this count and
investigate any differences. Mock results must have null EM/F1 quality scores.

Audit these invariants, extending tests or fixing bugs where necessary:

1. True and hypothetical Wikipedia states never mix. Lookup cursors remain
   stateful, repeated Lookup is not cached, and Finish spends no search quota.
   Selected question indices reach the actual environment reset.
2. Every ReAct action and authoritative model delay survives normalization.
   A speculative proposal is released from the preceding real tool's dispatch,
   including observation-model plus speculative-actor latency. Quota waiting
   shifts it; late/tied proposals cannot delay or duplicate required work.
3. Search quota is atomic, survives cancellation/completion until refill, and
   required ordering is fixed across admission comparisons. Exact-result reuse
   does not charge twice. No case/synonym equivalence is silently introduced.
4. Forecasts see only observed state, including pending-owner cases. No current
   uncompleted response, future query or evaluation answer leaks into inputs.
   History predicts future Search demand while accounting for intervening local
   actions. Timing distributions and tuning use development tasks only.
5. Full/own-agent policies share the exact same frozen candidate traces, forecast
   bank, scenarios, inference cost and risk guard. Only the gain objective differs.
   Replay must make no new model calls. Audit prediction fallbacks, not just crashes.
6. All attempted model calls, including failed/aborted stages, remain in costs.
   Check source/data hashes and resume safety. Do not edit saved hashes to force
   a resume after code changes. Preserve useful paid checkpoints and raw logs.
7. Requested agent count is not actual concurrency when a pilot is too small.
   Inspect `max_active_agents` and batch sizes. A four-task collection has only
   two held-out tasks and cannot establish four/eight-agent scaling.

After local checks pass, run a bounded actual-model smoke test using the existing
OpenRouter credentials in the private `.env`. Do not print the key, put it in
commands/prompts/artifacts, or overwrite the environment file. Read account usage
privately first. Spend **at most $0.50 additional total** in this testing turn,
including any model probes and Jev calls, and stay within remaining account
credit. The request limits below are additional bounds, not dollar guarantees.
Track usage/cost during testing and stop paid work before exceeding the budget.
Do not launch a broad model sweep or try to force a positive result.

```sh
set -a
source .env
set +a
.venv/bin/python -m quota_spec.paper_pipeline \
  --backend http --actor google/gemini-2.5-flash \
  --speculator google/gemini-2.5-flash --count 4 \
  --predictors history jev --contexts progress --seeds 7 17 \
  --samples 4 --window-s 10 --max-requests 128 \
  --max-forecast-requests 200 --no-plots \
  --output results/paper-independent-paid-smoke
```

Validate output schemas, model compatibility/truncation, actual QA scores, costs,
forecast failures and quota accounting before scaling. If the smoke is clean and
the remaining incremental budget safely covers it, collect the original seeded
20-question sample in a new run (`--count 20`, a consciously chosen request cap,
the same models and progress context) for actual 1/2/4/8-agent batches. Otherwise
report the smoke result and the budget limit without treating it as scaling evidence.
The width is fixed at one; do not compare it directly with the paper's top-three
46% agreement headline. Keep answer correctness separate from exact next-action
agreement and from latency.

Assess `jev_progress_full` versus `jev_progress_own` first, followed by the
no-speculation/current-capacity/reserve controls and history ablation. Report
mean and p95 completion, required-search wait, per-agent delay, deadline completion,
unused calls, inference overhead, exact reuse, EM/F1 and money spent. Accept zero
or negative speedups. The controller is an approximation; do not claim global
optimality. These are paired **replay** outcomes from fixed measured trajectories;
independent live ReAct/gateway fidelity is not implemented and remains a separate
validation task. Do not describe collection wall time as speculative speedup.

Return a concise report explaining what passed, bugs found/fixed, remaining
limitations, exact model/settings/task counts, actual concurrency, result and
log paths, additional spend and account headroom. Preserve raw evidence. Make
necessary correctness fixes, but leave broad redesign or a larger study for our
next review. Do not create a new chat, spawn agents, commit, or publish as part
of this handoff unless I separately ask.
