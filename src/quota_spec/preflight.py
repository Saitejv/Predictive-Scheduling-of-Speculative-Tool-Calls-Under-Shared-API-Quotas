"""Record environment and model access without printing or storing credentials."""

import argparse
import importlib.util
import json
import os
import platform
import shutil
import urllib.request
from pathlib import Path


def inspect(output, *, online=False):
    output.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output).free
    model_id = "jaredpalmer/kev-0.8b"
    model = {"id": model_id, "tag": "v1.0", "revision": None}
    try:
        if not online:
            raise RuntimeError("Offline preflight; metadata lookup not requested")
        with urllib.request.urlopen(
            f"https://huggingface.co/api/models/{model_id}/revision/v1.0", timeout=15
        ) as response:
            metadata = json.load(response)
        model.update(revision=metadata["sha"], gated=metadata.get("gated"))
    except Exception as exc:
        model["metadata_failure"] = type(exc).__name__ if online else None
        model["metadata_status"] = "lookup_failed" if online else "not_probed_offline"
    result = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "disk_free_bytes": free,
        "packages": {
            name: importlib.util.find_spec(name) is not None
            for name in ("fastapi", "uvicorn", "httpx", "torch", "mlx_lm", "transformers")
        },
        "jev": {
            "credential_present": bool(os.environ.get("TYPESAFE_API_KEY")),
            "status": "configured_not_probed"
            if os.environ.get("TYPESAFE_API_KEY")
            else "unavailable_missing_credential",
            "contract": "POST https://api.typesafe.ai/v1/systemone; Bearer auth; state/model/questions; answers.*.noul",
            "inference_latency_s": None,
            "cost_usd": None,
            "source": "https://docs.typesafe.ai/api/system-one",
        },
        "kev": {
            "endpoint_configured": bool(os.environ.get("KEV_BASE_URL")),
            "selected_artifact": model,
            "inference_latency_s": None,
            "cost_usd": None,
            "status": "configured_not_probed"
            if os.environ.get("KEV_BASE_URL")
            else "unavailable_not_installed",
            "reason": None
            if os.environ.get("KEV_BASE_URL")
            else "Set KEV_BASE_URL to a separately configured serving endpoint.",
            "contract": "Same System One endpoint; adapter URL must target a server loaded with the selected pinned artifact",
            "source": "https://github.com/jaredpalmer/kev",
        },
        "qa": {
            "endpoint_configured": bool(os.environ.get("QA_CHAT_URL")),
            "model_configured": bool(os.environ.get("QA_MODEL")),
            "credential_present": bool(os.environ.get("QA_API_KEY")),
            "status": "configured_not_probed"
            if os.environ.get("QA_CHAT_URL") and os.environ.get("QA_MODEL")
            else "unavailable_missing_endpoint_or_model",
            "inference_latency_s": None,
            "cost_usd": None,
        },
    }
    (output / "preflight.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/access"))
    parser.add_argument(
        "--online", action="store_true", help="Fetch public model metadata (no inference)"
    )
    args = parser.parse_args()
    inspect(args.output, online=args.online)


if __name__ == "__main__":
    main()
