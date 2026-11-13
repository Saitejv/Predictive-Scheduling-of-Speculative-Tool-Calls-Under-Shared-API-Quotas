"""Separate perfect candidate accuracy from quota admission quality (offline)."""

import argparse
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.artifacts import write_json
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import load_dataset
from quota_spec.latency_study import change_durations, oracle_gate_search, perfect_predictions


def run(output):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose fresh output")
    root.mkdir(parents=True)
    source = load_dataset("results/hotpot-dataset-50")["tapes"][20:]
    rows = []
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        (root / "rows.jsonl").open("w") as f,
    ):
        for label, factor in [("native", 1), ("scale10", 10)]:
            for cap, window in [(12, 30), (6, 60)]:
                for workers in [1, 2, 4, 8]:
                    for seed in [248, 249, 250]:
                        tapes = change_durations(source, scale=factor)
                        random.Random(seed).shuffle(tapes)
                        oracle = perfect_predictions(tapes)
                        gates = oracle_gate_search(
                            oracle,
                            cap,
                            window,
                            workers,
                            release=True,
                            age=999,
                            suppress=True,
                            exact_limit=0,
                            generate_on_reuse=True,
                        )
                        for mode, winner in gates.items():
                            run = winner["run"]
                            validate(run, oracle, cap, window, workers)
                            row = {
                                "duration": label,
                                "capacity": cap,
                                "window_s": window,
                                "workers": workers,
                                "seed": seed,
                                "policy": "F_gate_" + mode,
                                "exact": winner["exact"],
                                "selected": winner["selected"],
                                "bits": winner["bits"],
                                "evaluations": winner["evaluations"],
                                "metrics": run["metrics"],
                            }
                            rows.append(row)
                            f.write(json.dumps(row) + "\n")
                            f.flush()
                print(label, cap, window, len(rows), "perfect-predictor gated rows", flush=True)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "new_model_calls": 0,
            "warning": "Feasible best-found global subsets, not exact optima. Measured generation overhead, source windows selected clairvoyantly in pipeline mode. One shared quota, answer release, next-Search oracle and generation on reuse.",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    run(a.output)
