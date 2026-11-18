"""Audit quota, actual concurrency, archived source and common actor seeds."""

import argparse
import hashlib
import json
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.capture import CaptureStore
from quota_spec.live_context_audit import audit
from quota_spec.quota_speculation import MARKER


def inspect(roots, output):
    checked, actor_requests, source_files = [], 0, 0
    for root in roots:
        if not (root / "complete.json").exists():
            raise ValueError("Audit requires complete matrices")
        runs = json.loads((root / "progress.json").read_text())["runs"]
        for run in runs:
            path = Path(run["directory"])
            config = json.loads((path / "config.json").read_text())
            summary = run["summary"]
            result = audit(path)
            if summary["max_active_agents"] != run["agents"] or summary["tasks"] != 8:
                raise ValueError("Workload or concurrency mismatch")
            if (
                config["quota_epoch"] != "batch_dispatch; setup excluded"
                or summary["batch_started_at_s"] > 0.1
            ):
                raise ValueError("Quota epoch includes setup time")
            if run["policy"] == "quota" and summary["forecasts"]["requests"]:
                raise ValueError("Direct quota planner unexpectedly called Jev")
            for name, digest in config["source_sha256"].items():
                if (
                    hashlib.sha256((path / "source-snapshot" / name).read_bytes()).hexdigest()
                    != digest
                ):
                    raise ValueError("Frozen source mismatch")
                source_files += 1
            store = CaptureStore(path / "capture")
            for line in (path / "requests.jsonl").read_text().splitlines():
                record = json.loads(line)
                node = store.by_id[record["capture_node"]]
                body = record["request"]
                if node["branch"] == "actor":
                    identity = (
                        f"{config['actor_seed']}:{node['episode'].split(':')[0]}:{node['step']}"
                    )
                    expected = (
                        int.from_bytes(hashlib.sha256(identity.encode()).digest()[:4], "big")
                        & 0x7FFFFFFF
                    )
                    if (
                        body.get("seed") != expected
                        or "response_format" in body
                        or MARKER in body["messages"][-1]["content"]
                    ):
                        raise ValueError("Actor randomness or prompt isolation mismatch")
                    actor_requests += 1
            checked.append(
                {
                    "directory": str(path),
                    "pass": True,
                    "episodes": result["episodes"],
                    "agents": run["agents"],
                    "actor_seed": config["actor_seed"],
                }
            )
    report = {
        "pass": True,
        "runs": len(checked),
        "episodes": sum(c["episodes"] for c in checked),
        "actor_requests_seed_checked": actor_requests,
        "source_files_verified": source_files,
        "main_quota_context_leaks": 0,
        "quota_or_fifo_violations": 0,
        "checks": checked,
    }
    write_json(output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path, nargs="+")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    inspect(args.sources, args.output)
