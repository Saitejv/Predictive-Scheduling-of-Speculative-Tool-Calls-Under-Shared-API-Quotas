"""Small tables from live multi-agent batches; retain accuracy and path agreement."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from quota_spec.artifacts import write_json


def report(root):
    runs = json.loads((root / "progress.json").read_text())["runs"]
    table, paths = [], {}
    for run in runs:
        s = run["summary"]
        key = (run["agents"], run["capacity"], run["window_s"])
        tasks = [
            json.loads(p.read_text()) for p in (Path(run["directory"]) / "tasks").glob("*.json")
        ]
        paths[key, run["policy"]] = {
            t["question_index"]: [v["action"] for v in t["trajectory"]] for t in tasks
        }
        table.append(
            {
                **{k: run[k] for k in ["agents", "capacity", "window_s", "policy", "directory"]},
                "tasks": s["tasks"],
                "mean_completion_s": s["mean_completion_s"],
                "batch_resource_s": s["resource_makespan_s"],
                "batch_answers_s": s["answer_makespan_s"],
                "correct": sum(t["em"] == 1 for t in tasks),
                "f1": s["f1"],
                "known_cost_usd": s["inference"]["known_cost_usd"]
                + s["forecasts"]["known_cost_usd"],
                "unused_prefetches": s["unused_prefetches"],
                "cache_hits": s["cache_hits"],
                "mean_required_wait_s": s["mean_required_wait_s"],
                "prefetches": s["prefetches"],
                "forecast_requests": s["forecasts"]["requests"],
                "actor_failures": s["failures"],
                "optional_failures": s["optional_failures"],
            }
        )
    agreements = []
    for key in sorted({(r["agents"], r["capacity"], r["window_s"]) for r in runs}):
        base = paths.get((key, "no_speculation"), {})
        for policy in ["allow_all", "jev", "quota"]:
            other = paths.get((key, policy), {})
            if base and other:
                agreements.append(
                    {
                        "agents": key[0],
                        "capacity": key[1],
                        "window_s": key[2],
                        "policy": policy,
                        "identical_action_paths": sum(base[t] == other[t] for t in base),
                        "tasks": len(base),
                    }
                )
    out = {
        "live": True,
        "complete": (root / "complete.json").exists(),
        "runs": len(runs),
        "episodes": sum(r["tasks"] for r in table),
        "rows": table,
        "path_agreement_vs_none": agreements,
        "limitations": "One eight-question batch per cell. Common actor seeds are best effort; provider latency and actor paths can still differ. Descriptive results, not causal or statistically confirmed wins.",
    }
    write_json(root / "report.json", out)
    with (root / "rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    policies = ["no_speculation", "allow_all", "jev", "quota"]
    for metric, name in [
        ("batch_resource_s", "Batch time including background work (seconds)"),
        ("mean_completion_s", "Mean task completion (seconds)"),
        ("correct", "Correct answers out of 8"),
        ("known_cost_usd", "Known API cost (USD)"),
    ]:
        lines = [
            name,
            "",
            "| Agents | Quota | No spec. | Allow all | Jev | Quota-aware |",
            "|---:|---|---:|---:|---:|---:|",
        ]
        for key in sorted({(r["agents"], r["capacity"], r["window_s"]) for r in table}):
            row = {
                r["policy"]: r[metric]
                for r in table
                if (r["agents"], r["capacity"], r["window_s"]) == key
            }
            values = []
            for policy in policies:
                if policy not in row:
                    values.append("—")
                elif metric == "correct":
                    values.append(str(row[policy]))
                else:
                    values.append(
                        format(row[policy], ".4f" if metric == "known_cost_usd" else ".2f")
                    )
            lines.append(f"| {key[0]} | {key[1]} / {key[2]}s | " + " | ".join(values) + " |")
        (root / f"{metric}.md").write_text("\n".join(lines) + "\n")
    print((root / "batch_resource_s.md").read_text())
    return out


def combine(sources, output):
    reports = [report(p) for p in sources]
    if not all(r["complete"] for r in reports):
        raise ValueError("Both complete matrices are required")
    groups = defaultdict(list)
    for result in reports:
        for row in result["rows"]:
            groups[row["agents"], row["capacity"], row["window_s"], row["policy"]].append(row)
    rows = []
    for (agents, capacity, window, policy), group in sorted(groups.items()):
        if len(group) != len(sources):
            raise ValueError("Unbalanced matrix replication")
        rows.append(
            {
                "agents": agents,
                "capacity": capacity,
                "window_s": window,
                "policy": policy,
                "replications": len(group),
                "task_attempts": sum(r["tasks"] for r in group),
                "mean_batch_resource_s": mean(r["batch_resource_s"] for r in group),
                "batch_range_s": [
                    min(r["batch_resource_s"] for r in group),
                    max(r["batch_resource_s"] for r in group),
                ],
                "mean_completion_s": mean(r["mean_completion_s"] for r in group),
                "correct": sum(r["correct"] for r in group),
                "known_cost_usd": sum(r["known_cost_usd"] for r in group),
                "cache_hits": sum(r["cache_hits"] for r in group),
                "unused_prefetches": sum(r["unused_prefetches"] for r in group),
                "mean_required_wait_s": mean(r["mean_required_wait_s"] for r in group),
                "forecast_requests": sum(r["forecast_requests"] for r in group),
            }
        )
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "report.json",
        {
            "rows": rows,
            "source_matrices": [str(p) for p in sources],
            "episodes": sum(r["task_attempts"] for r in rows),
            "unique_questions": 8,
            "limitations": "Two live batches per cell on the same eight questions; descriptive estimates, not confirmed causal speedups.",
        },
    )
    with (output / "rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "Mean 8-question batch time in seconds; parentheses show exact matches across 16 attempts.",
        "",
        "| Agents | Shared quota | No speculation | Allow-all | Jev | Quota-aware |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for key in sorted({(r["agents"], r["capacity"], r["window_s"]) for r in rows}):
        group = {r["policy"]: r for r in rows if (r["agents"], r["capacity"], r["window_s"]) == key}
        cells = [
            f"{group[p]['mean_batch_resource_s']:.2f} ({group[p]['correct']}/16)"
            for p in ["no_speculation", "allow_all", "jev", "quota"]
        ]
        lines.append(f"| {key[0]} | {key[1]} calls / {key[2]}s | " + " | ".join(cells) + " |")
    (output / "table.md").write_text("\n".join(lines) + "\n")
    print((output / "table.md").read_text())
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path, nargs="+")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if len(args.source) == 1:
        report(args.source[0])
    elif args.output:
        combine(args.source, args.output)
    else:
        p.error("Combining matrices requires a fresh --output")
