Independent review completed November 12, 2026. **No full-versus-owner-only replay improvement was observed, and the pilot did not exercise their admission objectives.** All 19 held-out Search proposals arrived after authoritative readiness: 0.009–1.101 seconds late (median 0.507 seconds). Every Jev decision event was ineligible (456 across settings/seeds); no optional Search dispatched. This is an opportunity/timing result, not evidence that cross-agent and owner-only objectives are equivalent.

Local verification reproduced the original **124 passing tests with zero skips**, including upstream integration. Six new regressions bring the final count to **130 passing tests, zero skips**. Editable installation, public-source preparation, Ruff and `git diff --check` passed. The requested eight-task/five-context mock study completed with socket connect/connect_ex blocked: 432 aggregate rows, four held-out tasks, actual peak four, null EM/F1, zero fallbacks. Both paid studies were subsequently reproduced byte-for-byte for runs, comparisons, metric comparisons and calibration with sockets and model calls blocked; replay added no requests.

Correctness fixes made in this review:

- Preserve reported billing before validating chat choices or Jev answers, so a malformed paid response retains its known cost.
- Stop canonical collection on exhausted action generation instead of allowing upstream to skip a numbered iteration and misalign timings/branches. Preserve partial authoritative/hypothetical trajectories and measured timing on failure. Individual parser retries remain inside their measured generation call.
- Measure the whole tool operation, including failed HTTP timeout attempts; upstream previously retained only the successful final attempt. Record the actual environment reset index for verification.

The new regressions cover those failures, quota-wait-shifted proposal release, and prompt-level separation of hypothetical observations from the authoritative actor. Existing checks cover stateful uncached Lookup, quota-free Finish, exact byte-sensitive reuse, cancellation without refunds, atomic dispatch, late/tied required priority, pending-owner information boundaries, development-only training and checkpoint/source integrity. No broad redesign was made.

Paid settings were unchanged between the four-question smoke and the seeded 20-question pilot: pinned upstream commit `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c`, seed-248 question order, original six-shot ReAct/Wikipedia tools, width one, seven action iterations. Actor and speculative actor: `google/gemini-2.5-flash`, 1,000 output tokens, temperature 1, top-p 1. Observation model: the same model, 100 tokens, temperature 0.1, top-p 0.9. Google AI Studio served Gemini. Jev requested `typesafe/jev-1.14` at OpenRouter Decisions, returned `typesafe/jev-1.14-20261014`, provider TypeSafe; progress context and five-second timeout. Seeds 7/17, four scenarios, at most four forecast calls, base quota 3/10 s, risk threshold 0.05, no plots. Request caps: smoke 128 collection/200 forecasts; pilot 448/500, allowing the seven-step workload plus bounded retries. A separate per-request dollar guard covered both runs together, reserved headroom, and would stop on unknown cost; it did not change prompts or model parameters.

The smoke collected four tasks (2 development/2 held out), 52 Gemini plus 45 Jev requests, costing $0.025201634. Actual replay peak was two even when four/eight were requested. At its base setting all FIFO admission policies had mean 12.474 s, p95 13.812 s, mean/p95 Search wait 2.404/6.391 s, 100% deadline completion, no optional calls/reuse/charged scheduler overhead. One proposal was intrinsically on time but none were eligible at base quota. Held-out EM/F1: 50%/50%; all-four EM/F1: 50%/62.5%.

The primary pilot collected **20 tasks, split 10 development/10 held out**, with 260 Gemini and 186 Jev requests ($0.116439250). There were no inference/collection/forecast failures, aborts or unknown response costs. Six episodes required forced empty Finish after the action limit, including three held-out episodes; incorrect and exhausted episodes remain in QA scores.

Base comparison: requested and actual peak four, burst arrivals, quota 3/10 s. Values average the two seed aggregates:

| Policy | Mean completion (s) | p95 completion (s) | Mean/p95 Search wait (s) | Deadline completion |
| --- | ---: | ---: | ---: | ---: |
| Jev progress full | 25.862 | 51.803 | 5.021 / 16.996 | 80% |
| Jev progress owner-only | 25.862 | 51.803 | 5.021 / 16.996 | 80% |
| No speculation; current capacity; reserve; usage; history full/own | 25.862 | 51.803 | 5.021 / 16.996 | 80% |

The full-minus-own mean/p95/wait deltas and paired seed intervals are all exactly zero. These degenerate two-seed intervals do not estimate general HotpotQA uncertainty. Every FIFO admission policy also has zero speculative/unused calls and prediction fallbacks, zero charged decision overhead, and 36 charged Search dispatches per seed. One exact reuse per seed comes from a repeated **required** Search on task 2038; it is not speculative reuse. Forecast banks were paid/frozen but were never consulted by eligible held-out decisions. Development produced no eligible calibration decisions either: tuning selected the tied minimum horizon (10 s), reserve zero and the 1 ms scheduler-cost floor, rather than a measured decision p95.

Actual concurrency and completion with Jev full (owner-only and FIFO admission controls identical):

| Requested / actual replay peak | Batch sizes | Mean completion (s) | p95 completion (s) | Mean Search wait (s) | Deadline completion |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 / 1 | 1 × 10 | 8.925 | 20.756 | 0.444 | 100% |
| 2 / 2 | 2 × 5 | 15.699 | 31.762 | 2.274 | 100% |
| 4 / 4 | 4, 4, 2 | 25.862 | 51.803 | 5.021 | 80% |
| 8 / 8 | 8, 2 | 47.517 | 90.756 | 10.874 | 45% |

Paid collection/model requests were serial, with measured peak request concurrency **one**. The table describes replay load, not live multi-agent scaling. Deadlines are synthetic arrival + four quota windows (40 s at base), not measured application SLAs.

Per-agent base outcomes (seconds, averaged over the two seeds):

| Task | Full completion | Full quota wait | Full-minus-own completion |
| --- | ---: | ---: | ---: |
| 1354 | 21.037 | 15.241 | 0.000 |
| 1477 | 16.790 | 12.330 | 0.000 |
| 2038 | 43.336 | 32.401 | 0.000 |
| 2527 | 51.803 | 38.240 | 0.000 |
| 2861 | 11.151 | 8.400 | 0.000 |
| 2885 | 17.282 | 11.515 | 0.000 |
| 3021 | 11.197 | 7.517 | 0.000 |
| 4349 | 26.588 | 16.708 | 0.000 |
| 4948 | 12.849 | 8.767 | 0.000 |
| 7090 | 46.582 | 34.663 | 0.000 |

Pilot held-out **EM 30%, F1 47.38%**; development 40%/51.67%; all 20 35%/49.52%. These fixed-trajectory QA scores are shared by replay policies. Next-action agreement is separate: held-out case-folded top-one agreement was 9/36 scored actions (25% micro; 40% mean across tasks), excluding each initial action as upstream does. Strict quota identity produced four matching Search candidates out of 19 Search proposals; none was on time. No top-three/46% paper-headline comparison is made.

Gemini actor/speculative actor responses all ended normally. Observation responses hit the unchanged 100-token cap on 72/74 pilot calls (11/12 smoke calls); their usable partial text was retained. This substantial truncation limits speculation quality. Pilot median/p95 request latencies: actor 0.956/1.538 s, speculative actor 0.948/1.646 s, observation model 1.191/1.547 s, Jev 0.260/0.526 s. Real generation costs are reported separately from replay scheduler overhead, which was zero because no eligible decisions ran.

**Total additional spending: $0.141640884**, exactly matching the settled account-usage increase. There were 543 actual requests (312 Gemini, 231 Jev), no additional paid probes and no replay charges. Account usage rose from $0.053599021 to $0.195239905; remaining credit is **$4.804760095**. The $0.50 turn allowance has $0.358359116 unspent. Role totals: actor $0.058422730; speculative actor $0.055250220; observation prediction $0.022198100; Jev $0.005769834.

Remaining limitations: no eligible held-out interventions, only ten held-out questions and two task-order seeds, route/time-dependent model and Wikipedia measurements, heavily capped observation predictions, phase-entry frozen forecasts, finite scenarios/horizon, artificial deadlines and uninformative development tuning. The bounded controller is approximate. Independent live ReAct/gateway execution fidelity is still unimplemented. Collection wall time is not a speculative speedup. No further paid work or model sweep is justified by this pilot alone.

Preserved evidence:

- [Paid 20-task report/configuration/traces](../results/paper-independent-paid-20/REPORT.md), [normalized evaluation traces](../results/paper-independent-paid-20/traces/evaluation.json), [frozen study configuration](../results/paper-independent-paid-20/study/frozen_config.json), [events](../results/paper-independent-paid-20/study/events.jsonl), [per-agent outcomes](../results/paper-independent-paid-20/study/outcomes.jsonl), [paired comparisons](../results/paper-independent-paid-20/study/metric_comparisons.json).
- [Independent audit JSON](../results/paper-independent-audit/paper-independent-paid-20-audit.json), [proposal lead times](../results/paper-independent-audit/heldout-proposal-lead-times.json), [smoke audit](../results/paper-independent-audit/paper-independent-paid-smoke-audit.json).
- [Paid request/response ledger](../results/paper-independent-audit/paid-requests.jsonl), [final account snapshot](../results/paper-independent-audit/account-after-final.json), [budget guard](../results/paper-independent-audit/run_bounded.py), [smoke log](../results/paper-independent-audit/paid-smoke.log), [20-task log](../results/paper-independent-audit/paid-20.log).
- [Final tests](../results/paper-independent-audit/tests-final.log), [original 124-test run](../results/paper-independent-audit/tests-original-124.log), [socket-blocked mock log](../results/paper-independent-audit/offline-fixed.log), [smoke reproduction](../results/paper-independent-audit/smoke-replay-check.log), [20-task reproduction](../results/paper-independent-audit/20-replay-check.log).

Pre-existing changes, credentials, raw evidence and saved hashes were preserved. Artifact credential scanning passed. No commits, publication, new chats or sub-agents were used.
