"""Development tuning, frozen held-out sweeps, and paired run-level bootstrap."""

import argparse
import json
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

from .admission import AdmissionConfig, PredictiveAdmission
from .models import load_tasks, nonnegative, positive_int
from .policies import CurrentCapacity, FixedReserve, NoSpeculation, UsageForecastReserve
from .prediction import HistoryPredictor, PerturbedPredictor, calibration
from .provenance import git_state
from .replay import Replay, percentile
from .search import sha256_json
from .workload import dump_tasks


def source_hashes():
    import hashlib

    root = Path(__file__).resolve().parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))}


def bootstrap_ci(values, seed=7, samples=2000):
    if not values:
        raise ValueError("Bootstrap requires paired run differences")
    positive_int(samples, "samples")
    rng = random.Random(seed)
    estimates = sorted(
        sum(rng.choices(values, k=len(values))) / len(values) for _ in range(samples)
    )
    return {
        "mean": sum(values) / len(values),
        "low": percentile(estimates, 0.025),
        "high": percentile(estimates, 0.975),
        "runs": len(values),
    }


def batches(tasks, agents, seed, arrival, window):
    positive_int(agents, "agents")
    nonnegative(window, "window")
    if window == 0 or arrival not in ("burst", "staggered"):
        raise ValueError("Use a positive window and burst/staggered arrivals")
    shuffled = list(tasks)
    rng = random.Random(seed)
    rng.shuffle(shuffled)
    for begin in range(0, len(shuffled), agents):
        group = shuffled[begin : begin + agents]
        yield tuple(
            replace(
                t,
                arrival_s=(0 if arrival == "burst" else i * window / agents),
                deadline_s=(0 if arrival == "burst" else i * window / agents) + window * 4,
            )
            for i, t in enumerate(group)
        )


def summarize(results):
    task_count = sum(r.metrics["tasks"] for r in results)
    if not task_count:
        raise ValueError("Cannot summarize empty results")
    waits = [w for r in results for w in r.metrics["required_waits_s"]]
    return {
        "mean_completion_s": sum(
            r.metrics["mean_completion_s"] * r.metrics["tasks"] for r in results
        )
        / task_count,
        "p95_completion_s": percentile(
            [v for r in results for v in r.metrics["per_agent_completion_s"].values()], 0.95
        ),
        "p95_required_wait_s": percentile(
            [v for r in results for v in r.metrics["required_waits_s"]], 0.95
        ),
        "mean_required_wait_s": sum(waits) / len(waits) if waits else 0.0,
        "deadline_misses": sum(r.metrics["deadline_misses"] for r in results),
        "speculative_calls": sum(r.metrics["speculative_calls"] for r in results),
        "unused_speculative_calls": sum(r.metrics["unused_speculative_calls"] for r in results),
        "tasks": task_count,
        "calls_started": sum(r.metrics["calls_started"] for r in results),
        "reuse_hits": sum(r.metrics["reuse_hits"] for r in results),
        "modeled_decision_overhead_s": sum(
            r.metrics["modeled_decision_overhead_s"] for r in results
        ),
        "prediction_fallbacks": sum(
            bool(e.get("fallback"))
            for r in results
            for e in r.events
            if e["event"] == "candidate_decided"
        ),
        "deadline_completion_rate": 1
        - sum(r.metrics["deadline_misses"] for r in results)
        / sum(r.metrics["deadline_tasks"] for r in results)
        if sum(r.metrics["deadline_tasks"] for r in results)
        else None,
    }


def run_study(
    data: Path,
    output: Path,
    seeds=(7, 17, 27, 37, 47),
    samples=8,
    frozen_path=None,
    *,
    plots=True,
    bank_paths=(),
    window_s=0.1,
):
    development = load_tasks(json.loads((data / "development.json").read_text()))
    evaluation = load_tasks(json.loads((data / "evaluation.json").read_text()))
    if {t.task_id for t in development} & {t.task_id for t in evaluation}:
        raise ValueError("Development/evaluation IDs overlap")
    if not development or not evaluation:
        raise ValueError("Both splits must be nonempty")
    if any(len({t.task_id for t in group}) != len(group) for group in (development, evaluation)):
        raise ValueError("Duplicate task IDs")
    nonnegative(window_s, "window_s")
    if window_s == 0:
        raise ValueError("window_s must be positive")
    history = HistoryPredictor.fit(development)
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Provide nonempty unique seeds")
    AdmissionConfig(samples=samples)
    from .search import SearchCorpus

    corpus_digest = SearchCorpus.load(data / "corpus.json").digest
    manifest = json.loads((data / "manifest.json").read_text())
    if corpus_digest != manifest["corpus_sha256"]:
        raise ValueError("Manifest does not match corpus")
    for name in ("development", "evaluation"):
        raw = json.loads((data / f"{name}.json").read_text())
        expected = manifest.get("artifacts", {}).get(f"{name}.json")
        if expected and expected != sha256_json(raw):
            raise ValueError(f"Manifest does not match {name} trace")
    from .forecast_bank import BankPredictor

    banks = [BankPredictor(history, path, evaluation) for path in bank_paths]
    if len({bank.name for bank in banks}) != len(banks):
        raise ValueError("Duplicate forecast bank names")
    bank_hashes = {bank.name: bank.digest for bank in banks}
    for bank in banks:
        if bank.bank["config"]["development_sha256"] != sha256_json(dump_tasks(development)):
            raise ValueError("Forecast bank does not match development traces")
    durations = [s.duration_s for t in development for s in t.steps]
    expected_duration = sum(durations) / len(durations) if durations else 0.0
    calibration_costs = []
    if frozen_path:
        previous = json.loads(frozen_path.read_text())
        if previous.get("version") != 2 or previous.get("source_sha256") != source_hashes():
            raise ValueError(
                "Frozen study requires the same source version; regenerate after code changes"
            )
        if previous.get("forecast_bank_sha256", {}) != bank_hashes:
            raise ValueError("Frozen study requires the same forecast banks")
        window_s = previous["base_window_s"]
        if previous["development_sha256"] != sha256_json(dump_tasks(development)) or previous[
            "evaluation_sha256"
        ] != sha256_json(dump_tasks(evaluation)):
            raise ValueError("Frozen configuration does not match input traces")
        reserve = previous["reserve"]
        cfg = AdmissionConfig(**previous["admission"])
        seeds = tuple(previous["seeds"])
        tuning = previous["tuning"]
        if previous["corpus_sha256"] != corpus_digest:
            raise ValueError("Frozen configuration does not match corpus")
        if not seeds or len(set(seeds)) != len(seeds):
            raise ValueError("Frozen seeds must be nonempty and unique")
        FixedReserve(reserve)
    else:
        # Tune reserve and horizon solely on development batches; no held-out readout.
        tuning = []
        tuning_batches = list(batches(development, 4, 3, "burst", window_s))
        calibration_costs = []
        for batch in tuning_batches[:5]:
            probe = Replay(batch, 3, window_s, expected_duration_s=expected_duration).run(
                PredictiveAdmission(
                    history, AdmissionConfig(samples=samples, horizon_s=window_s * 10, overhead_s=0)
                )
            )
            calibration_costs.extend(
                e["decision_wall_s"] for e in probe.events if "decision_wall_s" in e
            )
        # Freeze a conservative millisecond-rounded development p95 before tuning.
        import math

        overhead = max(0.001, math.ceil(percentile(calibration_costs, 0.95) * 1000) / 1000)
        for reserve in (0, 1, 2):
            score = summarize(
                [Replay(b, 3, window_s).run(FixedReserve(reserve)) for b in tuning_batches]
            )
            tuning.append(
                {"kind": "reserve", "value": reserve, "score": score["mean_completion_s"]}
            )
        for horizon in (window_s, window_s * 3, window_s * 10):
            cfg = AdmissionConfig(samples=samples, horizon_s=horizon, overhead_s=overhead)
            score = summarize(
                [
                    Replay(b, 3, window_s, expected_duration_s=expected_duration).run(
                        PredictiveAdmission(history, cfg)
                    )
                    for b in tuning_batches
                ]
            )
            tuning.append(
                {"kind": "horizon", "value": horizon, "score": score["mean_completion_s"]}
            )
        reserve = min((x for x in tuning if x["kind"] == "reserve"), key=lambda x: x["score"])[
            "value"
        ]
        horizon = min((x for x in tuning if x["kind"] == "horizon"), key=lambda x: x["score"])[
            "value"
        ]
        cfg = AdmissionConfig(samples=samples, horizon_s=horizon, overhead_s=overhead)
    frozen = {
        "version": 2,
        "base_window_s": window_s,
        "forecast_bank_sha256": bank_hashes,
        "expected_duration_s": expected_duration,
        "data_agent": manifest.get("agent"),
        "reserve": reserve,
        "admission": asdict(cfg),
        "seeds": seeds,
        "development_sha256": sha256_json(dump_tasks(development)),
        "evaluation_sha256": sha256_json(dump_tasks(evaluation)),
        "corpus_sha256": json.loads((data / "manifest.json").read_text())["corpus_sha256"],
        "tuning": tuning,
        "python": sys.version,
        "configuration_reused_from": str(frozen_path) if frozen_path else None,
        "development_overhead_p95_s": previous.get("development_overhead_p95_s")
        if frozen_path
        else percentile(calibration_costs, 0.95),
        "overhead_calibration": "First five development batches, ten-window horizon, rounded up to milliseconds; frozen across policies/seeds",
        "bootstrap_unit": "whole repeated-seed aggregate; preserves shared-quota batches",
        "ordering": "FIFO for admission comparisons; progress controls with no speculation and current capacity",
    }
    frozen.update(git_state())
    frozen["source_sha256"] = source_hashes()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Study output is not empty; choose a fresh directory")
    output.mkdir(parents=True, exist_ok=True)
    history.save(output / "history.json")
    # Persist before running the first held-out comparison.
    (output / "frozen_config.json").write_text(json.dumps(frozen, indent=2) + "\n")
    policies = (
        "no_speculation",
        "current_capacity",
        "fixed_reserve",
        "usage_forecast",
        "predictive",
        "own_agent_only",
        "progress_order",
        "progress_current_capacity",
    )
    bank_policies = {
        f"{bank.name}_{suffix}": (bank, own)
        for bank in banks
        for suffix, own in (("full", False), ("own", True))
    }
    policies += tuple(bank_policies)
    # Focused one-factor sweeps around the base setting, not an exhaustive Cartesian grid.
    settings = {(agents, 3, window_s, "burst", 0.0) for agents in (1, 2, 4, 8)}
    settings.update((4, capacity, window_s, "burst", 0.0) for capacity in (1, 2, 6))
    settings.update((4, 3, window, "burst", 0.0) for window in (window_s * 0.3, window_s * 3))
    settings.add((4, 3, window_s, "staggered", 0.0))
    settings.update((4, 3, window_s, "burst", error) for error in (0.5, 1.0))
    runs, comparisons = [], []
    with (
        (output / "events.jsonl").open("w") as events,
        (output / "outcomes.jsonl").open("w") as outcomes,
    ):
        for setting_index, (agents, capacity, window, arrival, error) in enumerate(
            sorted(settings)
        ):
            paired = {name: [] for name in policies if name != "no_speculation"}
            for seed in seeds:
                groups = list(batches(evaluation, agents, seed, arrival, window))
                summaries = {}
                for name in policies:
                    predictor = PerturbedPredictor(history, error)
                    factories = {
                        "no_speculation": NoSpeculation,
                        "current_capacity": CurrentCapacity,
                        "fixed_reserve": lambda: FixedReserve(reserve),
                        "usage_forecast": UsageForecastReserve,
                        "predictive": lambda: PredictiveAdmission(
                            predictor, replace(cfg, seed=seed)
                        ),
                        "own_agent_only": lambda: PredictiveAdmission(
                            predictor, replace(cfg, seed=seed), own_only=True
                        ),
                        "progress_order": NoSpeculation,
                        "progress_current_capacity": CurrentCapacity,
                    }
                    if name in bank_policies:
                        bank, own = bank_policies[name]
                        policy = PredictiveAdmission(
                            PerturbedPredictor(bank, error), replace(cfg, seed=seed), own_only=own
                        )
                    else:
                        policy = factories[name]()
                    results = []
                    for batch_index, group in enumerate(groups):
                        replay = Replay(
                            group,
                            capacity,
                            window,
                            required_order="progress" if name.startswith("progress_") else "fifo",
                            expected_duration_s=expected_duration,
                        )
                        result = replay.run(policy)
                        results.append(result)
                        identity = {
                            "setting": setting_index,
                            "seed": seed,
                            "policy": name,
                            "batch": batch_index,
                        }
                        for event in result.events:
                            events.write(json.dumps({**identity, **event}) + "\n")
                        for task in group:
                            outcomes.write(
                                json.dumps(
                                    {
                                        **identity,
                                        "task_id": task.task_id,
                                        "arrival_s": task.arrival_s,
                                        "finish_s": result.metrics["task_finish_s"][task.task_id],
                                        "completion_s": result.metrics["task_finish_s"][
                                            task.task_id
                                        ]
                                        - task.arrival_s,
                                        "wait_s": result.metrics["per_agent_wait_s"][task.task_id],
                                        "deadline_s": task.deadline_s,
                                    }
                                )
                                + "\n"
                            )
                    summary = summarize(results)
                    summary.update(
                        agents=agents,
                        capacity=capacity,
                        window_s=window,
                        arrival=arrival,
                        prediction_error=error,
                        seed=seed,
                        policy=name,
                        setting=setting_index,
                    )
                    runs.append(summary)
                    summaries[name] = summary
                for name in paired:
                    paired[name].append(
                        summaries[name]["mean_completion_s"]
                        - summaries["no_speculation"]["mean_completion_s"]
                    )
            for name, differences in paired.items():
                ci = bootstrap_ci(differences)
                comparisons.append(
                    {
                        "setting": setting_index,
                        "agents": agents,
                        "capacity": capacity,
                        "window_s": window,
                        "arrival": arrival,
                        "prediction_error": error,
                        "policy": name,
                        "delta_completion_s": ci,
                        "regression": ci["mean"] > 0,
                    }
                )
            print(
                f"Completed setting {setting_index + 1}/{len(settings)}: {agents} agents, quota {capacity}/{window}s, {arrival}, error {error}",
                flush=True,
            )
    (output / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
    (output / "comparisons.json").write_text(json.dumps(comparisons, indent=2) + "\n")
    # Pair within setting and seed for every primary metric, including the
    # actual systems-contribution contrast (cross-agent vs own-agent objective).
    metric_comparisons = []
    contrasts = [(name, "no_speculation") for name in policies if name != "no_speculation"]
    contrasts += [
        ("predictive", "own_agent_only"),
        ("predictive", "fixed_reserve"),
        ("predictive", "usage_forecast"),
    ]
    contrasts += [(f"{b.name}_full", f"{b.name}_own") for b in banks]
    contrasts.append(("progress_current_capacity", "current_capacity"))
    contrasts += [
        (f"{bank.name}_full", baseline)
        for bank in banks
        for baseline in ("predictive", "fixed_reserve", "usage_forecast")
    ]
    bank_names = {bank.name for bank in banks}
    for bank in banks:
        backend, context = bank.bank["config"]["backend"], bank.bank["config"]["context"]
        if context != "progress" and f"{backend}_progress" in bank_names:
            contrasts.append((f"{bank.name}_full", f"{backend}_progress_full"))
        if backend == "kev" and f"jev_{context}" in bank_names:
            contrasts.append((f"{bank.name}_full", f"jev_{context}_full"))
    for setting in range(len(settings)):
        indexed = {(r["policy"], r["seed"]): r for r in runs if r["setting"] == setting}
        for policy, baseline in contrasts:
            row = {"setting": setting, "policy": policy, "baseline": baseline, "metrics": {}}
            for metric in (
                "mean_completion_s",
                "p95_completion_s",
                "mean_required_wait_s",
                "p95_required_wait_s",
                "deadline_misses",
                "unused_speculative_calls",
                "modeled_decision_overhead_s",
                "prediction_fallbacks",
            ):
                row["metrics"][metric] = bootstrap_ci(
                    [
                        indexed[policy, seed][metric] - indexed[baseline, seed][metric]
                        for seed in seeds
                    ]
                )
            metric_comparisons.append(row)
    (output / "metric_comparisons.json").write_text(json.dumps(metric_comparisons, indent=2) + "\n")
    # Calibration labels stay in the evaluator, outside prediction inputs.
    calibration_rows = []
    from .forecast_bank import bank_cases

    for identity, observed, agent, labels in bank_cases(evaluation):
        if identity[-1]:
            forecast = history.predict(observed, agent)
            p = forecast.next_probability * forecast.reuse_probability
            calibration_rows.append((p, labels["reuse"]))
    (output / "calibration.json").write_text(
        json.dumps(calibration(calibration_rows), indent=2) + "\n"
    )
    if plots:
        plot_study(comparisons, output, window_s)
        for backend in sorted({b.bank["config"]["backend"] for b in banks}):
            plot_study(
                comparisons,
                output,
                window_s,
                policies=[
                    f"{b.name}_full" for b in banks if b.bank["config"]["backend"] == backend
                ],
                stem=f"sensitivity-{backend}",
            )
    (output / "forecast_calibration.json").write_text(
        json.dumps({b.name: b.calibration for b in banks}, indent=2) + "\n"
    )
    return comparisons


def plot_study(comparisons, output, base_window=0.1, *, policies=None, stem="sensitivity"):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), layout="constrained")
    policies = policies or ("current_capacity", "fixed_reserve", "predictive", "own_agent_only")
    for ax, xfield, title in zip(
        axes,
        ("agents", "window_s", "prediction_error"),
        ("Concurrency", "Quota period", "Prediction error"),
    ):
        for policy in policies:
            rows = [
                r
                for r in comparisons
                if r["policy"] == policy
                and r["capacity"] == 3
                and r["arrival"] == "burst"
                and (xfield == "agents" or r["agents"] == 4)
                and (xfield == "window_s" or r["window_s"] == base_window)
                and (xfield == "prediction_error" or r["prediction_error"] == 0)
            ]
            rows.sort(key=lambda r: r[xfield])
            y = [r["delta_completion_s"]["mean"] for r in rows]
            lo = [max(0, m - r["delta_completion_s"]["low"]) for m, r in zip(y, rows)]
            hi = [max(0, r["delta_completion_s"]["high"] - m) for m, r in zip(y, rows)]
            ax.errorbar([r[xfield] for r in rows], y, yerr=[lo, hi], marker="o", label=policy)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set(title=title, xlabel=xfield, ylabel="Completion delta vs no speculation (s)")
    axes[0].legend(fontsize=7)
    fig.savefig(output / f"{stem}.png", dpi=180)
    fig.savefig(output / f"{stem}.pdf")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("results/study"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 17, 27, 37, 47])
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument(
        "--window-s",
        type=float,
        default=0.1,
        help="Base quota period; use seconds-scale windows for LLM traces",
    )
    parser.add_argument("--forecast-banks", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--frozen-config", type=Path, help="Reuse saved admission, reserve and seeds"
    )
    parser.add_argument("--no-plots", action="store_true", help="Run without optional matplotlib")
    args = parser.parse_args()
    try:
        run_study(
            args.data,
            args.output,
            tuple(args.seeds),
            args.samples,
            args.frozen_config,
            plots=not args.no_plots,
            bank_paths=args.forecast_banks,
            window_s=args.window_s,
        )
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
