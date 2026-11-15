"""Quota/refill surfaces for a fixed predictor; every baseline and loss is retained."""

import argparse
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from .admission import AdmissionConfig, PredictiveAdmission
from .artifacts import append_json, source_hashes, write_json
from .forecast_study import TimedHistory, validate
from .frozen_replay import FrozenReplay, load_dataset, scheduling_options
from .matched_context_study import CalibratedBank
from .policies import CurrentCapacity, NoSpeculation
from .probability_calibration import ProbabilityCalibration


def surface(
    dataset,
    bank,
    calibration,
    output,
    *,
    agents=(4,),
    capacities=(4, 8, 12, 16, 24),
    windows=(1, 2, 3, 5, 10),
    seeds=(248, 249, 250),
    scope="evaluation",
    samples=32,
    generation_step_budget=None,
):
    if scope not in ("development", "evaluation"):
        raise ValueError("Declare development or evaluation scope")
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh surface output")
    tapes = load_dataset(dataset)["tapes"]
    history = TimedHistory(tapes[:20])
    selected = tapes[:20] if scope == "development" else tapes[20:]
    calibrated = ProbabilityCalibration(json.loads(Path(calibration).read_text()))
    if set(calibrated.artifact["development_ids"]) != set(history.training_ids):
        raise ValueError("Calibration development IDs differ")
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "scope": scope,
            "dataset": str(dataset),
            "bank": str(bank),
            "calibration": str(calibration),
            "agents": agents,
            "capacities": capacities,
            "windows": windows,
            "seeds": seeds,
            "samples": samples,
            "generation_step_budget": generation_step_budget,
            "source_sha256": source_hashes(),
            "notes": [
                "Fixed method; no setting selected from this evaluation surface",
                "Measured native service, no tool scaling",
                "Required FIFO, episode windows, same saved candidates and answers, all background work charged",
            ],
        },
    )
    rows = []
    with (
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network during surface")
        ),
        patch.object(
            socket.socket, "connect_ex", side_effect=AssertionError("Network during surface")
        ),
    ):
        for count in agents:
            for capacity in capacities:
                for window in windows:
                    for seed in seeds:
                        ordered = list(selected)
                        random.Random(seed).shuffle(ordered)
                        for name in ("none", "all", "cal"):
                            if name == "none":
                                rule = NoSpeculation()
                            elif name == "all":
                                rule = CurrentCapacity()
                            else:
                                predictor = CalibratedBank(history, bank, calibrated)
                                rule = PredictiveAdmission(
                                    predictor,
                                    AdmissionConfig(samples=samples, seed=seed, nonblocking=True),
                                )
                            run = FrozenReplay(
                                ordered,
                                capacity,
                                window,
                                max_active_agents=count,
                                max_candidate_age=7,
                                suppress_known_calls=True,
                                revalidate_reset=True,
                                max_generation_step=generation_step_budget
                                if name == "cal"
                                else None,
                                **scheduling_options("overlap"),
                            ).run(rule)
                            validate(run, ordered, capacity, window, count)
                            row = {
                                "agents": count,
                                "capacity": capacity,
                                "window_s": window,
                                "seed": seed,
                                "policy": name,
                                **{
                                    k: v
                                    for k, v in run["metrics"].items()
                                    if not isinstance(v, (list, dict))
                                },
                            }
                            rows.append(row)
                            append_json(output / "rows.jsonl", row)
                print("Surface complete", count, capacity, flush=True)
    write_json(output / "rows.json", rows)
    write_json(
        output / "validation.json",
        {
            "passed": True,
            "network_blocked": True,
            "runs": len(rows),
            "forecast_fallbacks": 0,
            "answers_preserved": True,
        },
    )
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--bank", type=Path, required=True)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--agents", type=int, nargs="+", default=[4])
    p.add_argument("--capacities", type=int, nargs="+", default=[4, 8, 12, 16, 24])
    p.add_argument("--windows", type=float, nargs="+", default=[1, 2, 3, 5, 10])
    p.add_argument("--seeds", type=int, nargs="+", default=[248, 249, 250])
    p.add_argument("--scope", choices=("development", "evaluation"), default="evaluation")
    p.add_argument("--samples", type=int, default=32)
    p.add_argument("--generation-step-budget", type=int, default=None)
    a = p.parse_args()
    rows = surface(
        a.dataset,
        a.bank,
        a.calibration,
        a.output,
        agents=a.agents,
        capacities=a.capacities,
        windows=a.windows,
        seeds=a.seeds,
        scope=a.scope,
        samples=a.samples,
        generation_step_budget=a.generation_step_budget,
    )
    print("Saved", len(rows), "paired surface rows")


if __name__ == "__main__":
    main()
