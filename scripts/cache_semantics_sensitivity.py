"""Control for ordinary required-result caching versus speculative-only caching."""

import argparse
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.artifacts import write_json
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import load_dataset
from quota_spec.latency_study import DURATIONS, change_durations, perfect_predictions, replay
from quota_spec.perfect_gate import exact_gates
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.tape_forecasts import TapeBankPredictor, TapeHistory


def run(output):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose fresh output")
    root.mkdir(parents=True)
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    predictor = TapeBankPredictor(
        TapeHistory(source[:20]), "results/hotpot-jev-persistent-progress-50/bank.json"
    )
    evaluation = {t["task_id"] for t in source[20:]}
    rows = []
    individual = []
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        (root / "rows.jsonl").open("w") as f,
    ):
        for cap, window, workers in [(10000, 1, 1), (12, 30, 4), (6, 60, 2)]:
            for cache in [False, True]:
                for release in [False, True]:
                    for seed in [248, 249, 250]:
                        tapes = list(source[20:])
                        random.Random(seed).shuffle(tapes)
                        scenario = {
                            "capacity": cap,
                            "window_s": window,
                            "workers": workers,
                            "cache_required_results": cache,
                            "release": release,
                            "seed": seed,
                        }

                        def save(name, run, **extra):
                            validate(run, tapes, cap, window, workers)
                            row = {**scenario, "policy": name, "metrics": run["metrics"], **extra}
                            rows.append(row)
                            f.write(json.dumps(row) + "\n")
                            f.flush()

                        for name, policy in [
                            ("A_none", NoSpeculation()),
                            ("B_ungated", CurrentCapacity()),
                            (
                                "D_jev_all",
                                PredictiveAdmission(
                                    predictor,
                                    AdmissionConfig(
                                        samples=16,
                                        horizon_s=max(30, 2 * window),
                                        seed=seed,
                                        nonblocking=True,
                                    ),
                                ),
                            ),
                        ]:
                            save(
                                name,
                                replay(
                                    tapes,
                                    cap,
                                    window,
                                    workers,
                                    policy=policy,
                                    release=release,
                                    cache_required_results=cache,
                                ),
                            )
                        oracle = perfect_predictions(tapes, screen_empty=False)
                        save(
                            "F_full_generation",
                            replay(
                                oracle,
                                cap,
                                window,
                                workers,
                                policy=CurrentCapacity(),
                                release=release,
                                age=999,
                                suppress=True,
                                generate_on_reuse=True,
                                cache_required_results=cache,
                            ),
                        )
                        solved = exact_gates(
                            tapes,
                            cap,
                            window,
                            agents=workers,
                            release_on_answer=release,
                            cache_required_results=cache,
                        )
                        for mode in ["post", "pipeline"]:
                            w = solved["winners"][mode + "_throughput"]
                            save("E_" + mode, w["run"], exact=True, selected=w["selected"])
            print(cap, window, workers, len(rows), "cache-control batch rows", flush=True)
        for duration, scale, fixed in DURATIONS:
            for t in change_durations(source, scale=scale, fixed=fixed):
                for cache in [False, True]:
                    base = replay(
                        [t], 10000, 1, 1, policy=NoSpeculation(), cache_required_results=cache
                    )["metrics"]
                    solved = exact_gates(
                        [t],
                        10000,
                        1,
                        agents=1,
                        release_on_answer=True,
                        cache_required_results=cache,
                    )
                    gate = solved["winners"]["pipeline_latency"]["metrics"]
                    perfect = replay(
                        perfect_predictions([t], screen_empty=False),
                        10000,
                        1,
                        1,
                        policy=CurrentCapacity(),
                        age=999,
                        suppress=True,
                        generate_on_reuse=True,
                        cache_required_results=cache,
                    )["metrics"]
                    individual.append(
                        {
                            "duration": duration,
                            "task_id": t["task_id"],
                            "evaluation": t["task_id"] in evaluation,
                            "cache_required_results": cache,
                            "none_s": base["mean_completion_s"],
                            "recorded_gate_exact_s": gate["mean_completion_s"],
                            "perfect_predictor_s": perfect["mean_completion_s"],
                        }
                    )
    write_json(root / "noquota.json", individual)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "batch_rows": len(rows),
            "per_task_rows": len(individual),
            "new_model_calls": 0,
            "protocol": "Same per-episode exact-query result cache for ordinary and speculative Searches when enabled. Both baseline and speculation use the same cache rule. All original defaults preserved.",
        },
    )


def extra_oracles(output):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose fresh output")
    root.mkdir(parents=True)
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    evaluation = {t["task_id"] for t in source[20:]}
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for duration, scale, fixed in DURATIONS:
            for t in change_durations(source, scale=scale, fixed=fixed):
                for cache in [False, True]:
                    for name, lookahead, zero in [
                        ("G_zero_overhead", 1, True),
                        ("H_full_lookahead", None, False),
                        ("H_full_lookahead_zero", None, True),
                    ]:
                        run = replay(
                            perfect_predictions(
                                [t], lookahead=lookahead, zero_overhead=zero, screen_empty=False
                            ),
                            10000,
                            1,
                            1,
                            policy=CurrentCapacity(),
                            age=999,
                            suppress=True,
                            generate_on_reuse=True,
                            cache_required_results=cache,
                        )
                        rows.append(
                            {
                                "duration": duration,
                                "task_id": t["task_id"],
                                "evaluation": t["task_id"] in evaluation,
                                "cache_required_results": cache,
                                "variant": name,
                                "metrics": run["metrics"],
                            }
                        )
    write_json(root / "rows.json", rows)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "new_model_calls": 0,
            "protocol": "No-quota extra oracle references under both cache rules. Full lookahead assumes all later distinct Searches can be revealed at one saved generation duration; explicit stronger architecture.",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--extra-oracles", action="store_true")
    a = p.parse_args()
    if a.extra_oracles:
        extra_oracles(a.output)
    else:
        run(a.output)
