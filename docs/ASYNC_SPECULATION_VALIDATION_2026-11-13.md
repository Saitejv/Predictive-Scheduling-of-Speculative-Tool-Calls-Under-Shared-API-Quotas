# Async speculation validation — November 13, 2026

The agent now keeps prediction windows open until the answer, allowing speculative
Search work to help after intervening actions. It continues generating predictions
and launching Searches while the authoritative actor thinks. Exact requests reuse
completed results or join in-flight work. Previously requested queries suppress
duplicate speculation, and optional inference leaves one of four serving slots
available for the authoritative actor.

The previous next-action implementation already allowed dispatch during the next
actor's generation; its deadline was the actor's returned action, not the end of
the preceding tool latency. The new episode lifetime extends that opportunity
across later actions. `--candidate-lifetime next_action` retains the historical
behavior for reproduction. This distinction is covered by explicit async tests.

## Results in seconds

All rows below use one authoritative agent without a shared Search quota or Jev
gate. Positive savings mean a faster answer.

| Check | Without speculation | With speculation | Saved per question |
| --- | ---: | ---: | ---: |
| Fresh live pilot, 20 questions | 7.011 s | 6.247 s | 0.764 s |
| Same saved paths from that pilot | 6.395 s | 6.193 s | 0.202 s |
| Earlier 50 saved question paths | 8.902 s | 8.664 s | 0.238 s |
| Earlier paths with every Search duration multiplied by five, synthetic | 18.011 s | 16.099 s | 1.912 s |

The live result is exploratory: only 7 of 20 pairs had identical action sequences.
Its paired bootstrap 95% interval for mean saving is **−0.278 to +2.002 seconds**,
which includes zero. Sequential/speculative exact match was 0.25/0.40 and F1 was
0.337/0.487; neither quality nor general speed superiority is established by this
small pass. The fixed-path row isolates scheduling overlap using saved service
durations, prompts, actions, results and answers. It excludes new provider timing
and stochastic path differences. It is not a second live benchmark.

The synthetic row scales required and speculative Search durations equally.
It demonstrates the dependence on tool latency and must not be presented as a
measured production improvement. The original paper's approximately 20% timing
result concerns chess; its HotpotQA figure measures next-action agreement.
See [the original-source comparison](SINGLE_AGENT_BASELINE_REPAIR_2026-11-13.md).

## Background work and recording

| Across the 20 live questions | Without speculation | With speculation |
| --- | ---: | ---: |
| Total time until answers | 140.215 s | 124.939 s |
| Total time including draining started background work | 140.237 s | 136.325 s |
| Mean time including draining | 7.012 s | 6.816 s |

Thus the observed mean answer saving was 0.764 seconds, while mean time saved
including background drain was 0.196 seconds. These are different measurements.
The speculative condition launched 68 prefetches, reused six, and left 62 unused.
The event audit verified **35 prefetch launches during main-actor thinking**.
All started work was drained and billed, including work continuing after answers.

New recordings include start, answer and drain endpoints from one monotonic clock,
actor start/completion spans, candidate lifetime, and successful cache join/reuse
events. Failed prefetch results do not count as successful cache hits. The audit
checks endpoint differences, event counts, state transitions, exact authoritative
prompts, immutable blobs and the request inventory. It rejects corrupted timing
totals and launches after answer readiness. Completed replay banks retain lifetime
metadata; legacy tapes keep legacy expiry unless explicitly overridden.

Both live blocks passed: 40 endpoint checks and 189 authoritative state/prompt
transitions, zero recorded schedule residual, no failed model requests and no
optional failures. All costs are known. Live inference cost **$0.14256645**;
separate bank completion cost **$0.00508721**; total **$0.14765366**, within the
user-authorized $0.50 cap. Bank completion occurred after live timing ended.

## Reproduction and evidence

Evidence is retained locally in `results/async-agent-cleanup-2026-11-13/`:

The committed [validation manifest](ASYNC_SPECULATION_MANIFEST_2026-11-13.json)
contains the measured summary, audit outcome and SHA-256 evidence identities.

- `live-block-1/` and `live-block-2/`: original requests, usage, events, immutable
  capture blobs, task endpoints, prices, model configuration and source snapshots.
- `live-combined-summary.json` and `live-verification.json`: independently
  recalculated paired results, endpoint sums, request routing and full cost ledger.
- `bank-block-1/`, `bank-block-2/`, `pilot-dataset/`: separately completed and
  merged alternatives; no modification of the live inputs.
- `pilot-reference/`, `native-reference/`, `search-5x-reference/`: actual async
  Runtime versus frozen scheduler versus independent scalar calculation. All
  40/100/100 episode checks agree on answer time, drain, cache reuse and prefetch
  count, preserving exact saved prompts, actions and answers.
- `protected-before.json`: hashes of 7,743 earlier evidence files, verified again
  before publication. Earlier paid captures and audits remain unchanged.

Recalculate the live audit without model calls:

```sh
.venv/bin/python scripts/verify_live_speculation.py \
  results/async-agent-cleanup-2026-11-13 \
  --banks bank-block-1 bank-block-2 --budget .50
```

The tests cover dispatch while the main actor thinks, completed reuse, in-flight
joining, retention across Lookup, duplicate suppression, reserved actor capacity,
full post-answer accounting and corrupted recording rejection. Run `make test`,
`make lint` and `make offline OUTPUT=results/smoke-fresh` without paid inference.
Saved-output checks require the local evidence bank and pinned public source.
Raw paid recordings remain Git-ignored and must accompany a research handoff
separately from the code checkout.

Final verification used an exported clean copy of the staged Git tree, with the
pinned public upstream data installed separately: **235 tests passed**, Ruff
lint/format passed for 95 Python files, and the four-episode offline smoke
completed. All 7,743 protected earlier evidence files matched their hashes.
