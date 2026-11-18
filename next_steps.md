# Current handoff

Updated November 17, 2026. The current user direction authorizes API spending
for making the multi-agent Jev context-engine idea work. It supersedes the older
single-agent-only priority and earlier $0.50 testing-turn limits. Keep individual
experiments explicitly bounded, retain all attempts and preserve existing paid
evidence. Do not commit or publish without a request.

## Actual joint query-planner controlled test

Read [the full test](docs/QUOTA_TEAM_TEST_2026-11-17.md). Raw matrix:
`results/quota-team-test-2026-11-17-paced`, stopped initial trial:
`...-controlled`. 16 historical eval questions × 4 scenarios × 2 orders,
24 paid speculative schedules + 8 no-spec controls = 32 schedules, 512 replayed
episode completions. 765 successful API calls actually generate fresh queries
using the current quota/quota_team template, **not** the earlier fixed-candidate
gate. Saved observation-prediction prefixes/times and all main paths/results/
answers remain fixed. Search has a declared constant 0.1s or 3s response time,
both required and optional. It is counterfactual scheduling, not a native Search
benchmark. Full uses a quota-blind version of the same prompt and step-4 budget.

Primary metric now counts queued-work latency: all 16 questions ready at t=0,
mean `task_finish_s`. Prior worker-relative metric (finish minus task start) is
reported separately; do not mix the two clocks. Combined vs quota-only queued
latency: +6.33% slower (4/C8/5/0.1s), 0.27% faster (4/C8/5/3s), 5.03% faster
(8/C12/3/0.1s), 0.02% slower (8/C12/3/3s). The useful 8-worker fast-search win
also improves batch time 5.11% in both orders, but no speculation still wins.
4-worker slow Search beats no/full on mean and batch with either quota-aware
method; extra peers do not provide a reliable additional win. No default change.

Shared live/replay context serializer added. Live demand counter now counts
returned required Search actions including cache hits, matching replay, instead
of only misses entering the queue. New audit metadata identifies the convention;
old captures preserve old semantics. The counter regression, replay fresh-query
hook and independent all-765-context provenance/FIFO/quota audit pass. 291 tests,
Ruff (140 files) pass. No new native questions used: next unused offset stays346.

Initial unpaced attempt: 58 calls, 5 upstream shared-pool 429s, retained; matrix
was restarted with predeclared .75s inter-collection gap excluded from simulated
service. Genuine retry/backoff remains charged. Completed matrix has zero API
failures/retries. Total 823 attempts / $0.35091159 known charges, exact account
usage-delta reconciliation; 5 unknown individual failed receipts retain .0354497
reservation, total budget charge .38636129. No API/provider limit changes.

Storage recovered by transparently compressing 27 older JSONL logs, SHA-verified,
no data/paths removed. Manifests `results/quota-team-test-2026-11-17-lossless-*
.json` retain allocation changes. Compact results are under
`docs/evidence/quota-team-test-2026-11-17`. All jobs completed, no paid job running.

## Explicit combined quota/peer planner

Read [the follow-up](docs/QUOTA_TEAM_2026-11-17.md). `quota_team` is an explicit
alias for combined API and observed-peer context. The query-planner prompt now
uses peer phase/progress/history/results/returned intent to estimate demand
before refill; the worker-count reserve is only a missing/uncertain-context
fallback. Both quota-only and combined use the same updated instructions.
The `team` alias remains supported. This is the actual query generator, separate
from the earlier fixed-candidate admission gate. Main actors see neither quota
nor peer context. No default change away from Jev.

A new native check compares quota_team/quota on eight new questions, offsets
338–345, 4 workers C8/5s, generation budget 4. All 16 episodes finish with zero
actor/optional failures, zero Jev calls, valid quota/FIFO/peer audits. Combined
mean 8.788s vs quota-only 8.223s, batch 21.099s vs 21.208s. Independent actor
paths have 39 versus 37 actions; do not call the batch difference a speedup.
All 20 combined contexts contain both quota and peers. Next unused offset346.
288 tests and Ruff (137 files) pass. New known API receipts: $0.0687131/156 calls.
Artifacts: `results/quota-team-2026-11-17-*`, compact live report under
`docs/evidence/quota-team-2026-11-17`. All recordings are retained. Disk space
was down to ~412MiB at the final run: check free space before further paid runs.

## Latest peer-context and Search-time work

Read [the November 17 report](docs/TEAM_CONTEXT_2026-11-17.md). Artifacts are
`results/team-context-2026-11-17-*`; compact CSVs, audits and plot are tracked under
`docs/evidence/team-context-2026-11-17`. No data was deleted. No new commit/push.

900 fixed-path schedules cover 80 evaluation questions, five worker counts,
C=1,000,000/3s, C=12/3s and C=8/5s, native/0.1/1/3-second Search service,
three orders and no/full/full-step4/Jev-owner/Jev-global. Seven aggregate settings
beat both baselines on mean and all-background batch time. The useful larger
wins are 4 workers C8/5 with 3s Search and 8 workers C12/3 with 3s Search;
all three orders favor Jev on both endpoints against both baselines.
8 workers C8/5 with 3s Search has a tiny mean win but a batch loss—do not call it
a global win. For constant Search settings, forecast service duration gets the
same known configuration; development probabilities and actor/generation timing
are unchanged. This is counterfactual replay with unlimited provider service.

A separate 8-question pilot uses actual Gemini calls to gate saved candidates:
quota vs phase/progress vs full observed peer context. This **new admission gate
is not the existing live quota-aware query generator**. 24 valid paid schedules,
548 valid calls; no consistent advantage from the larger semantic payload.
Two earlier schema failures are retained and charged (115 calls). The corrected
schema enumerates only the supplied query, and dispatch still validates exact
identity. The independent audit validates all 548 observed contexts against
returned actions, result excerpts and returned intent. Jev-owner still sees all
forecasts; only its gain objective changes, so it is not a no-sharing ablation.

The live runtime also now supports `--speculation-planner team`, keeping its
query-planner instructions while appending bounded observed peer state. Two
8-question native smoke batches on new offsets 330–337 completed cleanly with
independent context/quota/FIFO audits, but independent actor paths make their
speed comparison descriptive only. Next unused live offset: 338. Do not turn
this opt-in option into the default based on the small gate pilot.

287 tests pass; Ruff passes for 137 files. Total new API spend $0.27274865,
825 calls, no unknown costs, exact account-delta reconciliation. Source snapshots
and gzip schedules retained. No paid jobs remain running. The next useful work
is a larger repeated-order fixed-candidate gate study (especially compact peer
progress), followed by a prospective live test; do not claim more context alone
is a demonstrated improvement. Preserve the earlier held-out native Jev proof
as separate evidence.

## Latest speed-only scenario comparison

Read [the speed tables](docs/SPEED_SCENARIOS.md). New live runs fill 1-agent
unconstrained (verified nonbinding C=1,000,000), 1-agent C=12/3s, and 6-agent C=12/3s.
The main table reuses only the common first-seed 2/4/8-agent runs for consistent
8-question samples; it does not mix in the older two-seed averages. All four
styles are present. Do not present these live observations as isolated causal
policy speedups: the six-agent full-speculation run has a 30.218s actor tail.
A separate 80-question fixed-path table covers no/full/Jev for all scenarios;
quota-aware LLM results cannot be copied into it without dynamic context data.
Added API cost: $0.190243988, reconciled; one recovered attempt retains a
$0.0064369 unknown-cost reservation. All 281 tests pass. New controller/report
sources and live/replay artifacts are under `scenario-speed-2026-11-15-*`.
The original 80-question primary Jev win remains separate evidence.

## Latest multi-agent matrix

Read [the scaling table](docs/MULTI_AGENT_SCALING_2026-11-15.md). Two complete
192-episode matrices compare 2/4/8 agents and 8/5s vs 12/3s quotas on the same
eight questions with two common actor seeds. Quota epochs now start at batch
dispatch. Actual actor prompts remain quota-free. No universal dual-baseline win
was established; quota-aware was faster than Jev in four settings, Jev scored
higher on exact match in five. Keep the earlier controlled 80-question result
separate. All 281 tests and 48 independent run audits pass.
Total new charges: $0.953237138 including the retained storage failure and two
budget-probe runs. $0.0006088 has only an aggregate account receipt. About $0.509
of the configured daily allowance remained at the final account check.
Raw evidence paths and byte content survived content-verified storage dedup and
transparent compression. Main data: `results/multi-agent-2026-11-15-final` and
`results/multi-agent-2026-11-15-repeat`; combined report in `...-comparison`.
Next unused offset: 330. Future confirmation needs larger question batches and
controlled actor paths; two eight-question batches are exploratory.

## Direct quota-aware speculation experiment

The previous checkpoint was pushed as `2deb6f5` before this experiment.
Read [the quota-prompt report](docs/QUOTA_PROMPT_2026-11-15.md). Opt in with
`--policy current_capacity --speculation-planner quota`; use `blind` for the
same planner without quota context. Actual main-agent prompts remain unchanged.
The final 240-episode / 16-unique-question live pilot completed cleanly across
three regimes, but does not establish a dual-baseline win. Keep Jev as default.
281 tests pass. All attempts cost $1.256674044 in known charges, reconciled;
15 unknown-cost attempts retain a $0.1028643 conservative reservation.
Next unused seeded offset: 306. Raw results, failures and source snapshots remain
under `results/quota-prompt-2026-11-15-*`. A future live confirmation should align
the quota epoch at batch dispatch and control actor randomness; alternatively,
collect exact dynamic quota-planner contexts for a matched-path replay.

## Latest confirmed result

Read [the quota wins report](docs/QUOTA_WINS_2026-11-15.md) first. The locked
80-new-question replication beats both requested baselines on both endpoints;
20 development questions selected 4 workers / 12 calls / 3 seconds, pooled Jev,
full episode-window calibration and an observed-step-4 generation budget.
275 tests pass. Additional campaign spend: $1.439993844, fully reconciled.
The 75-setting map has 13 dual-endpoint wins and retains substantial losses.
Fixed reserve remains competitive. Live A/B performance is still unproven.
Use offset 242 onward for genuinely new seeded questions; retain all prior
failures and invalidated timing runs. Current result/protocol/source snapshots
are immutable evidence. Subsequent work should prioritize a paired live study
and adaptation to quota/refill regimes using development data only.

The sections below preserve the earlier integration checkpoint and its scope.

## What is working

Read [the integration report](docs/MULTI_AGENT_CONTEXT_2026-11-15.md).

- `quota_spec.multi_agent` is the live multi-agent driver. It reuses the pinned
  asynchronous HotpotQA runtime, with actual 2/4/8-agent validation.
- `context_engine.py` supplies observed registry, bounded Jev inputs, single-flight
  TTL caching, asynchronous full/own admission, atomic final quota claims and
  FIFO required Search dispatch. Candidates never block an actor before admission.
- Workers release at answers; all paid background work drains. Optional requests
  reserve actor serving capacity. Unsent drafts expire before HTTP dispatch.
- Provider errors have bounded, independently recorded retries. Unknown charges
  consume a conservative reservation while retaining unknown actual cost.
- Progress, task, history and removed-history/progress context modes are supported.
  Calibration artifacts must match the requested model, context and dev split.
- `live_context_audit.py` independently validates observed Jev state, required
  priority, FIFO/quota inventory and immutable prompt/environment/cost evidence.
- `probability_calibration.py` fits on the original 20 development questions only.
  Reuse calibration improves the separate 30-question Brier score; next-demand
  and continuation calibration regress slightly. Keep calibration explicit.
- `matched_context_study.py` connects the corrected overlap scheduler to a complete
  episode-window forecast bank, retaining real forecast latency/cost.

## Evidence and interpretation

**266 tests pass.** The campaign contains 236 paid live episodes, 1,169 newly
collected bank contexts, and 216 matched same-work replays. The complete episode
bank has 3,054 contexts, all successful. All matched replays preserve answers,
quota and workers with zero predictor fallbacks and networking blocked.

Two earlier live runs failed: 11 episodes after a provider 502 exposed the old
unknown-cost global stop, and one episode after a non-JSON gateway response.
Both defects were fixed; all failed evidence is preserved. The final 16-question,
eight-worker confirmation completed with no actor/optional failures. An injected
non-JSON 502 test also recovers and passes the independent capture/context audit.

At eight agents and 12 calls/5 seconds, matched raw Jev mean completion is
16.173 s own-only versus 13.305 s full, against 13.287 s without speculation.
This supports **cross-agent protection**, not a large win over no speculation.
Calibrated full admission approaches no-speculation latency under binding quota.
The native single-worker nonbinding gain is around 1.2%. Do not replace these
findings with the uncontrolled live timing delta: some apparently faster live
runs have zero cache hits and different authoritative paths/quality.

Retained 150-second actor service dominates some historical batch tails. Mean
question saving and final batch throughput are separate outcomes. Replay holds
service fixed with unlimited provider concurrency; live serving capacity is a
separate measured control.

The campaign account delta is **$0.841052284**, exactly matching all known costs.
Two failed requests retain individually unknown cost; their reservations add
$0.006859600 for a conservative campaign bound of $0.847911884. Final reported
remaining limit is $4.158947716. Do not infer a standing budget from that balance.

Main artifacts:

- `results/multi-agent-context-2026-11-15-report/`: every trial, accounting and hashes.
- `results/multi-agent-context-2026-11-15-repaired-*`: final live source/capture/audits.
- `results/multi-agent-context-2026-11-15-repaired-fast-jev-retry/`: successful final confirmation.
- `results/multi-agent-context-2026-11-15-episode-bank/`: complete forecast bank.
- `results/multi-agent-context-2026-11-15-matched/`: full paired schedules and tuning.
- `results/multi-agent-context-2026-11-15-calibration.json`: dev-fitted maps and scores.

## Useful commands

```sh
make multi-agent-offline COUNT=8 AGENTS=4 OUTPUT=results/context-mock-fresh
make multi-agent-audit EVIDENCE=results/context-mock-fresh
make test
make lint
# Paid, after explicitly loading the private .env:
make multi-agent-live COUNT=16 OFFSET=98 AGENTS=8 MAX_USD=.7 OUTPUT=results/context-live-fresh
```

The direct CLI supports `--calibration`, `--context`, `--draft-actor`, `--width`,
`--optional-slots` and `--model-retries`. The forecast dollar cap partitions the
total budget, rather than adding to it. The detailed report includes commands
for rebuilding the matched study and the campaign report without inference.

## Further research

The next performance bottleneck is candidate precision and timeliness. Faster
nano width-one drafts generate some useful exact calls, but ungated wasted calls
still hurt under quota; Jev gates remain conservative and can be too late.
Try generator improvements and probability/timing calibration on development
questions, then preregister a genuinely fresh stream and quota for confirmation.
The offsets through 97 are now explored. A larger held-out study should compare
full/own Jev with tuned reserves, no speculation and history on identical work,
then validate separately with independently scheduled live agents.

Keep the original baseline available. Do not add artificial Search delays to a
native-performance claim. Kev is deferred. Older research history remains in
[the November 13 handoff](docs/RESEARCH_HISTORY_2026-11-13.md) and dated reports.
