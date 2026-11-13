"""Full deterministic gate analysis: fixed messages/tools and exact ideal subsets."""

import argparse
import concurrent.futures
import csv
import hashlib
import json
import multiprocessing
import random
import socket
import time
from pathlib import Path
from unittest.mock import patch

from .admission import AdmissionConfig, PredictiveAdmission
from .artifacts import source_hashes, write_json
from .forecast_study import ReserveFloor, validate
from .frozen_replay import FrozenReplay, load_dataset
from .perfect_gate import exact_gates, useful_keys
from .policies import CurrentCapacity, FixedReserve, NoSpeculation, UsageForecastReserve
from .speculation_audit import unlimited_reference
from .tape_forecasts import TapeBankPredictor, TapeHistory, digest

POLICIES = (
    "none",
    "ungated",
    "reserve_tools",
    "reserve_pipeline",
    "usage_reserve",
    "history_full",
    "jev_own",
    "jev_full",
    "jev_reserve",
    "perfect_reuse",
)


def compact(metrics):
    return {
        k: v
        for k, v in metrics.items()
        if k not in ["answers", "required_waits_s", "task_start_s", "task_finish_s"]
    }


def case_key(capacity, window, agents):
    return f"{capacity}:{window:g}:{agents}"


def reserve_values(tapes, capacity):
    # Remaining quota cannot fall below capacity minus every possible Search in
    # this finite stream. Lower reserves are equivalent; representative zero
    # plus every distinct high threshold exhausts all effective integer rules.
    maximum = sum(s["tool"] == "search" for t in tapes for s in t["steps"]) + sum(
        c["eligible"]
        for t in tapes
        for s in t["steps"]
        if s["window"]
        for c in s["window"]["candidates"]
    )
    return sorted({0, *range(max(0, capacity - maximum), capacity + 1)})


def run_one(
    tapes,
    capacity,
    window,
    agents,
    policy,
    *,
    generation_reserve=None,
    forced=None,
    generation_windows=None,
    replay_options=None,
):
    run = FrozenReplay(
        tapes,
        capacity,
        window,
        max_active_agents=agents,
        generation_reserve=generation_reserve,
        **(replay_options or {}),
    ).run(policy, forced=forced, generation_windows=generation_windows)
    validate(run, tapes, capacity, window, agents)
    return run


def tune(development, settings, agents, seeds, *, replay_options=None):
    choices = {}
    evidence = []
    for capacity, window in settings:
        candidates = reserve_values(development, capacity)
        for count in agents:
            choice = {}
            for mode in ["tools", "pipeline"]:
                values = []
                for reserve in candidates:
                    scores = []
                    latencies = []
                    for seed in seeds[:2]:
                        tapes = list(development)
                        random.Random(seed).shuffle(tapes)
                        run = run_one(
                            tapes,
                            capacity,
                            window,
                            count,
                            FixedReserve(reserve),
                            generation_reserve=reserve if mode == "pipeline" else None,
                            replay_options=replay_options,
                        )
                        scores.append(run["metrics"]["resource_makespan_s"])
                        latencies.append(run["metrics"]["mean_completion_s"])
                    values.append(
                        (sum(scores) / len(scores), sum(latencies) / len(latencies), reserve)
                    )
                choice[mode] = min(values)[2]
                evidence.append(
                    {
                        "capacity": capacity,
                        "window_s": window,
                        "agents": count,
                        "mode": mode,
                        "scores": values,
                    }
                )
            choices[case_key(capacity, window, count)] = choice
    return choices, evidence


def oracle_case(task):
    tapes, capacity, window, count, seed = task
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("Network in exact oracle")
    ):
        solved = exact_gates(tapes, capacity, window, agents=count)
        rows = []
        for name, winner in solved["winners"].items():
            validate(winner["run"], tapes, capacity, window, count)
            if winner["metrics"]["unused_speculative_calls"]:
                raise AssertionError("Perfect gate dispatched unused Search")
            rows.append(
                {
                    "policy": "ideal_" + name,
                    "capacity": capacity,
                    "window_s": window,
                    "agents": count,
                    "seed": seed,
                    **compact(winner["metrics"]),
                    "selected": winner["selected"],
                    "exact": True,
                    "oracle_bits": solved["candidate_bits"],
                    "oracle_subsets": solved["subsets"],
                }
            )
        return {
            "capacity": capacity,
            "window_s": window,
            "agents": count,
            "seed": seed,
            "rows": rows,
            "keys": solved["keys"],
            "subsets": solved["subsets"],
            "schedule_evaluations": solved["schedule_evaluations"],
            "solver_wall_s": solved["solver_wall_s"],
            "score_columns": [
                "mask",
                "post_mean_s",
                "post_resource_s",
                "pipeline_mean_s",
                "pipeline_resource_s",
            ],
            "scores": solved["scores"],
        }


def summarize(output):
    rows = [json.loads(line) for line in (output / "rows.jsonl").read_text().splitlines()]
    grouped = {}
    for row in rows:
        grouped.setdefault(
            (row["capacity"], row["window_s"], row["agents"], row["policy"]), []
        ).append(row)
    summary = []
    for (capacity, window, count, policy), values in grouped.items():
        row = {
            "capacity": capacity,
            "window_s": window,
            "agents": count,
            "policy": policy,
            "seeds": len(values),
        }
        for field in [
            "mean_completion_s",
            "p95_completion_s",
            "mean_required_wait_s",
            "resource_makespan_s",
            "answer_makespan_s",
            "speculative_calls",
            "unused_speculative_calls",
            "cache_hits",
            "observation_runs",
            "hypothetical_runs",
            "predictor_overhead_s",
        ]:
            row[field] = sum(v[field] for v in values) / len(values)
        row["throughput_questions_s"] = sum(
            v["tasks"] / v["resource_makespan_s"] for v in values
        ) / len(values)
        row["logical_forecast_calls"] = sum(
            v.get("logical_forecast_calls", 0) for v in values
        ) / len(values)
        row["logical_forecast_cost_usd"] = sum(
            v.get("logical_forecast_cost_usd", 0) for v in values
        ) / len(values)
        summary.append(row)
    index = {(r["capacity"], r["window_s"], r["agents"], r["policy"]): r for r in summary}
    for row in summary:
        baseline = index[row["capacity"], row["window_s"], row["agents"], "none"]
        row["mean_saving_percent"] = 100 * (
            1 - row["mean_completion_s"] / baseline["mean_completion_s"]
        )
        row["throughput_gain_percent"] = 100 * (
            row["throughput_questions_s"] / baseline["throughput_questions_s"] - 1
        )
    write_json(output / "summary.json", summary)
    with (output / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    return summary


def study(
    dataset, bank, output, *, settings=None, agents=(1, 2, 4, 8), seeds=(248, 249, 250), processes=4
):
    dataset, bank, output = Path(dataset), Path(bank), Path(output)
    if output.exists():
        raise ValueError("Choose fresh output")
    data = load_dataset(dataset)
    development, evaluation = data["tapes"][:20], data["tapes"][20:]
    history = TapeHistory(development)
    predictor = TapeBankPredictor(history, bank)
    config = json.loads(bank.read_text())["config"]
    if (
        config["dataset_sha256"]
        != hashlib.sha256((dataset / "dataset-manifest.json").read_bytes()).hexdigest()
    ):
        raise ValueError("Forecast dataset mismatch")
    keys = useful_keys(evaluation)
    if len(keys) > 12:
        raise ValueError("Exact enumeration requires a declared bounded candidate universe")
    settings = settings or [(10000, 1)] + [
        (c, w) for c in [1, 3, 6, 12] for w in [1, 5, 10, 30, 60]
    ]
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "version": 1,
            "dataset_sha256": config["dataset_sha256"],
            "forecast_sha256": digest(json.loads(bank.read_text())),
            "development": [t["task_id"] for t in development],
            "evaluation": [t["task_id"] for t in evaluation],
            "settings": settings,
            "agents": agents,
            "seeds": seeds,
            "policies": POLICIES,
            "source": source_hashes(),
            "oracle_keys": keys,
            "oracle_constraint": "Never launch a candidate absent from future required searches; original window lifetime and FIFO ordering. Enumerate every on-time useful subset.",
            "protocol": [
                "Same main-agent actions and measured model/tool service duration under every policy",
                "Local capture submission queues excluded consistently; no new provider calls",
                "Continuous worker pool; one quota persists across all evaluation questions; worker drains started work",
                "Fixed phase-entry forecast contexts, measured response time and cost; parallel per-agent Jev queries",
                "Deterministic 1 ms scheduler budget per decision; CPU wall cost reported separately",
                "16 sampled future chains, at most 4 searches per chain; horizon max(30, twice refill period)",
                "Reserves tuned for full-resource throughput on 20 development tasks and first two order seeds",
                "Perfect gate references have zero forecast cost/latency, retain generation/model/tool delays",
                "Ideal post-generation gate pays all naturally started generation work; ideal pipeline gate can skip unselected windows",
                "Latency-optimal and throughput-optimal oracle schedules are separate; solver CPU is offline, not a deployable policy",
                "Unlimited provider/model/tool serving concurrency apart from the declared Search quota; no live capacity claim",
            ],
        },
    )
    started = time.perf_counter()
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("Network in deterministic study")
    ):
        choices, evidence = tune(development, settings, agents, seeds)
    write_json(output / "tuning.json", choices)
    write_json(output / "tuning-evidence.json", evidence)
    print("Development reserve tuning complete", flush=True)
    tasks = []
    rows = []
    with (
        (output / "rows.jsonl").open("w") as stream,
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network in deterministic study")
        ),
    ):
        for capacity, window in settings:
            for count in agents:
                reserve = choices[case_key(capacity, window, count)]
                for seed in seeds:
                    tapes = list(evaluation)
                    random.Random(seed).shuffle(tapes)
                    tasks.append((tapes, capacity, window, count, seed))
                    for name in POLICIES:
                        before_calls, before_cost = (
                            predictor.logical_calls,
                            predictor.logical_cost_usd,
                        )
                        generation_reserve = None
                        forced = None
                        if name == "none":
                            policy = NoSpeculation()
                        elif name == "ungated":
                            policy = CurrentCapacity()
                        elif name == "reserve_tools":
                            policy = FixedReserve(reserve["tools"])
                        elif name == "reserve_pipeline":
                            policy = FixedReserve(reserve["pipeline"])
                            generation_reserve = reserve["pipeline"]
                        elif name == "usage_reserve":
                            policy = UsageForecastReserve()
                        elif name == "perfect_reuse":
                            policy = None
                            forced = frozenset(keys)
                        else:
                            forecasts = history if name == "history_full" else predictor
                            policy = PredictiveAdmission(
                                forecasts,
                                AdmissionConfig(
                                    samples=16,
                                    horizon_s=max(30, 2 * window),
                                    overhead_s=0.001,
                                    seed=seed,
                                    nonblocking=True,
                                ),
                                own_only=name == "jev_own",
                            )
                            if name == "jev_reserve":
                                policy = ReserveFloor(policy, reserve["pipeline"])
                                generation_reserve = reserve["pipeline"]
                        run = run_one(
                            tapes,
                            capacity,
                            window,
                            count,
                            policy,
                            generation_reserve=generation_reserve,
                            forced=forced,
                        )
                        row = {
                            "policy": name,
                            "capacity": capacity,
                            "window_s": window,
                            "agents": count,
                            "seed": seed,
                            **compact(run["metrics"]),
                            "logical_forecast_calls": predictor.logical_calls - before_calls,
                            "logical_forecast_cost_usd": predictor.logical_cost_usd - before_cost,
                            "decisions": run["decisions"],
                        }
                        if name == "perfect_reuse" and row["unused_speculative_calls"]:
                            raise AssertionError("Reuse oracle waste")
                        stream.write(json.dumps(row) + "\n")
                        stream.flush()
                        rows.append(row)
            print(f"{capacity}/{window}s: practical and reuse gates saved", flush=True)
    oracle_counts = {"settings": 0, "subsets": 0, "evaluated_schedules": 0}
    with (
        concurrent.futures.ProcessPoolExecutor(
            max_workers=processes, mp_context=multiprocessing.get_context("spawn")
        ) as pool,
        (output / "rows.jsonl").open("a") as stream,
        (output / "oracle-enumerations.jsonl").open("w") as enumeration,
    ):
        for item in pool.map(oracle_case, tasks, chunksize=1):
            for row in item.pop("rows"):
                stream.write(json.dumps(row) + "\n")
                rows.append(row)
            stream.flush()
            enumeration.write(json.dumps(item) + "\n")
            enumeration.flush()
            oracle_counts["settings"] += 1
            oracle_counts["subsets"] += item["subsets"]
            oracle_counts["evaluated_schedules"] += item["schedule_evaluations"]
            if oracle_counts["settings"] % 12 == 0:
                print(
                    "Exact oracle settings solved:",
                    oracle_counts["settings"],
                    "/",
                    len(tasks),
                    flush=True,
                )
    # All 50 traces also receive independent no-quota arithmetic. Mean latency
    # separates by task with unlimited resources, so per-task optima are exact.
    all50 = []
    for tape in data["tapes"]:
        solved = exact_gates([tape], 10000, 1, agents=1)
        a = unlimited_reference(tape, False)
        b = unlimited_reference(tape, True)
        all50.append(
            {
                "task_id": tape["task_id"],
                "none_s": a["completion_s"],
                "ungated_s": b["completion_s"],
                "ideal_post_latency_s": solved["winners"]["post_latency"]["metrics"][
                    "mean_completion_s"
                ],
                "ideal_pipeline_latency_s": solved["winners"]["pipeline_latency"]["metrics"][
                    "mean_completion_s"
                ],
                "actor_local_lower_bound_s": sum(
                    s["actor_duration_s"] + (s["tool_duration_s"] if s["tool"] != "search" else 0)
                    for s in tape["steps"]
                ),
            }
        )
    write_json(output / "all50-noquota-arithmetic.json", all50)
    summary = summarize(output)
    write_json(
        output / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "aggregate_rows": len(summary),
            "elapsed_wall_s": time.perf_counter() - started,
            "oracle": oracle_counts,
            "new_model_calls": 0,
            "validated_network_blocked": True,
        },
    )
    print("Complete", len(rows), "policy rows;", oracle_counts, flush=True)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset")
    p.add_argument("--bank", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--processes", type=int, default=4)
    p.add_argument("--seeds", type=int, nargs="+", default=[248, 249, 250])
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args()
    study(
        a.dataset,
        a.bank,
        a.output,
        processes=a.processes,
        seeds=a.seeds,
        settings=[(10000, 1), (3, 10)] if a.smoke else None,
    )


if __name__ == "__main__":
    main()
