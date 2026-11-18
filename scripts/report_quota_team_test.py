"""Summarize the actual quota/peer query-generator test without accuracy tradeoffs."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from quota_spec.artifacts import write_json

POLICIES = ("none", "all", "quota", "quota_team")
METRICS = (
    "mean_completion_s",
    "mean_from_batch_submit_s",
    "resource_makespan_s",
    "mean_required_wait_s",
    "p95_completion_s",
    "speculative_calls",
    "cache_hits",
    "unused_speculative_calls",
    "planner_calls",
    "planner_mean_rtt_s",
    "planner_abstentions",
)


def report(root, output):
    output.mkdir(parents=True, exist_ok=False)
    rows = json.loads((root / "rows.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    audit = json.loads((root / "independent-audit.json").read_text())
    assert audit["passed"] and len(rows) == len(protocol["cases"]) + len(protocol["cases"]) // 3
    for row in rows:
        import gzip

        run = json.loads(gzip.decompress((root / row["schedule"]).read_bytes()))
        row["mean_from_batch_submit_s"] = mean(run["metrics"]["task_finish_s"].values())
        generation = [e for e in run["events"] if e["event"] == "planner_generation_requested"]
        row["planner_calls"] = len(generation)
        row["planner_mean_rtt_s"] = mean(e["latency_s"] for e in generation) if generation else 0.0
        row["planner_abstentions"] = sum(not e["queries"] for e in generation)
    grouped = defaultdict(list)
    keys = ("agents", "capacity", "window_s", "search_s", "policy")
    for row in rows:
        grouped[tuple(row[k] for k in keys)].append(row)
    aggregate = [
        {
            **dict(zip(keys, key)),
            "orders": len(values),
            **{metric: mean(r[metric] for r in values) for metric in METRICS},
        }
        for key, values in grouped.items()
    ]
    assert all(r["orders"] == len(protocol["order_seeds"]) for r in aggregate)
    write_json(output / "aggregate.json", aggregate)
    with (output / "aggregate.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregate[0]))
        writer.writeheader()
        writer.writerows(aggregate)
    tables = {}
    cells = sorted(set((r["agents"], r["capacity"], r["window_s"], r["search_s"]) for r in rows))
    wins = []
    for metric in ("mean_from_batch_submit_s", "mean_completion_s", "resource_makespan_s"):
        lines = [
            "| Workers | Quota | Search | No speculation | Full speculation | Quota aware | Quota + agents |",
            "|---:|:---|---:|---:|---:|---:|---:|",
        ]
        for a, c, w, d in cells:
            values = {
                r["policy"]: r
                for r in aggregate
                if (r["agents"], r["capacity"], r["window_s"], r["search_s"]) == (a, c, w, d)
            }
            lines.append(
                f"| {a} | {c}/{w:g}s | {d:g}s | "
                + " | ".join(f"{values[p][metric]:.2f}" for p in POLICIES)
                + " |"
            )
            wins.append(
                dict(
                    agents=a,
                    capacity=c,
                    window_s=w,
                    search_s=d,
                    metric=metric,
                    savings_vs_quota_percent=100
                    * (1 - values["quota_team"][metric] / values["quota"][metric]),
                    saves_vs_none_and_full=all(
                        values["quota_team"][metric] < values[p][metric] for p in ("none", "all")
                    ),
                )
            )
        tables[metric] = "\n".join(lines) + "\n"
        (output / (metric + ".md")).write_text(tables[metric])
    per_order = []
    for a, c, w, d in cells:
        outcomes = []
        for seed in protocol["order_seeds"]:
            values = {
                r["policy"]: r
                for r in rows
                if (r["agents"], r["capacity"], r["window_s"], r["search_s"], r["seed"])
                == (a, c, w, d, seed)
            }
            outcomes.append(
                dict(
                    seed=seed,
                    mean_better_than_quota=values["quota_team"]["mean_completion_s"]
                    < values["quota"]["mean_completion_s"],
                    mean_from_submit_better_than_quota=values["quota_team"][
                        "mean_from_batch_submit_s"
                    ]
                    < values["quota"]["mean_from_batch_submit_s"],
                    batch_better_than_quota=values["quota_team"]["resource_makespan_s"]
                    < values["quota"]["resource_makespan_s"],
                )
            )
        per_order.append(dict(agents=a, capacity=c, window_s=w, search_s=d, orders=outcomes))
    write_json(output / "savings.json", wins)
    write_json(output / "order-comparisons.json", per_order)
    write_json(output / "audit.json", audit)
    print(tables["mean_from_batch_submit_s"])
    print(tables["mean_completion_s"])
    print(tables["resource_makespan_s"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report(args.root, args.output)
