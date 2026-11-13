"""Recompute live paired timings, request inventory, cost and cache evidence."""

import argparse
import json
import math
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.capture import CaptureStore
from quota_spec.capture_audit import audit
from quota_spec.hotpot_runtime import paired_summary


def verify(root, blocks, banks=(), budget=0.5):
    tasks, records, checks, seen = [], [], [], set()
    for block in blocks:
        path = root / block
        config = json.loads((path / "config.json").read_text())
        if config["purpose"] != "benchmark" or config["min_request_interval_s"] != 0:
            raise ValueError("This comparison requires an unpaced benchmark")
        checked = audit(path)
        store = CaptureStore(path / "capture")
        order = config["indices"]
        if seen.intersection(order):
            raise ValueError("Question IDs overlap across blocks")
        seen.update(order)
        rows = {
            r["question_index"]: {}
            for r in (json.loads(p.read_text()) for p in (path / "tasks").glob("*.json"))
        }
        for p in (path / "tasks").glob("*.json"):
            row = json.loads(p.read_text())
            rows[row["question_index"]][row["mode"]] = row
        headstart = 0.0
        for position, question in enumerate(order):
            for mode in (
                ("sequential", "speculative")
                if position % 2 == 0
                else ("speculative", "sequential")
            ):
                task = rows[question][mode]
                if task["failure"]:
                    raise ValueError("Incomplete live pair")
                tasks.append(task)
        for episode in map(json.loads, (path / "capture/steps.jsonl").read_text().splitlines()):
            task = next(t for t in tasks if t["episode"] == episode["episode"])
            for step, trajectory in zip(episode["steps"], task["trajectory"], strict=True):
                if step["prefetch_hit"]:
                    search = store.by_id[step["search"]]
                    if search["branch"] != "prefetch":
                        raise ValueError("Reported cache hit did not use a speculative execution")
                    headstart += max(0.0, search["service_s"] - trajectory["tool_wait_s"])
        raw = [json.loads(s) for s in (path / "requests.jsonl").read_text().splitlines()]
        inference = [json.loads(s) for s in (path / "inference.jsonl").read_text().splitlines()]
        if len(raw) != len(inference) or len({r["request_id"] for r in raw}) != len(raw):
            raise ValueError("Request inventory mismatch")
        by_id = {r["request_id"]: r for r in inference}
        for request in raw:
            record = by_id[request["request_id"]]
            expected = (
                config["speculator"]
                if record["role"] == "observation_speculator"
                else config["actor"]
            )
            if request["request"]["model"] != expected:
                raise ValueError("Wrong inference role/model routing")
            if record["failure"] or record["cost_usd"] is None:
                raise ValueError("Failed or unknown-cost inference")
        records.extend(inference)
        checks.append(
            {
                "block": block,
                "audit": checked,
                "model_requests": len(raw),
                "observed_reused_service_minus_wait_s": headstart,
                "interpretation": "Local cache benefit diagnostic, not the causal explanation of independent live paths",
            }
        )
    summary = paired_summary(
        tasks,
        records,
        protocol=json.loads((root / blocks[0] / "config.json").read_text())["measurement_protocol"],
    )
    bank_cost = 0.0
    for name in banks:
        bank = root / name
        usage = json.loads((bank / "completion-usage.json").read_text())
        if usage["failures"] or usage["unknown_costs"]:
            raise ValueError("Bank has failed or unknown-cost calls")
        bank_cost += usage["cost_usd"]
    total = summary["usage"]["cost_usd"] + bank_cost
    if not math.isfinite(total) or total > budget + 1e-9:
        raise ValueError("Authorized budget exceeded")
    for mode, values in summary["by_mode"].items():
        selected = [r for r in tasks if r["mode"] == mode]
        answer_total = sum(r["answer_at_s"] - r["started_at_s"] for r in selected)
        resource_total = sum(r["drained_at_s"] - r["started_at_s"] for r in selected)
        if (
            abs(answer_total - values["answer_time_total_s"]) > 1e-6
            or abs(resource_total - values["resource_time_total_s"]) > 1e-6
        ):
            raise ValueError("Independent endpoint sum disagrees with summary")
    result = {
        "complete": True,
        "questions": len(seen),
        "episodes": len(tasks),
        "blocks": checks,
        "new_live_cost_usd": summary["usage"]["cost_usd"],
        "new_completion_cost_usd": bank_cost,
        "new_inference_total_usd": total,
        "authorized_cap_usd": budget,
        "all_costs_known": True,
        "independent_endpoint_sums_match": True,
        "actual_prefetches_during_actor_thinking": sum(
            t["prefetches_while_actor_thinking"] for t in tasks
        ),
        "quality_and_path_warning": "Independent actor paths and provider times; the paired interval, quality and matched-path counts must accompany the point estimate.",
    }
    write_json(root / "live-combined-summary.json", summary)
    write_json(root / "live-verification.json", result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--blocks", nargs="+", default=["live-block-1", "live-block-2"])
    p.add_argument("--banks", nargs="*", default=[])
    p.add_argument("--budget", type=float, default=0.5)
    a = p.parse_args()
    print(json.dumps(verify(a.root, a.blocks, a.banks, a.budget), indent=2))
