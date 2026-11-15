"""Paired same-work Jev/calibration study with complete episode-window contexts."""

import argparse
import json
import random
import socket
import statistics
from pathlib import Path
from unittest.mock import patch

from .admission import AdmissionConfig, PredictiveAdmission
from .artifacts import append_json, source_hashes, write_json
from .forecast_study import TimedBank, TimedHistory, validate
from .frozen_replay import FrozenReplay, load_dataset, scheduling_options
from .policies import CurrentCapacity, FixedReserve, NoSpeculation
from .probability_calibration import ProbabilityCalibration
from .tape_forecasts import digest


class CalibratedBank(TimedBank):
    def __init__(self, history, bank, calibration):
        super().__init__(history, bank)
        self.calibration = calibration

    def predict(self, state, agent):
        return self.calibration.transform(super().predict(state, agent))


def study(
    dataset,
    bank,
    calibration,
    output,
    *,
    agents=(1, 4, 8),
    seeds=(248, 249, 250),
    settings=((10000, 10), (12, 5), (12, 10)),
    samples=16,
):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    tapes = load_dataset(dataset)["tapes"]
    development, evaluation = tapes[:20], tapes[20:]
    history = TimedHistory(development)
    calibrated = ProbabilityCalibration(json.loads(Path(calibration).read_text()))
    saved = json.loads(Path(bank).read_text())
    if saved["config"].get("max_candidate_age", 0) < 7:
        raise ValueError("Need complete episode-window forecast bank")
    if set(calibrated.artifact["development_ids"]) != set(history.training_ids):
        raise ValueError("Calibration development mismatch")
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "dataset": str(dataset),
            "bank_sha256": saved["sha256"],
            "calibration_sha256": calibrated.artifact["sha256"],
            "agents": agents,
            "seeds": seeds,
            "settings": settings,
            "samples": samples,
            "development_ids": list(history.training_ids),
            "evaluation_ids": [t["task_id"] for t in evaluation],
            "source_sha256": source_hashes(),
            "scheduling": "overlap; episode windows; no ordinary required-result cache",
            "assumptions": [
                "Fixed measured service times and fixed answers; unlimited provider capacity",
                "Exact finite phase-entry elapsed=0 forecasts; logical calls retain measured latency and cost",
                "The historical 20/30 cohort has already been explored; this is a diagnostic, not confirmatory evidence",
                "Native Search durations; no added tool delay",
                "Full and own rules share all forecast inputs, risk checks and paired scenarios",
            ],
        },
    )
    options = {
        **scheduling_options("overlap"),
        "max_candidate_age": 7,
        "suppress_known_calls": True,
        "revalidate_reset": True,
    }

    def execute(selected, count, capacity, window, seed, name, reserve=0):
        ordered = list(selected)
        random.Random(seed).shuffle(ordered)
        predictor = None
        if name == "no_speculation":
            rule = NoSpeculation()
        elif name == "current_capacity":
            rule = CurrentCapacity()
        elif name == "fixed_reserve":
            rule = FixedReserve(reserve)
        else:
            predictor = (
                history
                if name == "history_full"
                else CalibratedBank(history, bank, calibrated)
                if name.startswith("calibrated")
                else TimedBank(history, bank)
            )
            rule = PredictiveAdmission(
                predictor,
                AdmissionConfig(samples=samples, seed=seed, nonblocking=True),
                own_only=name.endswith("_own"),
            )
        run = FrozenReplay(ordered, capacity, window, max_active_agents=count, **options).run(rule)
        validate(run, ordered, capacity, window, count)
        return run, predictor

    rows = []
    names = (
        "no_speculation",
        "current_capacity",
        "fixed_reserve",
        "history_full",
        "jev_own",
        "jev_full",
        "calibrated_own",
        "calibrated_full",
    )
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("Network during matched replay")
    ):
        for capacity, window in settings:
            reserves = range(capacity + 1) if capacity <= 24 else (0, capacity)
            tuning = []
            for reserve in reserves:
                scores = [
                    execute(development, count, capacity, window, seed, "fixed_reserve", reserve)[
                        0
                    ]["metrics"]["mean_completion_s"]
                    for count in agents
                    for seed in seeds[:2]
                ]
                tuning.append((statistics.mean(scores), reserve))
            reserve = min(tuning)[1]
            write_json(
                output / f"tuning-{capacity}-{window:g}.json", {"choice": reserve, "scores": tuning}
            )
            for count in agents:
                for seed in seeds:
                    for name in names:
                        run, predictor = execute(
                            evaluation, count, capacity, window, seed, name, reserve
                        )
                        filename = f"{capacity}-{window:g}-{count}-{seed}-{name}.json"
                        write_json(output / filename, run)
                        row = {
                            "capacity": capacity,
                            "window_s": window,
                            "agents": count,
                            "seed": seed,
                            "policy": name,
                            "reserve": reserve,
                            "schedule": filename,
                            **{
                                k: v
                                for k, v in run["metrics"].items()
                                if not isinstance(v, (dict, list))
                            },
                            "logical_forecast_calls": getattr(predictor, "logical_calls", 0),
                            "logical_forecast_cost_usd": getattr(predictor, "logical_cost_usd", 0),
                            "unknown_forecast_costs": getattr(predictor, "unknown_cost_calls", 0),
                        }
                        rows.append(row)
                        append_json(output / "rows.jsonl", row)
                print(
                    f"Matched capacity={capacity}/{window:g}s agents={count} complete", flush=True
                )
    fields = (
        "mean_completion_s",
        "resource_makespan_s",
        "p95_completion_s",
        "mean_required_wait_s",
        "speculative_calls",
        "cache_hits",
        "unused_speculative_calls",
        "logical_forecast_calls",
        "logical_forecast_cost_usd",
    )
    aggregate = []
    for capacity, window in settings:
        for count in agents:
            for name in names:
                selected = [
                    r
                    for r in rows
                    if (r["capacity"], r["window_s"], r["agents"], r["policy"])
                    == (capacity, window, count, name)
                ]
                aggregate.append(
                    {
                        "capacity": capacity,
                        "window_s": window,
                        "agents": count,
                        "policy": name,
                        **{
                            field: statistics.mean(r[field] for r in selected)
                            for field in fields
                            if field in selected[0]
                        },
                    }
                )
    write_json(output / "summary.json", aggregate)
    write_json(
        output / "validation.json",
        {
            "passed": True,
            "runs": len(rows),
            "forecast_fallbacks": 0,
            "network_blocked": True,
            "answers_preserved": True,
            "inputs_sha256": digest(
                {"bank": saved["sha256"], "calibration": calibrated.artifact["sha256"]}
            ),
        },
    )
    return aggregate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--bank", type=Path, required=True)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--agents", type=int, nargs="+", default=[1, 4, 8])
    p.add_argument("--seeds", type=int, nargs="+", default=[248, 249, 250])
    p.add_argument("--samples", type=int, default=16)
    a = p.parse_args()
    result = study(
        a.dataset,
        a.bank,
        a.calibration,
        a.output,
        agents=a.agents,
        seeds=a.seeds,
        samples=a.samples,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
