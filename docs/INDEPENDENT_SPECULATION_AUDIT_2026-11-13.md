# Independent speculation audit — November 13, 2026

**The timing arithmetic checks out, but the earlier performance interpretation needs correction.** Three assumptions materially change the answer: workers waiting for speculation to drain, the limited content/lookahead of recorded predictions, and an asymmetric result cache. The last is especially consequential: the reported **6.32% gain disappears when no speculation can reuse ordinary required results too**. A perfect admission gate over recorded candidates is not a perfect predictor, and neither an eager predictor nor an eager zero-overhead oracle is a globally optimal shared-quota scheduler.

With equal caching and no quota pressure, the requested **perfect next-Search predictor, still paying generation and tool service, saves 1.47% of native answer latency and 23.85% at synthetic 10× Search latency**. The corresponding exact recorded-candidate gate saves 1.20% and 11.43%. Generation delay, lookahead and the shared quota determine which opportunity is available.

All experiments are offline. **No new inference or external tool requests; $0 new model spend.** Jev only; Kev remains deferred. Existing paid evidence was preserved: all 7,239 protected input/result files match their before-run hashes. Unrelated uncommitted work was left intact.

![Cache-matched opportunity versus Search latency](../results/independent-speculation-audit-2026-11-13/figures/noquota-latency.png)

## 1. The cache control changes the largest prior example

The original engine caches speculative Search results for the rest of their episode. It does **not** cache ordinary required results. A speculative result can therefore avoid later repeated Searches even when the no-speculation agent has already obtained the same result earlier. That is a valid comparison of the original runtime behaviors, but it combines speculative overlap with a cache capability the baseline lacks.

The new `cache_required_results=True` control gives **both** strategies the same episode-local exact-query cache. No cross-question cache is introduced. All six repeated authoritative Searches in the 50 paths have identical saved observed text, supporting this control on the fixed paths.

The following numbers use native durations, 30 evaluation questions, three paired orders, **two workers, six Searches per 60 seconds, original candidate lifetime, and release after drain**. Percentages are averages of per-order throughput, compared only within the same cache rule.

| Cache rule | Method | All-work finish, mean seconds | Throughput gain vs its own no-speculation baseline |
|---|---|---:|---:|
| Original: speculative results only | No speculation | 901.639520 | 0.000% |
| Original: speculative results only | Exact perfect Search admission | 848.011377 | +6.324% |
| Original: speculative results only | Exact perfect pipeline admission | 864.937106 | +4.339% |
| Common required + speculative cache | No speculation | 845.766887 | 0.000% |
| Common required + speculative cache | Exact perfect Search admission | 846.230260 | −0.055% |
| Common required + speculative cache | Exact perfect pipeline admission | 845.766887 | **0.000%** |

The matched-cache pipeline optimum selects no speculation. Ordinary caching saves 55.873 batch seconds without predicting anything; it moves demand across a refill boundary. Thus the old 6.32% result is reproducible, but does not isolate a 6.32% benefit from speculative overlap or superior admission.

The other quoted scenario is different: **four workers, 12 Searches/30 seconds**. Its original-cache result reproduces as **215.933327 → 215.026307 seconds**, **0.419481%** mean throughput gain. With common caching, the exact pipeline comparison becomes **214.791949 → 214.172630 seconds**, **0.284470%** gain. These scenarios must not be combined.

![Absolute times and gains under each cache rule](../results/independent-speculation-audit-2026-11-13/figures/cache-control.png)

A comparison of averaged reciprocal times is not the reciprocal of averaged times. For example, the original 6/60 result reduces average elapsed time by **5.947847%**, while improving mean per-order throughput by **6.324314%**. Every raw order, exact selection and both percentage calculations are saved in `arithmetic-audit.json` and `cache-controls/rows.jsonl`.

## 2. Independent timing calculation

Let a source Search dispatch at `d`, with source service `U`, next actor/message time `A`, speculative generation delay `G`, and matching next Search service `T`. Include admission response delay in `G` when there is a gate. In the no-quota, two-Search example:

```text
next required request:       r = d + U + A
speculative result ready:    p = d + G + T
no-speculative result ready:     r + T
joined/reused result ready:      max(r, p)

saving = min(T, max(0, U + A - G))
```

This equation assumes equal service duration for the matching required and speculative call, as in the perfect-predictor experiments. Generation that finishes at or after an original-window deadline cannot launch a useful prefetch there. A completed result saves the whole target tool time; an in-flight join saves only its already-overlapped portion. Generation and tools run concurrently with the main actor; there is no actor-side wait for Jev.

Hand-derived fixtures include the first 0.1-second message and final 0.1-second Finish message:

| Source `U` | Next message `A` | Generation `G` | Next tool `T` | No speculation | Speculation | Explanation |
|---:|---:|---:|---:|---:|---:|---|
| 4 | 3 | 1 | 4 | 11.2 s | 7.2 s | Result completed before demand; save 4 s |
| 1 | 0.5 | 0.2 | 4 | 5.7 s | 4.4 s | Join remaining service; save 1.3 s |
| 1 | 0.5 | 1.5 | 4 | 5.7 s | 5.7 s | Prediction arrives exactly at expiry; no launch |

A hand-derived two-agent fixture with quota **3/10 seconds** starts both source Searches at 0.1 s, each with service 2 s; the next messages take 2 s and the next Searches take 2 s. Only agent A has a one-second prediction. Without speculation, A answers at **6.2 s**, B at **12.1 s**. With speculation, A answers at **4.2 s**, B still at **12.1 s**. Mean answer latency improves by one second, while batch answer time and throughput do not improve. The queued Search dispatches exactly at the 10-second refill.

Checks cover completed reuse, in-flight joining, case-sensitive keys, expiry at equal timestamps, required FIFO dispatch, reset revalidation, no quota refunds, worker release and outstanding work. A separate two-agent regression verifies that a correct prefetch can harm another agent; the global gate rejects it.

The independent scalar perfect-predictor recurrence matches **all 800 distinct question/duration/oracle combinations exactly**; the study executes these in two retention branches, recording 1,600 checks. The existing serial recorded-candidate recurrence matches all 100 native task/mode checks exactly. The new recurrence uses no event heap, quota implementation or policy code. Another test checks 200 randomized message/tool chains against it.

## 3. What A–G mean here

| Label | Capability and charged work |
|---|---|
| A | No speculative generation or Searches; fixed authoritative messages, actions and tool outputs |
| B | Recorded ranked predictions, admitted whenever quota permits; full naturally started generation and speculative tool costs |
| C | Recorded predictions with a reserve and generation screen; retuned on the 20 development questions for each duration/quota/worker/release/retention setting |
| D | Recorded predictions admitted by saved Jev own-agent or all-agent forecasts; nonblocking admission, measured response delay, current-quota revalidation |
| E Search | Offline admission over recorded candidates; all naturally started generation retained |
| E pipeline | Offline admission over recorded candidates plus clairvoyant suppression of source windows with no selected candidate; selected windows still pay recorded generation |
| F | Synthetic perfect **next required Search** query, paying saved source generation and the matching required tool duration; generates on authoritative cache reuse; retains candidates through the episode; suppresses already known queries |
| G | Same one-next-Search architecture as F, with **zero generation delay**; tool service and shared quota still charged |

Primary F charts charge terminal generation that correctly discovers there are no further Searches. A separately labeled `F_perfect_predictor` variant can screen out those empty windows before generation. That stronger source-screening oracle must not be attributed to candidate accuracy alone. Generation after speculative dispatch is never recursive; F/G first react to the first authoritative Search. Lookups remain local and serial.

**Exactness:** all native, original-window global E cases enumerate every one of the **512 useful subsets**, separately for both pipeline architectures and release rules. Across 120 paired settings this is 122,880 enumerated schedules, plus winner verification. Every duration also receives exact per-task no-quota gate optimization, including longer-retention/common-cache controls.

The synthetic-duration global candidate pool grows to 20–27 useful bits. Those large global gates, and the main extended-lifetime global gates, are explicitly **feasible best-found** schedules from multiple starts and forward/reverse subset changes. They are **not exact perfect global optima or global ceilings**. The exact no-quota values below do not have that approximation. The archived earlier extended exact studies remain unchanged. No conclusion relies on calling a local search an exact oracle.

### Why a recorded gate can sometimes beat F

F predicts one next Search, whereas a recorded top-three window can contain several correct later Searches. These policy classes are not nested. On question **6031**, source step 2 contains both `Ohio Turnpike length` and the later `Ohio Turnpike`. E can dispatch both at 3.826 s. F predicts only the next query, then cannot finish generating the later query in time. The original-cache no-quota path finishes at **7.016 s under E versus 7.992 s under F**. Other saved counterexamples include a late next-Search prediction versus an on-time farther-ahead prediction. Event traces are retained in `non-nested-oracle-*.json`.

An **extra full-lookahead oracle** reveals all distinct later Searches at one saved source generation duration. This is a stronger, optimistic architecture, rather than a claim about a real predictor. With common caching it reaches **9.633 s at native timings** and **17.586 s at synthetic 10×**, compared with the F values below. Its zero-generation counterpart reaches **9.005 s** and **16.569 s**. Full lookahead is therefore another substantial axis of opportunity; perfect next-query accuracy alone does not supply it.

G is an upper reference for F in the **no-quota, stated one-next-Search architecture**. Under a shared quota, an eager G policy is not an optimized upper bound. A saved synthetic 5×, 6/60 s, four-worker, seed-249 case finishes at **848.245 s for F and 908.245 s for G**. Earlier dispatch changes both quota ordering and which repeated queries acquire speculative cache entries: F makes 89 Searches, G 91, crossing one additional reset. Both have zero unused speculative calls. With common caching, both make 88 Searches and that particular reversal disappears. The full traces and common-cache follow-up are saved; this is a quota/cache interaction, not negative tool latency or an omitted join. A truly optimized zero-overhead controller with optional delayed dispatch could emulate F, but that stronger controller is not the eager G curve.

## 4. Controlled tool-latency sweep

All-50 validation uses the canonical saved speculative-mode actor paths; multi-agent policy evaluation uses the disjoint **30 evaluation paths**, with 20 development paths for tuning. Each synthetic change affects **both required and speculative Searches**. Main-agent messages, Lookups, Finish actions and generation durations remain fixed. The 150.150-second actor outlier is retained.

The table below uses **common caching, verified nonbinding 10,000 Searches/1 s, evaluation30, and per-question answer latency**. Every reduction uses that row's no-speculation baseline. E is exact over recorded candidates with original lifetime. F/G use the explicitly broader reuse-trigger/retention architecture above. Each cell gives absolute mean seconds / latency reduction; these are not throughput percentages.

| Search duration | A mean s | E recorded gate: s / reduction | F perfect next Search: s / reduction | G zero generation: s / reduction |
|---|---:|---:|---:|---:|
| native | 10.446 | 10.321 / 1.20% | 10.293 / 1.47% | 9.117 / 12.73% |
| scale2 | 12.499 | 12.043 / 3.65% | 11.755 / 5.95% | 10.230 / 18.15% |
| scale5 | 18.657 | 17.129 / 8.19% | 15.644 / 16.15% | 13.959 / 25.18% |
| scale10 | 28.921 | 25.616 / 11.43% | 22.025 / 23.85% | 20.320 / 29.74% |
| fixed1 | 11.327 | 11.097 / 2.03% | 11.043 / 2.50% | 9.564 / 15.56% |
| fixed2 | 14.260 | 13.428 / 5.83% | 12.870 / 9.75% | 11.283 / 20.88% |
| fixed5 | 23.060 | 20.428 / 11.41% | 18.170 / 21.21% | 16.553 / 28.22% |
| fixed10 | 37.727 | 32.095 / 14.93% | 27.003 / 28.42% | 25.387 / 32.71% |

`native` retains recorded service times. Every `scale*` and `fixed*` row is **synthetic**; `fixed5`, for example, gives every required and speculative Search five seconds. Longer recorded-candidate retention raises the common-cache native E opportunity to **10.294 s / 1.46%**, almost F's 1.47%. At 2×/5×/10×, extending retention no longer improves those common-cache E means.

This explains the native result: a correct prediction still often takes too long to arrive. As `U` increases, the source tool provides more time for generation; as `T` increases, an on-time prefetch can hide more service. Increasing both consistently exposes the larger F advantage. Recorded candidates still miss queries and sometimes predict too late. Removing prediction overhead creates a substantially different result, especially natively.

## 5. Worker release, shared quota and throughput

Three distinct metrics are retained:

- **Answer latency:** answer time minus that question's worker-acceptance time.
- **Answer makespan:** time from workload start until every answer is available.
- **Resource makespan:** time until every started tool/generation/forecast operation has finished; used for all-work throughput.

A main-agent worker can accept another question at its answer while its background operations continue. The background calls retain their spent quota and service cost. No new optional Search is started for an already answered question. Worker count limits main-agent slots; model/tool serving concurrency is otherwise unlimited, apart from the one persistent shared Search quota.

A hand-derived drain fixture has a 20-second unused speculative Search. With one worker and quota 2/10 s, releasing at answer starts the next question at **11.1 s**, yields all answers at **12.3 s**, and finishes all work at **20.3 s**. Releasing after drain starts the next question at **20.3 s** and finishes at **21.5 s**. Both runs consume exactly the same four Search tokens. The outstanding work is neither discarded nor charged twice.

With original-cache native timings and one nonbinding worker, B changes from **−1.676% throughput under drain release to +1.273% under answer release**. The 30-question answer makespan changes from 321.343 to 311.973 s; all-work makespan changes from 321.698 to 312.328 s. Thus drain-before-next-question is a real restrictive throughput assumption. With common caching, answer-release F achieves **+1.374%**, while drain-release F is **−2.121%**. Terminal generation is fully charged in both.

![Worker-release rules and all outstanding work](../results/independent-speculation-audit-2026-11-13/figures/worker-release.png)

Earlier release is not guaranteed to improve a finite binding-quota batch: it changes dispatch phase and worker assignment. The old 6/60 Search-gate gain itself shrinks from 6.324% to 4.317% when workers release at answer, even before equalizing caches. Treat release architecture as an experimental setting, not a percentage adjustment.

The main sweep covers **1/2/4/8 workers**, quotas **10,000/1 s, 12/5 s, 3/10 s, 12/30 s and 6/60 s**, all eight duration settings, both release rules, original lifetime versus one extra action with historical duplicate suppression, and three orders. There are **19,200 policy executions** including the full-generation F supplement. Every nonbinding run is verified to have zero required quota wait; its capacity exceeds even the workload's total possible dispatches. Required and optional work share the same quota across the entire workload, with no per-question resets.

![Legacy-cache shared-quota sweep: absolute time and throughput](../results/independent-speculation-audit-2026-11-13/figures/shared-quota-latency.png)

That broad chart deliberately retains the original cache protocol for comparability; it is not an isolation of overlap alone. Native matched-cache, **answer-release** controls give a more direct interpretation:

| Quota / workers | A all-work s | Exact E pipeline s / throughput gain | Jev all-agent s / gain |
|---|---:|---:|---:|
| Nonbinding / 1 | 313.386 | 309.637 / +1.210% | 312.286 / +0.352% |
| 12/30 s / 4 | 214.792 | 214.173 / +0.284% | 215.223 / −0.201% |
| 6/60 s / 2 | 845.767 | 845.767 / 0.000% | 846.392 / −0.074% |

Historical duplicate suppression is another explicit restriction: it excludes any query ever requested, including ordinary results that the legacy cache does not retain. Retention and suppression are therefore disentangled in additional exact no-quota controls. At synthetic 2×, original lifetime/no suppression gives 12.156 s; extra lifetime alone gives **12.142 s**; the bundled extra-lifetime/historical-suppression rule gives **12.199 s**. The latter is not evidence that retention alone hurts. Under common caching, already requested results are actually reusable and this historical-suppression distinction disappears. All factorial values are in the numerical appendix.

## 6. Finite tails versus repeated throughput

The repeated diagnostic runs **30 and 300 episode instances**, with fresh task IDs/caches but the same mixture of frozen paths. One quota persists throughout each stream. Both worker-release rules and 1/2/4/8 workers are tested at nonbinding, 12/30 s and 6/60 s, for native and synthetic 10× durations. These are repeated traces, not fresh questions or independent live trials. Cloned task IDs also change the deterministic Monte Carlo draws for Jev; comparisons are paired within each diagnostic, rather than mixed with the original-ID sweep.

![Finite batches versus repeated streams](../results/independent-speculation-audit-2026-11-13/figures/finite-tail.png)

With **four workers, nonbinding quota, answer release, original cache rule**, full-generation F improves all-work throughput by **0.408% for native 30 tasks versus 1.460% for 300**. At synthetic 10×, it improves **21.606% versus 34.038%**. A single long actor call dominates the small batch's critical tail; repeating the mixture makes sustained overlap more visible.

Under **12/30 s**, the same native F comparison is **−0.044% for 30 versus +0.164% for 300**. At synthetic 10×, it is **+7.823% versus +6.553%**. Under **6/60 s and two workers**, synthetic 10× F drops from **+5.378% to +1.892%** as the stream grows. Quota-limited throughput does not inherit the full no-quota latency benefit. Interior 10%–90% completion-interval rates are also retained to reduce startup/tail influence; they do not establish asymptotic stationarity.

These repeated-stream results retain the original cache rule. They must not be used to reinstate the cache-confounded native 6.32% claim. Common-cache repeated-stream optima were not exhaustively solved.

## 7. Does current Jev capture the opportunity?

**Only partly, and not consistently enough to beat no speculation or a cheap reserve across the shared-quota regimes.** It can preserve quota relative to ungated speculation, and can benefit from the less restrictive answer-release architecture. The common-cache native controls above show a small nonbinding gain and no useful broad quota throughput advantage. The 6/60 common-cache case has zero exact pipeline opportunity to capture under these controls, so the old 6.32% gap should not be blamed on Jev.

Where actual overlap opportunity grows, the saved gate still leaves substantial value unrealized. In the original-cache synthetic 10×, 12/30 s, four-worker, answer-release case, no speculation uses **245.391 s**, Jev all-agent **306.408 s (−19.923%)**, while F uses **227.673 s (+7.823%)**. Jev dispatches 35.667 speculative Searches on average, 29 unused; the exact native/best-found synthetic E admission references avoid unused Searches. In the 300-instance version Jev remains **−18.471%**, so the loss is not just one finite tail. The development-tuned reserve chooses no speculation in this setting and avoids that loss. These are original-cache comparisons with their own matched baseline, not the common-cache numbers above.

All Jev probabilities and measured forecast response durations remain **frozen from native observations, at phase-entry elapsed=0**. Its development history delay/tool distributions are recomputed under each synthetic transform; Jev is not re-queried or recalibrated for slower tools. Its forecasts cover currently active agents, not a new-task arrival model. Thus these experiments assess the saved Jev gate under duration changes, not what a newly trained or freshly queried predictor could achieve. Logical replayed inference cost is recorded separately from actual new spend, which is zero.

## 8. Changes, verification and limits

No missing in-flight overlap, completion reuse, quota refund or reset arithmetic defect was found in the audited scheduler cases. The corrections are to **experimental controls and interpretation**: a matched required-result cache, release-at-answer comparisons, explicitly charged terminal generation, generation on cache reuse, and distinct candidate-accuracy/lookahead/admission references.

`FrozenReplay` adds opt-in `generate_on_reuse` and `cache_required_results`; both default to false, preserving the old protocol. A shared generation helper preserves ordinary dispatch behavior. `exact_gates` now forwards worker-release, fixed-tool-time and cache/trigger controls. No existing paid recording is rewritten.

Verification:

- **216 tests pass**; Ruff check and formatting pass for all 91 Python files.
- Thirteen new tests cover hand timelines, exact expiry, reset dispatch, retained background work/quota, common caching, duration transforms, predictor invention versus gate limitations, reuse generation, terminal generation, lookahead, percentages and independent randomized recurrences.
- **384 complete schedules** match the pre-audit replay implementation exactly in metrics, events and decisions across native/10× durations, workers, quota settings, release rules and lifetime controls when new options are disabled.
- A tape-only rollout cache compaction omits completed other episodes, whose task-scoped entries cannot affect active continuations. Eight native/synthetic, quota/worker comparisons match full policy results exactly, excluding only diagnostic CPU wall time. Declared scheduler overhead remains 1 ms; no simulated operation becomes faster from this optimization.
- All **7,239 protected evidence files** remain byte-identical; six repeated Search observations match exactly. Evidence before/after manifests and source snapshots are retained.

Exact global optimality for the large synthetic candidate pools remains a computational limit, explicitly marked in every E row. Fixed-path replay also assumes unlimited provider serving concurrency beyond Search quota, ignores original collection submission queues consistently, retains measured actor outliers, and does not measure changed answer quality or live provider contention. The 20/30 split is an already explored cohort, not a fresh confirmation sample.

The concrete conclusion is conditional: **slow tools make correct, timely prefetching more valuable; a saturated shared quota makes wasted prefetches more costly; equal caching removes the strongest earlier native reset example; and useful predictor accuracy, generation speed, lookahead and admission quality are separate requirements.**

## Evidence and reproduction

- `docs/INDEPENDENT_AUDIT_MANIFEST_2026-11-13.json`: source/result inventory and checksummed standalone audit bundle.
- [Full numerical tables](INDEPENDENT_LATENCY_TABLES_2026-11-13.md): every requested duration, release rule, worker count, own/all Jev comparison, exactness label and control.
- `results/independent-speculation-audit-2026-11-13/`: raw rows, exact per-task calculations, selected gate schedules, event traces, figures, protected evidence hashes and validation logs.
- `full-generation-predictor/combined-summary.csv`: all 6,400 main aggregate policy rows, with absolute times, seconds saved, latency reductions and answer/resource throughput gains.
- `cache-controls/`: 216 exact native batch-control policy rows and 800 per-task cache-control rows; `common-cache-oracles/` and `common-cache-retention/` add cache-matched upper references and retention controls.
- `repeated-stream.json` plus `full-generation-predictor/repeated-stream.json`: 1,728 completed stream policy rows. A redundant compact-stream rerun was stopped after the original stream completed; its partial log is preserved and is not used in results.

Use fresh output paths; commands make no paid calls:

```sh
AUDIT_ROOT=results/independent-audit-rerun
mkdir "$AUDIT_ROOT"
.venv/bin/python -m quota_spec.latency_study --output "$AUDIT_ROOT/latency-sweep"
.venv/bin/python scripts/audit_latency_study.py --output "$AUDIT_ROOT" --streams
.venv/bin/python scripts/full_generation_predictor.py "$AUDIT_ROOT"
.venv/bin/python scripts/full_generation_predictor.py "$AUDIT_ROOT" --combine
.venv/bin/python scripts/predictor_gate_sensitivity.py --output "$AUDIT_ROOT/predictor-gates"
.venv/bin/python scripts/oracle_architecture_sensitivity.py --output "$AUDIT_ROOT/oracle-architecture"
.venv/bin/python scripts/oracle_architecture_sensitivity.py --output "$AUDIT_ROOT/oracle-lookahead" --lookahead-bound
.venv/bin/python scripts/oracle_architecture_sensitivity.py --output "$AUDIT_ROOT/retention-controls" --retention-controls
.venv/bin/python scripts/oracle_architecture_sensitivity.py --output "$AUDIT_ROOT/common-cache-retention" --retention-controls --common-cache
.venv/bin/python scripts/cache_semantics_sensitivity.py --output "$AUDIT_ROOT/cache-controls"
.venv/bin/python scripts/cache_semantics_sensitivity.py --output "$AUDIT_ROOT/common-cache-oracles" --extra-oracles
.venv/bin/python scripts/report_latency_study.py "$AUDIT_ROOT"
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
```

`verify_latency_audit.py` additionally verifies this audit's original source snapshot and protected-before manifest. Those provenance files are created before edits and retained in this result bundle; they are not synthesized from post-edit sources during reproduction.
