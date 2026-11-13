"""Read-only reconciliation of live answer latency and fixed-work throughput.

The live pair delta includes changed paths and service times. It must never be
reported as an isolated speculative throughput gain. This audit adds a common
workload bridge and a conservative shared-quota lower bound.
"""

import argparse
import copy
import json
import math
import random
import socket
import statistics
from pathlib import Path
from unittest.mock import patch

from .artifacts import source_hashes, write_json
from .capture import CaptureStore
from .capture_bank import generation_span
from .forecast_study import validate
from .frozen_replay import FrozenReplay, load_dataset, scheduling_options
from .latency_study import oracle_gate_search
from .policies import CurrentCapacity, NoSpeculation


def reconcile_seconds(live_baseline, live_speculative, fixed_baseline, fixed_speculative):
    values = (live_baseline, live_speculative, fixed_baseline, fixed_speculative)
    if not all(math.isfinite(v) and v >= 0 for v in values):
        raise ValueError("Timings must be finite nonnegative seconds")
    terms = {
        "uncontrolled_path_and_service_difference_s": live_baseline - fixed_baseline,
        "fixed_path_overlap_s": fixed_baseline - fixed_speculative,
        "live_vs_service_playback_difference_s": fixed_speculative - live_speculative,
    }
    saving = live_baseline - live_speculative
    if abs(sum(terms.values()) - saving) > 1e-9:
        raise AssertionError("Reconciliation failed")
    return {
        "live_baseline_mean_answer_s": live_baseline,
        "live_speculative_mean_answer_s": live_speculative,
        "fixed_baseline_mean_answer_s": fixed_baseline,
        "fixed_speculative_mean_answer_s": fixed_speculative,
        "observed_live_mean_answer_saving_s": saving,
        **terms,
        "warning": "Algebraic accounting, not a causal attribution of the uncontrolled difference",
    }


def quota_lower_bound(tapes, capacity, window_s):
    """Every distinct episode/query needs an execution, even with perfect reuse.

    Useful-only speculation cannot remove this minimum count. The last of N
    mandatory distinct executions cannot dispatch before floor((N-1)/C)*W.
    Add the minimum possible measured service of any such query. Generation,
    remaining actor work, FIFO and serving contention can only add time.
    """
    if type(capacity) is not int or capacity < 1 or not math.isfinite(window_s) or window_s <= 0:
        raise ValueError("Invalid fixed-window quota")
    required = {}
    for t in tapes:
        for s in t["steps"]:
            if s["tool"] == "search":
                key = (t["task_id"], s["query"])
                required[key] = min(required.get(key, math.inf), s["tool_duration_s"])
    for t in tapes:
        for s in t["steps"]:
            for c in s["window"]["candidates"] if s["window"] else ():
                key = (t["task_id"], c["query"])
                if c["eligible"] and key in required:
                    required[key] = min(required[key], c["duration_s"])
    count = len(required)
    last_dispatch = ((count - 1) // capacity) * window_s if count else 0
    service = min(required.values(), default=0)
    return {
        "minimum_distinct_searches": count,
        "earliest_last_mandatory_dispatch_s": last_dispatch,
        "minimum_search_service_s": service,
        "batch_lower_bound_s": last_dispatch + service,
        "scope": "Common exact-query caching, fixed paths, empty initial cache, aligned quota full at t=0",
    }


def live_accounting(root, tapes, blocks):
    tasks, work = [], []
    for block in blocks:
        path = root / block
        config = json.loads((path / "config.json").read_text())
        if config["purpose"] != "benchmark" or config["min_request_interval_s"] != 0:
            raise ValueError("Use unpaced benchmark recordings")
        store = CaptureStore(path / "capture")
        episode_tasks = {
            t["episode"]: t
            for t in (json.loads(p.read_text()) for p in (path / "tasks").glob("*.json"))
        }
        tasks.extend(episode_tasks.values())
        for task in episode_tasks.values():
            if abs(task["completion_s"] - (task["answer_at_s"] - task["started_at_s"])) > 1e-6:
                raise ValueError("Live answer time disagrees with recorded endpoints")
            if abs(task["resource_s"] - (task["drained_at_s"] - task["started_at_s"])) > 1e-6:
                raise ValueError("Live resource time disagrees with recorded endpoints")
            drains = [
                n for n in store.nodes if n["kind"] == "drain" and n["episode"] == task["episode"]
            ]
            if len(drains) != 1 or store.blob(drains[0]["output"]) != task:
                raise ValueError("Live task differs from immutable captured drain")
        for episode in map(json.loads, (store.root / "steps.jsonl").read_text().splitlines()):
            t = episode_tasks[episode["episode"]]
            if t["failure"]:
                raise ValueError("Live pair includes a failed episode")
            actor_s = search_s = local_s = 0.0
            for s in episode["steps"]:
                actor_s += generation_span(store, store.by_id[s["actor"]])
                if s["tool"] == "search":
                    search_s += store.by_id[s["search"]]["service_s"]
                else:
                    local_s += store.by_id[s["application"]]["local_service_s"]
            work.append(
                {
                    "question": str(t["question_index"]),
                    "mode": t["mode"],
                    "live_answer_s": t["answer_at_s"] - t["started_at_s"],
                    "live_resource_s": t["drained_at_s"] - t["started_at_s"],
                    "actor_service_s": actor_s,
                    "required_search_service_without_overlap_s": search_s,
                    "local_service_s": local_s,
                    "serial_service_s": actor_s + search_s + local_s,
                }
            )
    ids = {t["task_id"] for t in tapes}
    for mode in ("sequential", "speculative"):
        mode_work = [r for r in work if r["mode"] == mode]
        if len(mode_work) != len(ids) or {r["question"] for r in mode_work} != ids:
            raise ValueError("Live recordings and fixed tapes must contain identical question IDs")
    baseline = FrozenReplay(tapes, 10000, 1, max_active_agents=1).run(NoSpeculation())["metrics"]
    spec = FrozenReplay(
        tapes, 10000, 1, max_active_agents=1, max_candidate_age=999, suppress_known_calls=True
    ).run(CurrentCapacity())["metrics"]
    means = {
        mode: statistics.mean(r["live_answer_s"] for r in work if r["mode"] == mode)
        for mode in ("sequential", "speculative")
    }
    direct = statistics.mean(r["serial_service_s"] for r in work if r["mode"] == "speculative")
    if abs(direct - baseline["mean_completion_s"]) > 1e-8:
        raise AssertionError("Captured stage sums do not match no-overlap playback")
    return {
        "questions": len(ids),
        "episode_work": work,
        "bridge": reconcile_seconds(
            means["sequential"],
            means["speculative"],
            baseline["mean_completion_s"],
            spec["mean_completion_s"],
        ),
        "live_total_resource_s": {
            mode: sum(r["live_resource_s"] for r in work if r["mode"] == mode)
            for mode in ("sequential", "speculative")
        },
        "live_pair_interval": json.loads((root / "live-combined-summary.json").read_text())[
            "paired"
        ]["bootstrap_95_mean_saving_s"],
    }


def repeated_stream(tapes, selected, capacity, window, workers, repeats=15):
    """Repeat the same mix to expose finite-batch tails; never invent new data."""
    expanded, forced = [], set()
    for repeat in range(repeats):
        for original in tapes:
            item = copy.deepcopy(original)
            item["task_id"] = f"{original['task_id']}#repeat{repeat}"
            expanded.append(item)
            forced.update(
                (item["task_id"], step, rank)
                for tid, step, rank in selected
                if tid == original["task_id"]
            )
    options = {
        "max_candidate_age": 999,
        "suppress_known_calls": True,
        "cache_required_results": True,
        **scheduling_options("overlap"),
    }
    runner = FrozenReplay(expanded, capacity, window, max_active_agents=workers, **options)
    baseline = runner.run(NoSpeculation())
    gate = runner.run(
        forced=frozenset(forced), generation_windows=frozenset((t, s) for t, s, _ in forced)
    )
    for result in (baseline, gate):
        validate(result, expanded, capacity, window, workers)
    b, g = baseline["metrics"], gate["metrics"]
    return {
        "synthetic_repetition_of_recorded_mix": True,
        "questions": len(expanded),
        "baseline": b,
        "feasible_gate": g,
        "throughput_gain_percent": 100 * (b["resource_makespan_s"] / g["resource_makespan_s"] - 1),
        "warning": "Reuses the 20-question winner; not a global optimum on the repeated stream or new live evidence",
    }


def run(live_root, dataset, output, *, seeds=(248, 249, 250), agents=(1, 2, 4, 8)):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    tapes = load_dataset(dataset)["tapes"]
    output.mkdir(parents=True)
    settings = ((10000, 1), (12, 30), (6, 60))
    write_json(
        output / "protocol.json",
        {
            "dataset": str(dataset),
            "source": source_hashes(),
            "agents": agents,
            "seeds": seeds,
            "settings": settings,
            "candidate_lifetime": "episode",
            "cache_required_results": True,
            "source_calls": 0,
            "new_paid_usd": 0,
            "metrics": {
                "answer_latency": "Worker acceptance to answer, per question",
                "batch_answer_s": "Campaign start to last answer",
                "batch_resource_s": "Campaign start to completion of all started work",
                "throughput": "Questions / batch_resource_s",
            },
            "oracle_warning": "Large request-triggered gate sets use feasible multistart search, not a certified global optimum. A quota lower bound independently limits any possible gain.",
        },
    )
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Offline audit")):
        write_json(
            output / "live-accounting.json",
            live_accounting(Path(live_root), tapes, ["live-block-1", "live-block-2"]),
        )
        for capacity, window in settings:
            lower = quota_lower_bound(tapes, capacity, window)
            for count in agents:
                for seed in seeds:
                    ordered = list(tapes)
                    random.Random(seed).shuffle(ordered)
                    for profile in ("legacy", "overlap"):
                        options = {
                            "max_candidate_age": 999,
                            "suppress_known_calls": True,
                            "cache_required_results": True,
                            **scheduling_options(profile),
                        }
                        runner = FrozenReplay(
                            ordered, capacity, window, max_active_agents=count, **options
                        )
                        controls = {
                            "no_speculation": runner.run(NoSpeculation()),
                            "ungated": runner.run(CurrentCapacity()),
                        }
                        gates = oracle_gate_search(
                            ordered,
                            capacity,
                            window,
                            count,
                            release=options["release_on_answer"],
                            age=999,
                            suppress=True,
                            generation_trigger=options["generation_trigger"],
                            retry_candidates=options["retry_candidates"],
                            cache_required_results=True,
                            exact_limit=0,
                        )
                        for stage, winner in gates.items():
                            controls[stage + "_gate_best_found"] = winner["run"]
                        for policy, measured in controls.items():
                            validate(measured, ordered, capacity, window, count)
                            m = measured["metrics"]
                            if m["resource_makespan_s"] + 1e-8 < lower["batch_lower_bound_s"]:
                                raise AssertionError(
                                    "Schedule violates independent quota lower bound"
                                )
                            rows.append(
                                {
                                    "capacity": capacity,
                                    "window_s": window,
                                    "agents": count,
                                    "seed": seed,
                                    "profile": profile,
                                    "policy": policy,
                                    "quota_lower_bound": lower,
                                    "metrics": m,
                                }
                            )
                        name = f"{capacity}-{window}-{count}-{seed}-{profile}.json"
                        write_json(
                            output / name,
                            {
                                "controls": controls,
                                "gate_search": {
                                    k: {key: value for key, value in v.items() if key != "run"}
                                    for k, v in gates.items()
                                },
                            },
                        )
                        if profile == "overlap":
                            write_json(
                                output / ("stream-" + name),
                                repeated_stream(
                                    ordered, gates["pipeline"]["selected"], capacity, window, count
                                ),
                            )
                    write_json(output / "rows.json", rows)
                    print(capacity, window, count, seed, "verified", flush=True)
    groups = {}
    for row in rows:
        key = tuple(row[k] for k in ("capacity", "window_s", "agents", "profile", "policy"))
        groups.setdefault(key, []).append(row)
    summary = []
    for key, values in groups.items():
        result = dict(zip(("capacity", "window_s", "agents", "profile", "policy"), key))
        for name in (
            "mean_completion_s",
            "answer_makespan_s",
            "resource_makespan_s",
            "search_calls",
            "cache_hits",
            "candidates_deferred",
            "unused_speculative_calls",
        ):
            result[name] = statistics.mean(r["metrics"][name] for r in values)
        result["questions_per_s"] = statistics.mean(
            len(tapes) / r["metrics"]["resource_makespan_s"] for r in values
        )
        result["quota_lower_bound_s"] = values[0]["quota_lower_bound"]["batch_lower_bound_s"]
        summary.append(result)
    index = {
        tuple(r[k] for k in ("capacity", "window_s", "agents", "profile", "policy")): r
        for r in summary
    }
    for row in summary:
        key = tuple(row[k] for k in ("capacity", "window_s", "agents", "profile"))
        baseline = index[key + ("no_speculation",)]
        row["batch_saved_s"] = baseline["resource_makespan_s"] - row["resource_makespan_s"]
        row["throughput_gain_percent"] = 100 * (
            row["questions_per_s"] / baseline["questions_per_s"] - 1
        )
        row["maximum_possible_batch_saving_s"] = (
            baseline["resource_makespan_s"] - row["quota_lower_bound_s"]
        )
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-root", type=Path, default=Path("results/async-agent-cleanup-2026-11-13")
    )
    parser.add_argument(
        "--dataset", type=Path, default=Path("results/async-agent-cleanup-2026-11-13/pilot-dataset")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.live_root, args.dataset, args.output)


if __name__ == "__main__":
    main()
