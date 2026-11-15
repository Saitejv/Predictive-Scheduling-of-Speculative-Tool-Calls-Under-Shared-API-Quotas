# Current handoff

Updated November 15, 2026. The current user direction authorizes API spending
for making the multi-agent Jev context-engine idea work. It supersedes the older
single-agent-only priority and earlier $0.50 testing-turn limits. Keep individual
experiments explicitly bounded, retain all attempts and preserve existing paid
evidence. Do not commit or publish without a request.

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
