"""Exact gate comparison with candidates retained through one extra actor action."""

import argparse
import concurrent.futures
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
from .frozen_replay import load_dataset
from .gate_study import case_key, compact, run_one, summarize, tune
from .perfect_gate import exact_gates, useful_keys
from .policies import CurrentCapacity, FixedReserve, NoSpeculation
from .tape_forecasts import TapeBankPredictor, TapeHistory, digest

OPTIONS = {"max_candidate_age": 1, "suppress_known_calls": True}
POLICIES = (
    "none",
    "ungated",
    "reserve_tools",
    "reserve_pipeline",
    "jev_own",
    "jev_full",
    "jev_reserve",
    "perfect_reuse",
)


def solve_case(args):
    tapes, capacity, window, count, seed = args
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network in oracle")):
        solved = exact_gates(tapes, capacity, window, agents=count, **OPTIONS)
        rows = []
        for name, winner in solved["winners"].items():
            validate(winner["run"], tapes, capacity, window, count)
            if winner["metrics"]["unused_speculative_calls"]:
                raise AssertionError("Oracle unused Search")
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


def study(dataset, bank, output, *, processes=4):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose fresh output")
    data = load_dataset(dataset)
    dev, evaluation = data["tapes"][:20], data["tapes"][20:]
    history = TapeHistory(dev)
    predictor = TapeBankPredictor(history, bank)
    settings = [(10000, 1), (3, 10), (12, 5), (12, 30), (12, 60)]
    agents = [1, 2, 4, 8]
    seeds = [248, 249, 250]
    keys = useful_keys(evaluation, **OPTIONS)
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "dataset": str(dataset),
            "bank_sha256": digest(json.loads(Path(bank).read_text())),
            "settings": settings,
            "agents": agents,
            "seeds": seeds,
            "replay_options": OPTIONS,
            "oracle_keys": keys,
            "source": source_hashes(),
            "protocol": "Same deterministic timing and reserve objective as main study, with one extra actor action of candidate lifetime; exact optimal no-unused-Search admission subsets; no intentional deferred optional queue.",
        },
    )
    started = time.perf_counter()
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network")):
        choices, evidence = tune(dev, settings, agents, seeds, replay_options=OPTIONS)
    write_json(output / "tuning.json", choices)
    write_json(output / "tuning-evidence.json", evidence)
    tasks = []
    count_rows = 0
    with (
        (output / "rows.jsonl").open("w") as stream,
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network")),
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
                        elif name == "perfect_reuse":
                            policy = None
                            forced = frozenset(keys)
                        else:
                            policy = PredictiveAdmission(
                                predictor,
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
                            replay_options=OPTIONS,
                        )
                        stream.write(
                            json.dumps(
                                {
                                    "policy": name,
                                    "capacity": capacity,
                                    "window_s": window,
                                    "agents": count,
                                    "seed": seed,
                                    **compact(run["metrics"]),
                                    "logical_forecast_calls": predictor.logical_calls
                                    - before_calls,
                                    "logical_forecast_cost_usd": predictor.logical_cost_usd
                                    - before_cost,
                                    "decisions": run["decisions"],
                                }
                            )
                            + "\n"
                        )
                        stream.flush()
                        count_rows += 1
            print(f"{capacity}/{window}s: practical gates saved", flush=True)
    oracle_counts = {"settings": 0, "subsets": 0, "evaluated_schedules": 0}
    with (
        concurrent.futures.ProcessPoolExecutor(
            max_workers=processes, mp_context=multiprocessing.get_context("spawn")
        ) as pool,
        (output / "rows.jsonl").open("a") as stream,
        (output / "oracle-enumerations.jsonl").open("w") as enumeration,
    ):
        for item in pool.map(solve_case, tasks, chunksize=1):
            for row in item.pop("rows"):
                stream.write(json.dumps(row) + "\n")
                count_rows += 1
            stream.flush()
            enumeration.write(json.dumps(item) + "\n")
            enumeration.flush()
            oracle_counts["settings"] += 1
            oracle_counts["subsets"] += item["subsets"]
            oracle_counts["evaluated_schedules"] += item["schedule_evaluations"]
            if oracle_counts["settings"] % 4 == 0:
                print(
                    "Extended exact oracle:", oracle_counts["settings"], "/", len(tasks), flush=True
                )
    summary = summarize(output)
    write_json(
        output / "completion.json",
        {
            "complete": True,
            "rows": count_rows,
            "aggregate_rows": len(summary),
            "oracle": oracle_counts,
            "new_model_calls": 0,
            "elapsed_wall_s": time.perf_counter() - started,
        },
    )
    print("Complete", count_rows, "rows;", oracle_counts, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--bank", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--processes", type=int, default=4)
    a = parser.parse_args()
    study(a.dataset, a.bank, a.output, processes=a.processes)
