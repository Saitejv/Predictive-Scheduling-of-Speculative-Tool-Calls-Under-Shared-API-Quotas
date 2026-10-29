# Model access audit

Historical access audit, October 28, 2026. Preflight is now offline by default;
use `--online` to refresh public metadata. See `API_SETUP.md` for the current
mock-tested connection workflow. The original hardware/access observations follow.

Checked October 28, 2026. The executable audit is `python -m quota_spec.preflight`;
its output is `results/access/preflight.json`. It records credential presence,
never credential values. The tested machine is Apple Silicon with 8 GiB RAM.
Only about 2 GiB of disk headroom remained during the access audit.

## Jev

No `TYPESAFE_API_KEY` is configured. Live inference, latency and monetary cost
remain unmeasured. The adapter is implemented and tested against mock contract
responses, malformed predictions and a real total-request timeout.

The primary [System One API documentation](https://docs.typesafe.ai/api/system-one)
specifies a bearer-authenticated POST to `/v1/systemone`, with model, observed
state and named typed questions. We ask three probability questions: exact
candidate reuse, upcoming demand, and continuation after the next call. Timing
samples come from the development-only history table. No fallback is labeled
as a successful Jev prediction; predictor failure rejects speculation.

## Kev

Selected pretrained artifact: `jaredpalmer/kev-0.8b`, tag `v1.0`, resolved by
Hugging Face to revision `bf75a6a8848ea6960ff2ed108d9ed44c2941174f`.
Metadata is public and was successfully retrieved. No runtime or weights are
installed and no `KEV_BASE_URL` is configured. Loading a model and its base
weights/dependencies was not feasible with the remaining local disk headroom.
Latency, cost and calibration for Kev remain unmeasured.

[Upstream Kev](https://github.com/jaredpalmer/kev) documents source installation
and a System One-compatible server. Do not install the unrelated PyPI `kev`
package. On a host with enough disk/memory, install from that repository and
serve the selected pinned artifact:

```sh
uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b@bf75a6a8848ea6960ff2ed108d9ed44c2941174f --port 8009
```

Set `KEV_BASE_URL=http://127.0.0.1:8009` for this project's adapter. Record the
server's code revision, loaded weight revision, device and dtype with results.
The server's `kev-latest` request alias alone does not identify its loaded
weights; the operator must retain the pinned launch configuration.

## What remains

Supply Jev access and a working pinned Kev server, then run all five context
modes on the same evaluation traces. Configure known input/output token prices
if cost should be computed; unknown prices remain null. Use the new `quota_spec.qa --backend http` main-model QA integration, record its cost and candidate/context
construction time, and evaluate actual answers. Existing evidence-equality
checks are a tool-correctness gate, not an answer-quality measurement.
