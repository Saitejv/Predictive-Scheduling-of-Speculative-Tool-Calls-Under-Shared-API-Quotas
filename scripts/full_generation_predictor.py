"""Perfect predictor including windows which correctly predict no more Search."""

import argparse
import copy
import csv
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.artifacts import write_json
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import load_dataset
from quota_spec.latency_study import (
    METRICS,
    aggregate,
    change_durations,
    perfect_predictions,
    replay,
)
from quota_spec.policies import CurrentCapacity


def run(root):
    out = root / "full-generation-predictor"
    if out.exists():
        raise ValueError("Choose fresh output")
    out.mkdir(parents=True)
    config = json.loads((root / "latency-sweep/config.json").read_text())
    source = load_dataset("results/hotpot-dataset-50")["tapes"][20:]
    rows = []
    streams = []
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        (out / "rows.jsonl").open("w") as f,
    ):
        for duration, scale, fixed in config["durations"]:
            for cap, window in config["settings"]:
                for workers in config["workers"]:
                    for release in [True, False]:
                        for seed in config["seeds"]:
                            tapes = change_durations(source, scale=scale, fixed=fixed)
                            random.Random(seed).shuffle(tapes)
                            oracle = perfect_predictions(tapes, screen_empty=False)
                            run = replay(
                                oracle,
                                cap,
                                window,
                                workers,
                                policy=CurrentCapacity(),
                                release=release,
                                age=999,
                                suppress=True,
                                generate_on_reuse=True,
                            )
                            validate(run, oracle, cap, window, workers)
                            m = run["metrics"]
                            for age in [0, 1]:
                                row = {
                                    "duration": duration,
                                    "capacity": cap,
                                    "window_s": window,
                                    "workers": workers,
                                    "release": release,
                                    "age": age,
                                    "suppress": age > 0,
                                    "seed": seed,
                                    "policy": "F_full_generation",
                                    "tasks": m["tasks"],
                                    **{k: m[k] for k in METRICS},
                                }
                                rows.append(row)
                                f.write(json.dumps(row) + "\n")
            f.flush()
            print(duration, len(rows), "full-generation rows", flush=True)
        for duration, scale in [("native", 1), ("scale10", 10)]:
            for repeats in [1, 10]:
                for seed in config["seeds"]:
                    order = change_durations(source, scale=scale)
                    random.Random(seed).shuffle(order)
                    tapes = []
                    for r in range(repeats):
                        for t in order:
                            clone = copy.deepcopy(t)
                            clone["task_id"] += f":repeat-{r}"
                            tapes.append(clone)
                    oracle = perfect_predictions(tapes, screen_empty=False)
                    for cap, window in [(10000, 1), (12, 30), (6, 60)]:
                        for workers in [1, 2, 4, 8]:
                            for release in [True, False]:
                                run = replay(
                                    oracle,
                                    cap,
                                    window,
                                    workers,
                                    policy=CurrentCapacity(),
                                    release=release,
                                    age=999,
                                    suppress=True,
                                    generate_on_reuse=True,
                                )
                                validate(run, oracle, cap, window, workers)
                                m = run["metrics"]
                                finishes = sorted(m["task_finish_s"].values())
                                lo = len(finishes) // 10
                                hi = 9 * len(finishes) // 10
                                streams.append(
                                    {
                                        "duration": duration,
                                        "repeats": repeats,
                                        "seed": seed,
                                        "capacity": cap,
                                        "window_s": window,
                                        "workers": workers,
                                        "release": release,
                                        "policy": "F_full_generation",
                                        "tasks": len(tapes),
                                        **{k: m[k] for k in METRICS},
                                        "questions_s": len(tapes) / m["resource_makespan_s"],
                                        "interior_questions_s": (hi - lo)
                                        / (finishes[hi] - finishes[lo]),
                                    }
                                )
            print(duration, len(streams), "full-generation stream rows", flush=True)
    write_json(out / "repeated-stream.json", streams)
    write_json(
        out / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "stream_rows": len(streams),
            "new_model_calls": 0,
            "protocol": "F full generation, including terminal source windows. Same measured source durations, next-Search candidate accuracy, generation on reuse and whole-episode retention as F screened. All started work accounted.",
        },
    )


def combine(root):
    original = [json.loads(x) for x in (root / "latency-sweep/rows.jsonl").read_text().splitlines()]
    full = [
        json.loads(x)
        for x in (root / "full-generation-predictor/rows.jsonl").read_text().splitlines()
    ]
    assert json.loads((root / "latency-sweep/completion.json").read_text())["complete"]
    summary = aggregate(original + full)
    write_json(root / "full-generation-predictor/combined-summary.json", summary)
    with (root / "full-generation-predictor/combined-summary.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in summary for k in r}))
        writer.writeheader()
        writer.writerows(summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--combine", action="store_true")
    a = p.parse_args()
    if a.combine:
        combine(a.root)
    else:
        run(a.root)
