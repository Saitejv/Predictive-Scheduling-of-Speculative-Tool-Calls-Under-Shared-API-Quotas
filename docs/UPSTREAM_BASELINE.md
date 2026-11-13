# Running the authors' code directly

See the [November 12 direct-run results](UPSTREAM_RESULTS_2026-11-12.md): 20
questions completed, with 21.17% top-one and 36.50% top-three agreement.

Use `scripts/run_upstream_baseline.py` to cross-check the existing canonical
collector against the original `HotPotQARun.webthink` implementation in a full
Git checkout. The script does not use our collector, trace normalization,
forecast banks, replay, quota controller, or Jev. It imports the authors' runner,
environment, wrappers, prompts, dataset, action parser and scorer directly.

The upstream source remains unchanged on disk. A replacement OpenRouter
transport loads credentials from the environment, retains request/response
evidence without authorization headers, checks costs before another request,
and stops on inference failures instead of silently skipping iterations.

```sh
git clone https://github.com/naimengye/speculative-action.git tmp/speculative-action-upstream
git -C tmp/speculative-action-upstream checkout dc938b9ef7474caf07fe4ad16549c1fa8c7d268c
.venv/bin/python -m pip install -e '.[paper,dev]'

# Diagnostic: preserves the upstream task-selection/state defects.
.venv/bin/python scripts/run_upstream_baseline.py \
  --backend mock --count 2 --output results/upstream-original-smoke

# Corrected: same upstream webthink loop, explicit in-memory state fixes.
.venv/bin/python scripts/run_upstream_baseline.py \
  --backend mock --count 2 --state-fixes --output results/upstream-fixed-smoke

set -a
source .env
set +a
.venv/bin/python scripts/run_upstream_baseline.py \
  --backend http --state-fixes --count 20 --max-usd 0.13 \
  --output results/upstream-gemini-fresh
```

The checkout must be pristine at the pinned revision, and outputs must be fresh.
The dollar cap is incremental for this invocation; it can stop a run before all
20 questions finish. Before each paid request, the guard uses current model
prices, a conservative UTF-8 byte bound for input tokens plus message overhead,
and the maximum output token count. Unknown billed costs prevent further calls.
The separate request cap defaults to 448. Failed/partial evidence is retained.

## Compatibility fixes

Without `--state-fixes`, `HistoryWrapper.reset(idx=...)` discards `idx` and
evaluates a NumPy-random question. The script seeds NumPy at 248 to make this
diagnostic reproducible; that seed does not recover the historical paper sample.
The offline test requests question 7107 and actually receives question 6619.
With fixes enabled, the actual question index is 7107.

The other fix keeps speculative page content, lookup cursors, step counters and
answers isolated from authoritative tool state. Hypothetical local tools execute
from the state before the real tool, and real state is restored afterward.
These fixes change defective upstream behavior and are recorded in the config;
they must not be described as an entirely unmodified execution.

## What this establishes

[Paper Figure 4 and Appendix B.2](https://arxiv.org/html/2510.04371v2#S3.F4)
evaluate next-action agreement for HotpotQA. The original loop executes its
normal and hypothetical branches serially. Running it establishes the agreement
baseline; its wall-clock duration is not a speculative-versus-sequential latency
comparison. The roughly 20% time saving reported elsewhere in the paper is a
chess result.

`summary.json` reports the original scorer alongside strict first-one/first-three
scores from the same raw candidate lists, excluding the first action and
averaging per question. The original scorer lowercases the entire action and
checks every supplied candidate for top-three; the strict score truncates to
the first three. Returned list widths are retained. Standard error across
questions is not a confidence interval or an equivalence test.

The 100-token observation cap and original request settings are preserved in
this baseline, including their truncation/compatibility limitations. A separate
GPT-5 nano probe under `results/upstream-gpt5nano-compatibility/` uses a
512-token cap and minimal reasoning. It recovered visible output, but is an
explicit settings variant and does not establish trajectory-level agreement.

The run stores `config.json`, current prices, `inference.jsonl`, complete paid
request/response bodies in `requests.jsonl`, individual task files, any failed
task, and `summary.json`. Credentials stay outside these artifacts. The source
hashes, harness hash, actual indices and billed usage make this check auditable.

The extension still needs a live no-quota comparison before a throughput claim:
required Wikipedia calls must run concurrently with speculation, candidates must
arrive early enough to start useful subsequent calls, and only matching tool
identities/arguments may reuse results. Then shared quotas and cross-agent
admission can be compared using the same workload. Forking the repository does
not itself supply that missing concurrent HotpotQA runtime.
