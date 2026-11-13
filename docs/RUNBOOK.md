# Active HotpotQA baseline runbook

For complete capture, bank completion and shared-quota replay, use
[CAPTURE_REPLAY.md](CAPTURE_REPLAY.md).

Start with [README](../README.md) and [the implementation handoff](../next_steps.md).
The active driver is `quota_spec.hotpot_runtime`; the authors' serial reference
and historical quota/BM25 pipelines are separate experiments.

## Setup and verification

```sh
make setup
make prepare
make test
make lint
make offline OUTPUT=results/hotpot-smoke-fresh
```

Setup creates `.venv` and installs `.[paper,analysis,dev]`. Preparation downloads
pinned upstream source, six-shot examples, data and Apache license, verifies
Git blob hashes and records SHA-256 identities. Subsequent preparation verifies
the local files. The offline runtime expects this preparation and uses mock
inference/Search; its timings and null answer scores are only mechanics checks.
The tests block sockets when exercising the mock runtime and exporter.

`make test-baseline` selects the current runtime/export suite;
`make test-extensions` checks preserved reference and future extension code.
The baseline suite needs prepared upstream and `paper` extras to exercise all
runtime tests. Missing prerequisites are explicitly skipped by those tests.

## Unpaced live benchmark

```sh
set -a
source .env
set +a
make live OUTPUT=results/hotpot-live-fresh
```

This requests inference and Wikipedia access. It defaults to Gemini 2.5 Flash
for actor and observation predictor, seven actions, three candidate actions,
20 paired questions, $0.50 and a 2,000-request cap. There is no artificial model
submission interval. The previous `make live` shared a 1.1-second submission gate
between actor and speculation, which distorted the speed comparison; that default
has been removed. For other settings use
`.venv/bin/python -m quota_spec.hotpot_runtime --help`. Every started request is
drained and accounted for, including unused work and failures. Unknown costs
block further paid requests. Keep credentials outside recordings and docs.

For rate-paced data collection use `make capture OUTPUT=results/hotpot-capture-fresh`.
This explicitly selects capture purpose and a 1.1-second interval (override with
`CAPTURE_INTERVAL_S`). Paced capture wall times are not unpaced benchmark results.
The CLI rejects pacing under benchmark purpose before requests or output creation.

Check the single-agent baseline without inference using
`make single-agent-check OUTPUT=results/single-agent-check-fresh`. This requires
the pristine pinned original checkout at `tmp/speculative-action-upstream` and
the saved 50-question dataset. It verifies the authors' chess analysis and actual
async HotpotQA runtime independently of shared-quota simulation.

## Frozen audit and export

```sh
make report REPORT_OUTPUT=results/hotpot-report-fresh
make export EXPORT_OUTPUT=results/hotpot-stage-export-fresh
```

No inference or tool requests are made. The report uses prepared upstream
prompts and original paid source hashes, regenerates the summary and checks all
184 authoritative prompt prefixes. It writes to a fresh directory outside the
input. `PAID_SOURCE` selects the original source snapshot; active source changes
are reported separately. To audit another run directly, use:

```sh
.venv/bin/python scripts/report_hotpot_runtime.py results/another-live-run \
  --output results/another-report
```

Omitting `--source-snapshot` leaves that verification explicitly unset.
The report currently expects complete live paired recordings, not mock runs.
The [exporter](STAGE_EXPORT.md) requires no upstream installation and preserves
raw inputs in a separate export. Missing data is reported, never fetched.

## Restore the retained checkpoint

`docs/BASELINE_CHECKPOINT.json` is a tracked inventory of 218 files captured
before cleanup, including source, docs, tests, paid evidence, pinned upstream
and license. Its archive is local and Git-ignored:
`results/baseline-checkpoint-2026-11-12/baseline.tar.gz`.
SHA-256: `3fec09a8f934fc7ee359e732e59cc455f0528b3160c01b31ef95bc2f7570e512`.

A Git checkout alone does not contain the archive. Retain or transfer it
separately. Verify the checksum before extracting into an empty directory:

```sh
shasum -a 256 /path/to/baseline.tar.gz
mkdir /path/to/restored-baseline
tar -xzf /path/to/baseline.tar.gz -C /path/to/restored-baseline
```

Restore `results/hotpot-live-paired-20/`, `results/hotpot-live-audit/` and
`results/upstream-direct-gemini-20/` into a new active checkout to inspect the
paid evidence with current tools. Do not overwrite active source with the old
source snapshot. The manifest records byte counts and hashes for every archived
file. `.env` and credentials were excluded.

## Preserved reference and extensions

[The upstream reference guide](UPSTREAM_BASELINE.md) invokes the authors' serial
runner explicitly. [The historical runbook](LEGACY_RUNBOOK.md) preserves older
commands and their context. Those pipelines remain tested, but their one-candidate
replay and local-BM25 trajectories are not the current three-candidate HotpotQA
baseline. See [the extension map](ARCHITECTURE.md) before integrating them.
