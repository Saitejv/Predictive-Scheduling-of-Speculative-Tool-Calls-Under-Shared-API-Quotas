"""Recompute the November 15 integration campaign without inference."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.live_context_audit import audit


def report(results, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh report output")
    output.mkdir(parents=True)
    trials, known, unknown_upper, requests, forecast_requests = [], 0.0, 0.0, 0, 0
    inputs = []
    for root in sorted(results.glob("multi-agent-context-2026-11-15-*")):
        if not root.is_dir() or not (root / "summary.json").exists():
            continue
        summary = json.loads((root / "summary.json").read_text())
        if not isinstance(summary, dict) or summary.get("backend") != "http":
            continue
        config = json.loads((root / "config.json").read_text())
        tasks = [json.loads(p.read_text()) for p in (root / "tasks").glob("*.json")]
        if len(tasks) != summary["tasks"]:
            raise ValueError("Task inventory differs from summary")
        mean = statistics.mean(t["completion_s"] for t in tasks)
        if abs(mean - summary["mean_completion_s"]) > 1e-6:
            raise ValueError("Mean completion does not reproduce")
        resources = max(t["drained_at_s"] for t in tasks) - min(t["started_at_s"] for t in tasks)
        if (
            config.get("capture_protocol") == "multi_agent"
            and abs(resources - summary["resource_makespan_s"]) > 1e-6
        ):
            raise ValueError("Resource makespan does not reproduce")
        failures = sum(bool(t["failure"]) for t in tasks)
        checked = (
            audit(root)
            if not failures and config.get("capture_protocol") == "multi_agent"
            else None
        )
        events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
        reservations = {
            r["request_id"]: r["reserved_usd"] for r in events if r["event"] == "inference_started"
        }
        inference = [
            json.loads(line) for line in (root / "inference.jsonl").read_text().splitlines()
        ]
        upper = sum(
            r.get("budget_charge_usd", reservations[r["request_id"]])
            for r in inference
            if r.get("cost_usd") is None
        )
        cost = summary["inference"]["known_cost_usd"] + summary["forecasts"]["known_cost_usd"]
        known += cost
        unknown_upper += upper
        requests += summary["inference"]["requests"]
        forecast_requests += summary["forecasts"]["requests"]
        trials.append(
            {
                "name": root.name,
                "path": str(root),
                "valid_performance_run": failures == 0 and checked is not None,
                "independent_context_audit": bool(checked),
                "failed_episodes": failures,
                "recomputed_resource_makespan_s": resources,
                **summary,
                "total_known_cost_usd": cost,
                "unknown_attempt_upper_bound_usd": upper,
            }
        )
        inputs.extend(p for p in root.rglob("*") if p.is_file())
    bank = json.loads(
        (results / "multi-agent-context-2026-11-15-episode-bank/report.json").read_text()
    )
    bank_new = bank["new_collection_summary"]
    known += bank_new["known_cost_usd"]
    before = json.loads(
        (results / "multi-agent-context-2026-11-15-smoke/account-before.json").read_text()
    )
    after = json.loads((results / "multi-agent-context-2026-11-15-account-final.json").read_text())
    delta = after["usage"] - before["usage"]
    if abs(delta - known) > 1e-8:
        raise ValueError("Account delta does not reconcile to all retained known costs")
    result = {
        "live_episodes": sum(t["tasks"] for t in trials),
        "failed_episodes": sum(t["failed_episodes"] for t in trials),
        "live_chat_attempts": requests,
        "live_jev_attempts": forecast_requests,
        "new_offline_jev_attempts": bank_new["requests"],
        "provider_known_cost_usd": known,
        "unknown_attempt_upper_bound_usd": unknown_upper,
        "conservative_total_upper_bound_usd": known + unknown_upper,
        "account_usage_before_usd": before["usage"],
        "account_usage_after_usd": after["usage"],
        "account_delta_usd": delta,
        "reported_remaining_limit_usd": after["limit_remaining"],
        "account_reconciliation": "Known provider costs match the campaign account delta; two failed attempts retain individually unknown cost and their conservative upper bounds.",
        "trials": trials,
        "matched_validation": json.loads(
            (results / "multi-agent-context-2026-11-15-matched/validation.json").read_text()
        ),
        "matched": json.loads(
            (results / "multi-agent-context-2026-11-15-matched/summary.json").read_text()
        ),
        "calibration": json.loads(
            (results / "multi-agent-context-2026-11-15-calibration.json").read_text()
        )["metrics"],
    }
    inputs.extend(
        p
        for p in (results / "multi-agent-context-2026-11-15-episode-bank").rglob("*")
        if p.is_file()
    )
    inputs.extend(
        p for p in (results / "multi-agent-context-2026-11-15-matched").rglob("*") if p.is_file()
    )
    inputs.extend(
        [
            results / "multi-agent-context-2026-11-15-calibration.json",
            results / "multi-agent-context-2026-11-15-account-final.json",
        ]
    )
    write_json(output / "summary.json", result)
    write_json(
        output / "evidence-sha256.json",
        {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(inputs))},
    )
    lines = [
        "# Multi-agent context integration campaign",
        "",
        f"{result['live_episodes']} live episodes; {result['failed_episodes']} failed episodes retained. Account delta ${delta:.9f}; conservative upper bound ${known + unknown_upper:.9f}.",
        "",
        "Independent live paths do not isolate scheduling speedup. Failed runs are excluded from performance claims.",
        "",
        "| Run | Valid | Agents | Mean s | All-work s | Hits | Prefetches | EM | Known $ |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for t in trials:
        lines.append(
            f"| {t['name']} | {t['valid_performance_run']} | {t['max_active_agents']} | {t['mean_completion_s']:.3f} | {t['recomputed_resource_makespan_s']:.3f} | {t['cache_hits']} | {t['prefetches']} | {t['em']:.3f} | {t['total_known_cost_usd']:.6f} |"
        )
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, default=Path("results"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = report(a.results, a.output)
    print(
        json.dumps(
            {k: v for k, v in r.items() if k not in ("trials", "matched", "calibration")}, indent=2
        )
    )
