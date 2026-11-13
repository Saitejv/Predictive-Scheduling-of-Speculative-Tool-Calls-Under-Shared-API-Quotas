"""Summarize paired asynchronous admission experiments from immutable replay rows."""

import argparse
import json
import math
import random
import statistics
from pathlib import Path

from quota_spec.artifacts import write_json


def analyze(root):
    root = Path(root)
    rows = [json.loads(line) for line in (root / "rows.jsonl").read_text().splitlines()]
    summary = json.loads((root / "summary.json").read_text())
    idx = {(r["capacity"], r["window_s"], r["agents"], r["variant"]): r for r in summary}
    comparisons = []
    for variant in [
        "overlap_jev_full",
        "persistent_jev_full",
        "persistent_history_full",
        "hybrid_jev_full",
        "detached_hybrid",
        "detached_reserve",
        "budgeted_reserve",
        "budgeted_hybrid",
    ]:
        for baseline in [
            "no_speculation",
            "classic_reserve",
            "legacy_jev_full",
            "persistent_reserve",
        ]:
            pairs = []
            for r in summary:
                if r["variant"] != variant:
                    continue
                other = idx.get((r["capacity"], r["window_s"], r["agents"], baseline))
                if other is None:
                    continue
                pairs.append(
                    {
                        "capacity": r["capacity"],
                        "window_s": r["window_s"],
                        "agents": r["agents"],
                        "throughput_percent": 100
                        * (r["throughput_questions_s"] / other["throughput_questions_s"] - 1),
                        "completion_saving_percent": 100
                        * (1 - r["mean_completion_s"] / other["mean_completion_s"]),
                        "mean_completion_s": r["mean_completion_s"],
                        "baseline_mean_s": other["mean_completion_s"],
                        "post_action_launches": r["post_action_launches"],
                        "cache_hits": r["cache_hits"],
                    }
                )
            multi = [r for r in pairs if r["agents"] > 1]
            if not multi:
                continue
            comparisons.append(
                {
                    "variant": variant,
                    "baseline": baseline,
                    "settings": len(pairs),
                    "multi_agent_settings": len(multi),
                    "geomean_multi_agent_throughput_percent": 100
                    * (
                        math.exp(
                            statistics.mean(
                                math.log(1 + p["throughput_percent"] / 100) for p in multi
                            )
                        )
                        - 1
                    ),
                    "multi_agent_throughput_wins_over_1_percent": sum(
                        p["throughput_percent"] > 1 for p in multi
                    ),
                    "multi_agent_throughput_losses_over_1_percent": sum(
                        p["throughput_percent"] < -1 for p in multi
                    ),
                    "best": max(multi, key=lambda p: p["throughput_percent"]),
                    "worst": min(multi, key=lambda p: p["throughput_percent"]),
                    "pairs": pairs,
                }
            )
    counts = {}
    for variant in sorted({r["variant"] for r in rows}):
        values = [r for r in rows if r["variant"] == variant]
        counts[variant] = {
            k: sum(r[k] for r in values)
            for k in [
                "speculative_calls",
                "cache_hits",
                "unused_speculative_calls",
                "post_action_launches",
                "logical_forecast_calls",
                "logical_forecast_cost_usd",
            ]
        }
    result = {
        "runs": len(rows),
        "comparisons": comparisons,
        "totals": counts,
        "warning": "Same exploratory fixed question bank, repeated workload-order seeds; selected best cells are not held-out discoveries; geometric means weight quota/worker settings equally",
    }
    write_json(root / "ANALYSIS.json", result)
    return result


def paired_interval(root, variant, baseline, capacity, window, agents):
    rows = [json.loads(line) for line in (Path(root) / "rows.jsonl").read_text().splitlines()]

    def select(name):
        return {
            r["seed"]: r
            for r in rows
            if (r["variant"], r["capacity"], r["window_s"], r["agents"])
            == (name, capacity, window, agents)
        }

    a, b = select(variant), select(baseline)
    seeds = sorted(a.keys() & b.keys())
    delta = [b[s]["mean_completion_s"] - a[s]["mean_completion_s"] for s in seeds]
    rng = random.Random(99)
    bootstrap = sorted(statistics.mean(rng.choices(delta, k=len(delta))) for _ in range(5000))
    return {
        "mean_saving_s": statistics.mean(delta),
        "order_seed_bootstrap95_s": [bootstrap[125], bootstrap[4874]],
        "seed_saving_range_s": [min(delta), max(delta)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("studies", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.studies:
        result = analyze(path)
        print(path, "runs", result["runs"])
        for comparison in result["comparisons"]:
            if comparison["baseline"] in ["classic_reserve", "legacy_jev_full"]:
                print(
                    comparison["variant"],
                    "vs",
                    comparison["baseline"],
                    "multi-agent throughput geomean",
                    round(comparison["geomean_multi_agent_throughput_percent"], 3),
                    "wins/losses",
                    comparison["multi_agent_throughput_wins_over_1_percent"],
                    comparison["multi_agent_throughput_losses_over_1_percent"],
                    "best",
                    comparison["best"],
                    "worst",
                    comparison["worst"],
                )


if __name__ == "__main__":
    main()
