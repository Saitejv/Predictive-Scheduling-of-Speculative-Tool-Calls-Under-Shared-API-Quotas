"""Reconcile every quota-prompt API attempt, including failed experiments."""

import argparse
import hashlib
import json
from pathlib import Path

from quota_spec.artifacts import write_json


def audit(output, account_snapshot=None):
    records, sources, snapshots = [], [], 0
    roots = [p for p in Path("results").glob("quota-prompt-2026-11-15-*") if p.is_dir()]
    for root in sorted(roots):
        for name in ["inference.jsonl", "forecasts.jsonl"]:
            for path in sorted(root.rglob(name)):
                config = path.parent / "config.json"
                if config.exists() and json.loads(config.read_text()).get("backend") == "mock":
                    continue
                rows = [json.loads(s) for s in path.read_text().splitlines() if s]
                known = sum(r["cost_usd"] for r in rows if r.get("cost_usd") is not None)
                unknown = [r for r in rows if r.get("cost_usd") is None]
                bound = sum(r.get("budget_charge_usd", 0) for r in unknown)
                sources.append(
                    {
                        "file": str(path),
                        "requests": len(rows),
                        "known_cost_usd": known,
                        "unknown_cost_attempts": len(unknown),
                        "unknown_upper_bound_usd": bound,
                    }
                )
                records.extend(rows)
                requests = path.with_name("requests.jsonl")
                if name == "inference.jsonl" and requests.exists():
                    if len(requests.read_text().splitlines()) != len(rows):
                        raise ValueError(f"Request/usage inventory differs: {path}")
        for config_path in root.rglob("config.json"):
            snapshot = config_path.parent / "source-snapshot"
            if not snapshot.exists():
                continue
            config = json.loads(config_path.read_text())
            for name, digest in config["source_sha256"].items():
                if hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f"Source snapshot mismatch: {snapshot / name}")
                snapshots += 1
    result = {
        "requests": len(records),
        "known_cost_usd": sum(r["known_cost_usd"] for r in sources),
        "unknown_cost_attempts": sum(r["unknown_cost_attempts"] for r in sources),
        "unknown_upper_bound_usd": sum(r["unknown_upper_bound_usd"] for r in sources),
        "source_files_verified": snapshots,
        "sources": sources,
    }
    if account_snapshot:
        before = json.loads(
            Path(
                "results/quota-prompt-2026-11-15-live-pilot/00-12-3-b0-quota/account-before.json"
            ).read_text()
        )
        after = json.loads(account_snapshot.read_text())
        delta = after["usage"] - before["usage"]
        result.update(
            account_delta_usd=delta,
            account_minus_known_usd=delta - result["known_cost_usd"],
            reconciled_to_known_costs=abs(delta - result["known_cost_usd"]) < 1e-8,
        )
        if (
            not result["known_cost_usd"] - 1e-8
            <= delta
            <= result["known_cost_usd"] + result["unknown_upper_bound_usd"] + 1e-8
        ):
            raise ValueError("Settled account delta falls outside recorded cost bounds")
    write_json(output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--account-snapshot", type=Path)
    args = p.parse_args()
    audit(args.output, args.account_snapshot)
