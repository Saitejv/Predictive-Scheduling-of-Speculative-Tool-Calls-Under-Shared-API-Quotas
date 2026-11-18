"""Speed-only scenario table, using one common workload and actor seed."""

import argparse
import csv
import json
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.live_context_audit import audit


def report(extra, output):
    old = Path("results/multi-agent-2026-11-15-final")
    if not (extra / "complete.json").exists():
        raise ValueError("Missing scenario runs are not complete")
    selected = [
        r
        for r in json.loads((old / "progress.json").read_text())["runs"]
        if r["capacity"] == 12 and r["window_s"] == 3
    ] + json.loads((extra / "progress.json").read_text())["runs"]
    if len(selected) != 24:
        raise ValueError("Need exactly six scenarios and four methods")
    rows, inventories = [], []
    for run in selected:
        path = Path(run["directory"])
        config = json.loads((path / "config.json").read_text())
        if config["actor_seed"] != 5851516 or config["count"] != 8:
            raise ValueError("Workload or actor seed differs")
        inventories.append(tuple(config["indices"]))
        checked = audit(path)
        if not checked["passed"] or run["summary"]["max_active_agents"] != run["agents"]:
            raise ValueError("Scenario audit failed")
        no_limit = run["capacity"] == 1000000
        if no_limit:
            events = [json.loads(s) for s in (path / "events.jsonl").read_text().splitlines()]
            claims = [e for e in events if e["event"] == "quota_claimed"]
            if not all(e["remaining"] > 999000 for e in claims):
                raise ValueError("No-quota control became binding")
        s = run["summary"]
        rows.append(
            {
                "agents": run["agents"],
                "quota": "none" if no_limit else "12 calls / 3s",
                "policy": run["policy"],
                "mean_latency_s": s["mean_completion_s"],
                "batch_s": s["resource_makespan_s"],
                "answers_batch_s": s["answer_makespan_s"],
                "questions_per_s": 8 / s["resource_makespan_s"],
                "mean_required_wait_s": s["mean_required_wait_s"],
                "cache_hits": s["cache_hits"],
                "unused_prefetches": s["unused_prefetches"],
                "forecast_requests": s["forecasts"]["requests"],
                "known_cost_usd": s["inference"]["known_cost_usd"]
                + s["forecasts"]["known_cost_usd"],
                "source": str(path),
            }
        )
    if len(set(inventories)) != 1:
        raise ValueError("Questions differ between scenarios")
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "report.json",
        {
            "rows": rows,
            "questions": 8,
            "actor_seed": 5851516,
            "finite_quota": "12 calls per aligned 3-second window",
            "no_quota_implementation": "1,000,000 calls per window; verified never binding",
            "same_question_ids": list(inventories[0]),
            "reused_runs": 12,
            "new_runs": 12,
            "limits": "Live descriptive timings, not a large-sample or fixed-path causal comparison. Only first common-seed runs used for consistency.",
        },
    )
    with (output / "rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for metric, title in [
        (
            "batch_s",
            "Seconds to complete the same eight-question workload, including background work.",
        ),
        ("mean_latency_s", "Mean answer latency per question, seconds."),
    ]:
        lines = [
            title,
            "",
            "| Scenario | No speculation | Full speculation | Jev | Quota-aware |",
            "|---|---:|---:|---:|---:|",
        ]
        for agents, quota in [
            (1, "none"),
            (1, "12 calls / 3s"),
            (2, "12 calls / 3s"),
            (4, "12 calls / 3s"),
            (6, "12 calls / 3s"),
            (8, "12 calls / 3s"),
        ]:
            group = {
                r["policy"]: r[metric]
                for r in rows
                if r["agents"] == agents and r["quota"] == quota
            }
            if len(group) != 4:
                raise ValueError("Incomplete scenario")
            label = f"{agents} agent{'s' if agents > 1 else ''}, {'no quota' if quota == 'none' else 'with quota'}"
            lines.append(
                "| "
                + label
                + " | "
                + " | ".join(
                    f"{group[p]:.2f}" for p in ["no_speculation", "allow_all", "jev", "quota"]
                )
                + " |"
            )
        (output / f"{metric}.md").write_text("\n".join(lines) + "\n")
    print((output / "batch_s.md").read_text())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("extra", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report(args.extra, args.output)
