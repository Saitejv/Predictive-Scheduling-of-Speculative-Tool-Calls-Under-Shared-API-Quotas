"""Describe randomized live quota-prompt pilots without same-path speedup claims."""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

from quota_spec.artifacts import write_json
from quota_spec.capture import CaptureStore
from quota_spec.quota_speculation import parse_queries


def report(root):
    progress = json.loads((root / "progress.json").read_text())
    groups = defaultdict(list)
    question_rows = defaultdict(dict)
    choices = defaultdict(list)
    costs = 0.0
    for run in progress["runs"]:
        directory = Path(run["directory"])
        summary = run["summary"]
        key = (run["capacity"], run["window_s"], run["policy"])
        groups[key].append(summary)
        costs += summary["inference"]["known_cost_usd"] + summary["forecasts"]["known_cost_usd"]
        for p in (directory / "tasks").glob("*.json"):
            task = json.loads(p.read_text())
            question_rows[run["capacity"], run["window_s"], task["question_index"]][
                run["policy"]
            ] = task
        if run["policy"] in {"blind", "quota"}:
            store = CaptureStore(directory / "capture")
            for node in store.nodes:
                if node["kind"] != "generation" or node["branch"] != "speculative_actor":
                    continue
                data = store.blob(node["input"])
                attempt = store.by_id[data["attempts"][-1]]
                actions = parse_queries(store.blob(attempt["output"])["content"], data["width"])
                context = data["quota_context"]
                remaining = context["remaining_calls"] if context else None
                headroom = (
                    max(
                        0,
                        remaining
                        - context["queued_required_calls"]
                        - (
                            context["other_active_workers"]
                            if context["seconds_to_refill"] > 1
                            else 0
                        ),
                    )
                    if context
                    else None
                )
                choices[key].append(
                    {
                        "remaining_calls": remaining,
                        "queries": len(actions),
                        "observed_headroom": headroom,
                        "preserves_instructed_headroom": len(actions) <= headroom
                        if context
                        else None,
                    }
                )
    aggregates = []
    for (capacity, window, policy), group in sorted(groups.items()):
        aggregates.append(
            {
                "capacity": capacity,
                "window_s": window,
                "policy": policy,
                "tasks": sum(r["tasks"] for r in group),
                "blocks": len(group),
                **{
                    k: mean(r[k] for r in group)
                    for k in [
                        "mean_completion_s",
                        "resource_makespan_s",
                        "em",
                        "f1",
                    ]
                },
                **{
                    k: sum(r[k] for r in group)
                    for k in [
                        "prefetches",
                        "cache_hits",
                        "unused_prefetches",
                        "optional_failures",
                    ]
                },
                "forecast_requests": sum(r["forecasts"]["requests"] for r in group),
                "planner_choices": choices[capacity, window, policy],
            }
        )
    comparisons = []
    for capacity, window in sorted({k[:2] for k in groups}):
        for baseline in ["no_speculation", "allow_all", "jev", "blind"]:
            pairs = [
                (tasks[baseline], tasks["quota"])
                for (c, w, _), tasks in question_rows.items()
                if (c, w) == (capacity, window) and {baseline, "quota"} <= tasks.keys()
            ]
            if not pairs:
                continue
            differences = [a["completion_s"] - b["completion_s"] for a, b in pairs]
            identical = sum(
                [s["action"] for s in a["trajectory"]] == [s["action"] for s in b["trajectory"]]
                for a, b in pairs
            )
            rng = random.Random(585)
            boot = sorted(mean(rng.choices(differences, k=len(pairs))) for _ in range(10000))
            comparisons.append(
                {
                    "capacity": capacity,
                    "window_s": window,
                    "baseline": baseline,
                    "pairs": len(pairs),
                    "identical_action_paths": identical,
                    "quota_mean_saving_s": mean(differences),
                    "quota_mean_saving_percent": 100
                    * mean(differences)
                    / mean(a["completion_s"] for a, _ in pairs),
                    "descriptive_question_bootstrap_95_s": [boot[249], boot[9749]],
                    "caveat": "Shared workers and provider variability make questions dependent; only two independent blocks per setting",
                }
            )
    first = Path(progress["runs"][0]["directory"])
    last = Path(progress["runs"][-1]["directory"])
    delta = (
        json.loads((last / "account-after.json").read_text())["usage"]
        - json.loads((first / "account-before.json").read_text())["usage"]
    )
    result = {
        "live_pilot": True,
        "runs": len(progress["runs"]),
        "complete": (root / "complete.json").exists(),
        "known_cost_usd": costs,
        "account_snapshot_delta_usd": delta,
        "account_snapshot_unreconciled_usd": costs - delta,
        "accounting_note": "Immediate key-usage snapshots can lag provider usage; reconcile the whole campaign after settlement",
        "aggregates": aggregates,
        "comparisons": comparisons,
        "limitations": "Exploratory autonomous live paths; this does not replace the locked matched-replay result",
    }
    write_json(root / "report.json", result)
    for r in aggregates:
        print(
            r["capacity"],
            r["window_s"],
            r["policy"],
            r["tasks"],
            f"mean={r['mean_completion_s']:.3f}",
            f"batch={r['resource_makespan_s']:.3f}",
            f"prefetch={r['prefetches']}",
            f"hits={r['cache_hits']}",
            f"optional_fail={r['optional_failures']}",
            f"EM={r['em']:.3f}",
        )
    print("Cost", costs)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    report(p.parse_args().source)
