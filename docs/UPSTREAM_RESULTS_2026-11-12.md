# Direct upstream replication check, November 12, 2026

**The authors' HotpotQA runner reproduces the qualitative agreement result:
three candidates outperform one, with point estimates close to Figure 4.
This experiment does not establish a live throughput gain.**

We cloned [the authors' repository](https://github.com/naimengye/speculative-action)
at `dc938b9ef7474caf07fe4ad16549c1fa8c7d268c` into
`tmp/speculative-action-upstream/`. The checkout remains pristine. Unlike the
existing collection/replay pipeline, this cross-check invokes the actual
`HotPotQARun.webthink` implementation directly, with an instrumented OpenRouter
transport and explicit in-memory state fixes. No Jev calls, forecast banks,
shared quotas, trace normalization or scheduling replay were involved.

## Independent paid result

Gemini 2.5 Flash served as both the actor and observation speculator, through
Google AI Studio on OpenRouter. The original prompts, six examples, action
parser, Wikipedia tools, 1,000-token actor cap, 100-token observation cap,
temperatures, top-p settings, width three and seven action iterations were
preserved. We used the intended first 20 seed-248 question indices and verified
that every actual question index matched. The historical paper sample cannot
be recovered exactly from its released logs.

| Measure | Paper Figure 4, Gemini | Direct upstream run |
| --- | ---: | ---: |
| Top-one next-action agreement | 19.58% | 21.17% ± 8.04 pp |
| Top-three next-action agreement | 38.33% | 36.50% ± 8.61 pp |

Uncertainty is one standard error across 20 questions, using the authors'
per-question averaging convention. Both prefixes come from each question's
same width-three candidate lists, excluding the initial action. The original
scorer and an independent strict-prefix scorer agree exactly for this run.
There were no lists exceeding width three on the 70 scored actions. Six scored
lists contained fewer than three candidates. The paper's scorer lowercases the
full action; our comparison preserves that convention.

These estimates support behavioral agreement reproduction, not statistical
equivalence or an exact historical rerun. The earlier collector-based Gemini
run reached 24.17% top-one and 38.33% top-three on the same intended question
indices; this independent stochastic run gives a second, similar result.

All 20 questions completed with 248 inference requests and zero inference
failures. Authoritative answer EM was 35%, and F1 was 45.36%; the paper does not
publish a corresponding HotpotQA answer-quality target. Billed baseline cost
was **$0.11568040**, with no unknown request costs.

## Why this does not solve throughput by itself

[Section 3.3 and Appendix B.2](https://arxiv.org/html/2510.04371v2#S3.SS3)
report HotpotQA action agreement. The approximately 20% end-to-end speedup is
reported for chess. The released HotpotQA `webthink` loop executes its normal
and hypothetical branches serially and does not implement the concurrent
prefetch/cache runtime needed to measure that effect on this workload.

In this new run, the median real Wikipedia Search took **0.658 s**, while the
median observation prediction took **1.092 s**. A further speculative actor
call is needed before a next action is available; median actor-request latency
was **0.924 s**. These are serial component measurements, not a live paired
comparison. They indicate limited overlap opportunity with current Wikipedia
latency and explain why substantial agreement need not translate into useful
prefetching. Observation output hit the original 100-token cap on 65 of 68
requests, another limitation retained for fidelity.

## Upstream defects and compatibility

The uncorrected wrapper discards requested task indices. A network-blocked
diagnostic requested 7107/5619 but actually evaluated 6619/2198. The corrected
run forwards indices. Speculative observations also overwrite real page and
lookup state unless isolated. The corrected run evaluates hypothetical tools
from pre-tool state and restores real state afterward. These are explicit
deviations from defective upstream behavior; source files remain unchanged.

The earlier GPT-5 nano observation failed with no visible output at 100 tokens.
A separate one-request compatibility probe with the original observation
prompt, a 512-token cap and minimal reasoning returned HTTP 200, 2,377 visible
characters and zero reasoning tokens. It still hit its output cap. This cost
**$0.00020770**. It demonstrates a usable observation response under changed
settings, not a completed GPT-5 nano trajectory or a Figure 4 replication.

## Decision and next gate

Using the upstream implementation is feasible for the agreement baseline, and
the current canonical collector was already using its runner components. A
wholesale replacement of the project is not necessary to obtain this behavior.
The full local checkout and direct harness now provide a reference for any
future fork.

Before adding Jev, implement and measure the no-quota concurrent HotpotQA
runtime: run real tools alongside observation prediction, launch speculative
next calls as soon as candidates exist, and reuse only exact matching calls
while preserving authoritative state. Compare against sequential execution
with equivalent workload/model settings, counting all inference and unused
branches. If realistic tool latency leaves too little overlap, report that
result; any controlled latency sweep must be labeled as a systems experiment
rather than a published HotpotQA speedup. Shared quotas and cross-agent Jev
admission follow this baseline.

## Evidence and validation

- [Runner and exact reproduction commands](UPSTREAM_BASELINE.md)
- [New harness](../scripts/run_upstream_baseline.py)
- [Machine-readable summary](../results/upstream-direct-gemini-20/summary.json)
- [Timing and provenance audit](../results/upstream-direct-gemini-20/analysis.json)
- [Full paid requests/responses](../results/upstream-direct-gemini-20/requests.jsonl)
- [Individual authoritative and speculative trajectories](../results/upstream-direct-gemini-20/tasks/)
- [Exact paid harness snapshot](../results/upstream-direct-gemini-20/source/run_upstream_baseline.py)
- [GPT-5 nano compatibility probe](../results/upstream-gpt5nano-compatibility/summary.json)
- [Settled account and spending audit](../results/upstream-direct-gemini-20/account-final.json)
- [145-test validation log](../results/upstream-direct-gemini-20/tests-145.log)

The full suite passed 145 tests with no skips in the configured environment.
Additional checks run the original/corrected runner with sockets blocked,
verify that budget denials never send a request, and retain/stop on unknown
costs. Strict agreement was regenerated from frozen task files with sockets
blocked; all upstream source hashes and the paid harness hash match the saved
configuration. Ruff and whitespace checks pass. Existing user changes and
credentials were preserved.

New spending was **$0.11588810** including the compatibility probe. Combined
with earlier recorded pilot/reproduction spending, the total is **$0.469644574**,
below the previously recorded $0.50 ceiling. No further paid work was started.
Settled account usage increased by exactly the new request costs; remaining
OpenRouter credit is $4.476756405.
