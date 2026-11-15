"""Preregistered paired quota confirmation with order and task-bootstrap checks."""

import argparse
import copy
import gzip
import hashlib
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
from .matched_context_study import CalibratedBank
from .policies import CurrentCapacity, FixedReserve, NoSpeculation
from .probability_calibration import ProbabilityCalibration

ENDPOINTS = ("mean_completion_s", "resource_makespan_s")


def percentile(values, p):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * p)]


def interval(values, *, seed=917, repetitions=5000):
    rng = random.Random(seed)
    means = [statistics.mean(rng.choices(values, k=len(values))) for _ in range(repetitions)]
    return [percentile(means, 0.025), percentile(means, 0.975)]


def confirm(dataset, bank, calibration, protocol, output, *, bootstrap=100, settings=None):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh confirmation output directory")
    specification = json.loads(Path(protocol).read_text())
    supported = {
        "no_speculation",
        "allow_all",
        "budget_allow_all",
        "calibrated_full",
        "calibrated_unbudgeted",
        "raw_full",
        "history_full",
        "development_tuned_reserve",
    }
    if set(specification["policies"]) - supported or not {
        "no_speculation",
        "allow_all",
        "calibrated_full",
    } <= set(specification["policies"]):
        raise ValueError("Protocol must declare the method and both valid baselines")
    tapes = load_dataset(dataset)["tapes"]
    by_id = {t["task_id"]: t for t in tapes}
    development_ids = [str(i) for i in specification["development_indices"]]
    evaluation_ids = [str(i) for i in specification["evaluation_indices"]]
    if set(development_ids) & set(evaluation_ids):
        raise ValueError("Development and evaluation questions overlap")
    if not set(development_ids + evaluation_ids) <= by_id.keys():
        raise ValueError("Dataset lacks preregistered questions")
    development = [by_id[i] for i in development_ids]
    evaluation = [by_id[i] for i in evaluation_ids]
    history = TimedHistory(development)
    calibrated = ProbabilityCalibration(json.loads(Path(calibration).read_text()))
    saved = json.loads(Path(bank).read_text())
    if (
        specification.get("http_transport")
        and saved["config"].get("http_transport", "per_request") != specification["http_transport"]
    ):
        raise ValueError("Forecast transport differs from the preregistered method")
    if set(calibrated.artifact["development_ids"]) != set(history.training_ids):
        raise ValueError("Calibration used a different development split")
    if (
        saved["config"]["dataset_sha256"]
        != hashlib.sha256((Path(dataset) / "dataset-manifest.json").read_bytes()).hexdigest()
    ):
        raise ValueError("Forecast bank and measured tapes differ")
    options = {
        **scheduling_options("overlap"),
        "max_candidate_age": 7,
        "suppress_known_calls": True,
        "revalidate_reset": True,
    }
    settings = settings or [specification["primary_setting"], *specification["secondary_settings"]]
    if specification["primary_setting"] not in settings:
        raise ValueError("Confirmation must include the preregistered primary setting")
    seeds = specification["order_seeds"]
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "protocol": specification,
            "actual_dataset": str(Path(dataset).resolve()),
            "dataset_manifest_sha256": hashlib.sha256(
                (Path(dataset) / "dataset-manifest.json").read_bytes()
            ).hexdigest(),
            "bank_sha256": saved["sha256"],
            "calibration_sha256": calibrated.artifact["sha256"],
            "bootstrap_repetitions": bootstrap,
            "settings": settings,
            "source_sha256": source_hashes(),
            "notes": [
                "Native measured service; explicit collection pacing excluded, real provider backoff included",
                "Networking disabled throughout replay",
                "Task bootstrap resamples complete measured trajectories; forecasts remain frozen and development-only",
            ],
        },
    )
    package = Path(__file__).parent
    (output / "source-snapshot").mkdir()
    for name in source_hashes():
        (output / "source-snapshot" / name).write_bytes((package / name).read_bytes())

    def execute(selected, setting, seed, name, reserve=0):
        pred = None
        if name == "no_speculation":
            policy = NoSpeculation()
        elif name in ("allow_all", "budget_allow_all"):
            policy = CurrentCapacity()
        elif name == "development_tuned_reserve":
            policy = FixedReserve(reserve)
        else:
            pred = (
                history
                if name == "history_full"
                else TimedBank(history, bank)
                if name == "raw_full"
                else CalibratedBank(history, bank, calibrated)
            )
            policy = PredictiveAdmission(
                pred,
                AdmissionConfig(
                    samples=specification["samples"],
                    horizon_s=specification["horizon_s"],
                    max_calls=specification["max_calls"],
                    seed=seed,
                    nonblocking=True,
                ),
            )
        run = FrozenReplay(
            selected,
            setting["capacity"],
            setting["window_s"],
            max_active_agents=setting["agents"],
            max_generation_step=specification.get("generation_step_budget")
            if name in ("calibrated_full", "budget_allow_all")
            else None,
            **options,
        ).run(policy)
        validate(run, selected, setting["capacity"], setting["window_s"], setting["agents"])
        return run

    rows = []
    tuning_runs = 0
    with (
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network during confirmation")
        ),
        patch.object(
            socket.socket, "connect_ex", side_effect=AssertionError("Network during confirmation")
        ),
    ):
        for setting in settings:
            choices = []
            for reserve in range(setting["capacity"] + 1):
                values = []
                for seed in seeds[:2]:
                    ordered = list(development)
                    random.Random(seed).shuffle(ordered)
                    base = execute(ordered, setting, seed, "no_speculation")["metrics"]
                    tested = execute(ordered, setting, seed, "development_tuned_reserve", reserve)[
                        "metrics"
                    ]
                    tuning_runs += 2
                    values.append(
                        (
                            tested[ENDPOINTS[0]]
                            / base[ENDPOINTS[0]]
                            * tested[ENDPOINTS[1]]
                            / base[ENDPOINTS[1]]
                        )
                        ** 0.5
                    )
                choices.append((statistics.mean(values), reserve))
            reserve = min(choices)[1]
            key = f"{setting['agents']}-{setting['capacity']}-{setting['window_s']:g}"
            write_json(
                output / f"tuning-{key}.json",
                {
                    "choice": reserve,
                    "scores": choices,
                    "criterion": "Development-only geometric mean of mean-completion and resource-makespan ratios to no speculation; two order seeds",
                },
            )
            for seed in seeds:
                ordered = list(evaluation)
                random.Random(seed).shuffle(ordered)
                for name in specification["policies"]:
                    run = execute(ordered, setting, seed, name, reserve)
                    filename = f"{key}-{seed}-{name}.json.gz"
                    with gzip.open(output / filename, "wt") as stream:
                        json.dump(run, stream)
                    row = {
                        **setting,
                        "seed": seed,
                        "policy": name,
                        "schedule": filename,
                        **{
                            k: v
                            for k, v in run["metrics"].items()
                            if not isinstance(v, (dict, list))
                        },
                    }
                    rows.append(row)
                    append_json(output / "rows.jsonl", row)
            print("Confirmed setting", key, flush=True)
        comparisons = []
        for setting in settings:
            for baseline in ("no_speculation", "allow_all"):
                by = {
                    (r["seed"], r["policy"]): r
                    for r in rows
                    if all(r[k] == v for k, v in setting.items())
                }
                for endpoint in ENDPOINTS:
                    savings = [
                        by[seed, baseline][endpoint] - by[seed, "calibrated_full"][endpoint]
                        for seed in seeds
                    ]
                    comparisons.append(
                        {
                            **setting,
                            "baseline": baseline,
                            "endpoint": endpoint,
                            "mean_saving_s": statistics.mean(savings),
                            "saving_percent": 100
                            * statistics.mean(savings)
                            / statistics.mean(by[seed, baseline][endpoint] for seed in seeds),
                            "order_seed_interval_s": interval(savings),
                            "positive_orders": sum(v > 0 for v in savings),
                            "orders": len(seeds),
                        }
                    )
        write_json(output / "comparisons.json", comparisons)
        # Primary question-cluster robustness: no trimming and no invented tool service.
        primary = specification["primary_setting"]
        rng = random.Random(75193)
        bootstrap_rows = []
        for repetition in range(bootstrap):
            selected = []
            for index, original in enumerate(rng.choices(evaluation, k=len(evaluation))):
                tape = copy.deepcopy(original)
                tape["task_id"] = f"{original['task_id']}#draw{index}"
                selected.append(tape)
            seed = 10000 + repetition
            metrics = {
                name: execute(selected, primary, seed, name)["metrics"]
                for name in ("no_speculation", "allow_all", "calibrated_full")
            }
            row = {
                "repetition": repetition,
                **{
                    f"{base}:{endpoint}": metrics[base][endpoint]
                    - metrics["calibrated_full"][endpoint]
                    for base in ("no_speculation", "allow_all")
                    for endpoint in ENDPOINTS
                },
            }
            bootstrap_rows.append(row)
            append_json(output / "task-bootstrap.jsonl", row)
            if (repetition + 1) % 10 == 0:
                print("Task bootstrap", repetition + 1, "/", bootstrap, flush=True)
        bootstrap_intervals = (
            {
                f"{base}:{endpoint}": [
                    percentile([r[f"{base}:{endpoint}"] for r in bootstrap_rows], 0.025),
                    percentile([r[f"{base}:{endpoint}"] for r in bootstrap_rows], 0.975),
                ]
                for base in ("no_speculation", "allow_all")
                for endpoint in ENDPOINTS
            }
            if bootstrap
            else {}
        )
        primary_comparisons = [r for r in comparisons if all(r[k] == v for k, v in primary.items())]
        passed = (
            bool(bootstrap)
            and all(r["order_seed_interval_s"][0] > 0 for r in primary_comparisons)
            and all(v[0] > 0 for v in bootstrap_intervals.values())
        )
        primary_hits = sum(
            r["cache_hits"]
            for r in rows
            if r["policy"] == "calibrated_full" and all(r[k] == v for k, v in primary.items())
        )
        passed = passed and primary_hits > 0
        result = {
            "success": passed,
            "primary_comparisons": primary_comparisons,
            "task_bootstrap_intervals_s": bootstrap_intervals,
            "native_timing": True,
            "answers_preserved": True,
            "network_blocked": True,
            "forecast_fallbacks": 0,
            "replay_runs": len(rows) + 3 * bootstrap,
            "development_tuning_runs": tuning_runs,
            "primary_cache_hits_across_orders": primary_hits,
            "limitations": "Order-seed intervals measure scheduling-order variation. Task bootstrap conditions on the trained predictor and measured service-time sample; neither estimates live-provider variability.",
        }
        write_json(output / "result.json", result)
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--bank", type=Path, required=True)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--bootstrap", type=int, default=100)
    args = p.parse_args()
    print(
        json.dumps(
            confirm(
                args.dataset,
                args.bank,
                args.calibration,
                args.protocol,
                args.output,
                bootstrap=args.bootstrap,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
