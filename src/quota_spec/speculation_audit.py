"""Reconcile live wall-clock speedups with same-trajectory scheduling replay.

The unlimited-quota reference is a serial recurrence, independent of the replay
engine's event heap. It determines candidate availability at each next true actor
action and compares every task's completion and exact-cache hits.
"""

import argparse
import json
import random
import socket
import statistics
from pathlib import Path
from unittest.mock import patch

from .artifacts import write_json
from .frozen_replay import FrozenReplay, load_dataset
from .policies import CurrentCapacity, NoSpeculation

LIVE_SOURCES = (
    "hotpot-capture-pilot-complete-7",
    "hotpot-capture-pilot-remaining-13",
    "hotpot-capture-expansion-30",
)


def unlimited_reference(tape, speculate):
    """No heap, queues, quota or policy code; only serial authoritative dependencies.

    A window opened at uncached Search i can launch before action i+1 returns.
    Past launched results remain cached. A cache hit never opens another window.
    """
    now, window, cache, hits = 0.0, None, {}, 0
    timeline = []
    for index, row in enumerate(tape["steps"]):
        actor_start = now
        ready = actor_start + row["actor_duration_s"]
        # The previous window expires at this actor's returned action, not at
        # actor start. Its candidates can finish generation during thinking.
        if window is not None and window["ready_s"] < ready:
            for candidate in window["candidates"]:
                if candidate["eligible"] and candidate["query"] not in cache:
                    cache[candidate["query"]] = window["ready_s"] + candidate["duration_s"]
        window = None
        hit = row["tool"] == "search" and row["query"] in cache
        if hit:
            hits += 1
            now = max(ready, cache[row["query"]])
        else:
            now = ready + row["tool_duration_s"]
            if speculate and row["tool"] == "search" and row["window"]:
                value = row["window"]
                window = {
                    "ready_s": ready
                    + value["observation_duration_s"]
                    + value["hypothetical_duration_s"],
                    "candidates": value["candidates"],
                }
        timeline.append(
            {
                "step": index + 1,
                "action": row["action"],
                "actor_start_s": actor_start,
                "required_ready_s": ready,
                "step_finished_s": now,
                "hit": hit,
            }
        )
    return {"completion_s": now, "cache_hits": hits, "timeline": timeline}


def live_components(root):
    root = Path(root)
    config = json.loads((root / "config.json").read_text())
    tasks = [json.loads(p.read_text()) for p in (root / "tasks").glob("*.json")]
    records = [json.loads(line) for line in (root / "inference.jsonl").read_text().splitlines()]
    result = {
        "source": str(root),
        "configured_request_interval_s": config.get("min_request_interval_s", 0),
        "by_mode": {},
        "question_ids": config["indices"],
    }
    for mode in ["sequential", "speculative"]:
        selected = [t for t in tasks if t["mode"] == mode and t["failure"] is None]
        actors = [r for r in records if r["role"] == "actor" and r["episode"].endswith(":" + mode)]
        actor = sum(r["latency_s"] for r in actors)
        queue = sum(r.get("queue_s", 0) for r in actors)
        tools = sum(s["tool_wait_s"] for t in selected for s in t["trajectory"])
        wall = sum(t["completion_s"] for t in selected)
        result["by_mode"][mode] = {
            "questions": len(selected),
            "wall_total_s": wall,
            "mean_s": wall / len(selected),
            "actor_service_s": actor,
            "actor_queue_s": queue,
            "tool_wait_s": tools,
            "other_s": wall - actor - queue - tools,
            "cache_hits": sum(t["cache_hits"] for t in selected),
            "actor_requests": len(actors),
            "actions": sum(len(t["trajectory"]) for t in selected),
        }
    return result


def audit(project, output):
    project, output = Path(project), Path(output)
    if output.exists():
        raise ValueError("Choose fresh audit output")
    data = load_dataset(project / "results/hotpot-dataset-50")
    tapes = data["tapes"]
    live = [live_components(project / "results" / name) for name in LIVE_SOURCES]
    original = live_components(project / "results/hotpot-live-paired-20")
    original_saved = json.loads(
        (project / "results/hotpot-live-paired-20/summary.json").read_text()
    )
    original_overlap = json.loads(
        (project / "results/hotpot-live-paired-20/audit.json").read_text()
    )["prefetch_overlap_s"]
    checks = []
    matched = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network during audit")):
        for tape in tapes:
            pair = {}
            for speculate, policy in [(False, NoSpeculation()), (True, CurrentCapacity())]:
                expected = unlimited_reference(tape, speculate)
                actual = FrozenReplay([tape], 10000, 1).run(policy)["metrics"]
                error = abs(expected["completion_s"] - actual["mean_completion_s"])
                if error > 1e-8 or expected["cache_hits"] != actual["cache_hits"]:
                    raise AssertionError(
                        (
                            "Independent recurrence disagreement",
                            tape["task_id"],
                            speculate,
                            expected,
                            actual,
                        )
                    )
                checks.append(error)
                pair["speculative" if speculate else "no_prefetch"] = expected
            matched.append(
                {
                    "task_id": tape["task_id"],
                    "no_prefetch_s": pair["no_prefetch"]["completion_s"],
                    "speculative_s": pair["speculative"]["completion_s"],
                    "cache_hits": pair["speculative"]["cache_hits"],
                    "saving_s": pair["no_prefetch"]["completion_s"]
                    - pair["speculative"]["completion_s"],
                    "timeline": pair["speculative"]["timeline"],
                }
            )
        schedules = []
        for split, subset in [("all50", tapes), ("dev20", tapes[:20]), ("eval30", tapes[20:])]:
            for workers in [1, 4, 8]:
                for capacity, window in [(10000, 1), (12, 5), (12, 30)]:
                    for seed in [248, 249, 250, 251, 252]:
                        ordered = list(subset)
                        random.Random(seed).shuffle(ordered)
                        for name, policy in [
                            ("no_prefetch", NoSpeculation()),
                            ("speculative", CurrentCapacity()),
                        ]:
                            result = FrozenReplay(
                                ordered, capacity, window, max_active_agents=workers
                            ).run(policy)
                            m = result["metrics"]
                            schedules.append(
                                {
                                    "split": split,
                                    "workers": workers,
                                    "capacity": capacity,
                                    "window_s": window,
                                    "seed": seed,
                                    "mode": name,
                                    **{
                                        k: m[k]
                                        for k in [
                                            "mean_completion_s",
                                            "mean_required_wait_s",
                                            "resource_makespan_s",
                                            "cache_hits",
                                            "speculative_calls",
                                            "unused_speculative_calls",
                                            "observation_runs",
                                            "hypothetical_runs",
                                            "late_windows",
                                        ]
                                    },
                                }
                            )
    original_seq = original["by_mode"]["sequential"]
    original_spec = original["by_mode"]["speculative"]
    live_total = {}
    for mode in ["sequential", "speculative"]:
        values = [r["by_mode"][mode] for r in live]
        live_total[mode] = {
            key: sum(value[key] for value in values) for key in values[0] if key != "mean_s"
        }
        live_total[mode]["mean_s"] = (
            live_total[mode]["wall_total_s"] / live_total[mode]["questions"]
        )
    groups = {}
    for label, subset in [("all50", matched), ("dev20", matched[:20]), ("eval30", matched[20:])]:
        no = sum(r["no_prefetch_s"] for r in subset)
        yes = sum(r["speculative_s"] for r in subset)
        groups[label] = {
            "questions": len(subset),
            "no_prefetch_mean_s": no / len(subset),
            "speculative_mean_s": yes / len(subset),
            "saving_total_s": no - yes,
            "saving_percent": 100 * (1 - yes / no),
            "cache_hits": sum(r["cache_hits"] for r in subset),
        }
    required = [s["tool_duration_s"] for t in tapes for s in t["steps"] if s["tool"] == "search"]
    observation = [
        s["window"]["observation_duration_s"] for t in tapes for s in t["steps"] if s["window"]
    ]
    hypothetical = [
        s["window"]["hypothetical_duration_s"] for t in tapes for s in t["steps"] if s["window"]
    ]
    result = {
        "version": 1,
        "original_live_20": original,
        "later_live_shards": live,
        "later_live_50": live_total,
        "matched_unlimited_quota": groups,
        "independent_reference_checks": len(checks),
        "max_completion_error_s": max(checks),
        "original_live_reconciliation": {
            "observed_total_saving_s": original_seq["wall_total_s"] - original_spec["wall_total_s"],
            "actor_service_difference_s": original_seq["actor_service_s"]
            - original_spec["actor_service_s"],
            "tool_wait_difference_s": original_seq["tool_wait_s"] - original_spec["tool_wait_s"],
            "other_difference_s": original_seq["other_s"] - original_spec["other_s"],
            "logged_useful_prefetch_overlap_s": original_overlap,
            "tool_wait_difference_not_isolated_as_prefetch_s": original_seq["tool_wait_s"]
            - original_spec["tool_wait_s"]
            - original_overlap,
            "warning": "Timing reconciliation, not a causal attribution of the independent live trajectories",
        },
        "original_paired_uncertainty_s": original_saved["paired"]["bootstrap_95_mean_saving_s"],
        "native_medians_s": {
            "search": statistics.median(required),
            "observation": statistics.median(observation),
            "hypothetical_actor": statistics.median(hypothetical),
        },
        "comparison_warning": "Live wall times, paced capture wall times, and same-path service-time replays are distinct comparisons. 12 calls/5 seconds is not guaranteed nonbinding for multiple agents with speculation.",
    }
    output.mkdir(parents=True)
    write_json(output / "AUDIT.json", result)
    write_json(output / "matched-tasks.json", matched)
    write_json(output / "schedules.json", schedules)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=Path, default=Path("."))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    r = audit(args.project, args.output)
    print(
        json.dumps(
            {k: v for k, v in r.items() if k not in ["later_live_shards", "original_live_20"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
