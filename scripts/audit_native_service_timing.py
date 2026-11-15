"""Check independently recorded HTTP timing against capture service/queue clocks."""

import argparse
import json
from pathlib import Path

from quota_spec.capture import CaptureStore


def audit(root):
    store = CaptureStore(root / "capture")
    checks = []
    for node in store.nodes:
        if node["kind"] != "search" or node["status"] != "completed":
            continue
        result = store.blob(node["output"])
        if "http_network_s" not in result:
            raise ValueError("Missing independent HTTP network measurement")
        if node["service_s"] + 1e-6 < result["http_network_s"]:
            raise ValueError("Native service shorter than actual HTTP work")
        if result["collection_pacing_s"] + 1e-6 < result["http_mutex_wait_s"]:
            raise ValueError("Artificial pacing mutex wait leaked into native service")
        if node["queue_s"] + 1e-6 < result["collection_pacing_s"]:
            raise ValueError("Collection pacing is absent from queue accounting")
        if node["service_s"] + node["queue_s"] > node["elapsed_s"] + 0.01:
            raise ValueError("Service plus queue exceeds actual capture duration")
        checks.append(
            {
                "node": node["id"],
                "service_s": node["service_s"],
                "http_network_s": result["http_network_s"],
                "collection_queue_s": result["collection_pacing_s"],
                "mutex_s": result["http_mutex_wait_s"],
                "http_backoff_s": result["http_backoff_s"],
            }
        )
    return {"passed": True, "searches": len(checks), "checks": checks}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    a = p.parse_args()
    print(json.dumps(audit(a.source), indent=2))
