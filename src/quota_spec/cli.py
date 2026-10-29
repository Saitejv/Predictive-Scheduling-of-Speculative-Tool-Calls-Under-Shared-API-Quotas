"""Run a repeatable baseline comparison and retain inputs and event logs."""

import argparse
import json
import sys
from pathlib import Path

from .admission import AdmissionConfig, PredictiveAdmission
from .models import load_tasks
from .policies import CurrentCapacity, FixedReserve, NoSpeculation, UsageForecastReserve
from .prediction import HistoryPredictor
from .provenance import git_state
from .replay import Replay, offline_reference
from .workload import dump_tasks, synthetic_tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, choices=(1, 2, 4, 8), default=4)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--capacity", type=int, default=3)
    parser.add_argument("--window-s", type=float, default=10)
    parser.add_argument(
        "--expected-duration-s",
        type=float,
        default=1.0,
        help="Initial observable tool duration estimate",
    )
    parser.add_argument("--reserve", type=int, default=1)
    parser.add_argument("--trace", type=Path, help="JSON task list; replaces synthetic input")
    parser.add_argument("--output", type=Path, default=Path("results/demo"))
    parser.add_argument(
        "--skip-reference", action="store_true", help="Skip expensive offline lookahead"
    )
    parser.add_argument(
        "--history-trace", type=Path, help="Disjoint development tasks for history fitting"
    )
    parser.add_argument("--predictor", choices=("history", "jev", "kev", "mock"), default="history")
    parser.add_argument("--model", help="Model name; defaults to JEV_MODEL / KEV_MODEL")
    parser.add_argument("--model-base-url", help="Override model endpoint, without credentials")
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument("--decision-timeout-s", type=float, default=5.0)
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    parser.add_argument(
        "--context",
        choices=("task", "history", "progress", "no_history", "no_progress"),
        default="progress",
    )
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--horizon-s", type=float, default=30)
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--epsilon", type=float, default=0.05)
    parser.add_argument(
        "--overhead-s", type=float, default=0.001, help="Frozen modeled decision latency"
    )
    parser.add_argument("--required-order", choices=("fifo", "progress"), default="fifo")
    args = parser.parse_args()
    predictor = None
    try:
        tasks = (
            load_tasks(json.loads(args.trace.read_text()))
            if args.trace
            else synthetic_tasks(args.agents, args.seed)
        )
        replay = Replay(
            tasks,
            args.capacity,
            args.window_s,
            required_order=args.required_order,
            expected_duration_s=args.expected_duration_s,
        )
        policies = {
            "no_speculation": NoSpeculation(),
            "current_capacity": CurrentCapacity(),
            "fixed_reserve": FixedReserve(args.reserve),
            "usage_forecast": UsageForecastReserve(),
        }
        admission = AdmissionConfig(
            args.samples, args.horizon_s, args.max_calls, args.epsilon, args.overhead_s, args.seed
        )
        if args.history_trace:
            development = load_tasks(json.loads(args.history_trace.read_text()))
            if {t.task_id for t in tasks} & {t.task_id for t in development}:
                raise ValueError("Development/evaluation task IDs overlap")
            history = HistoryPredictor.fit(development)
            predictor = history
            if args.predictor != "history":
                from .adapters import JevPredictor, KevPredictor, MockSystemOnePredictor

                options = dict(
                    context=args.context,
                    timeout_s=args.timeout_s,
                    decision_timeout_s=args.decision_timeout_s,
                    input_usd_per_million=args.input_usd_per_million,
                    output_usd_per_million=args.output_usd_per_million,
                )
                if args.predictor != "mock":
                    options.update(base_url=args.model_base_url, model=args.model)
                predictor = {
                    "jev": JevPredictor,
                    "kev": KevPredictor,
                    "mock": MockSystemOnePredictor,
                }[args.predictor](history, **options)
            policies["predictive"] = PredictiveAdmission(predictor, admission)
            policies["own_agent_only"] = PredictiveAdmission(predictor, admission, own_only=True)
        elif args.predictor != "history":
            raise ValueError("Model predictors require --history-trace for timing distributions")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "trace.json").write_text(json.dumps(dump_tasks(tasks), indent=2) + "\n")
    config = {
        "schema_version": 1,
        "seed": args.seed,
        "capacity": args.capacity,
        "window_s": args.window_s,
        "reserve": args.reserve,
        "input": str(args.trace) if args.trace else "synthetic",
        "tasks": len(tasks),
        "python": sys.version,
        **git_state(),
        "skip_reference": args.skip_reference,
    }
    config.update(
        expected_duration_s=args.expected_duration_s,
        required_order=args.required_order,
        predictor=args.predictor,
        context=args.context,
        history_trace=str(args.history_trace) if args.history_trace else None,
        admission=vars(admission),
        model=getattr(predictor, "model", None),
        timeout_s=args.timeout_s,
        decision_timeout_s=args.decision_timeout_s,
        input_usd_per_million=args.input_usd_per_million,
        output_usd_per_million=args.output_usd_per_million,
        mock=args.predictor == "mock",
        overhead_mode="measured" if args.predictor in ("jev", "kev") else "frozen",
    )
    if args.history_trace:
        history.save(args.output / "history.json")
    (args.output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    summary = {}
    print(f"{'policy':<24} {'mean (s)':>10} {'p95 (s)':>10} {'wait (s)':>10} {'unused':>8}")
    names = list(policies) + ([] if args.skip_reference else ["offline_reference"])
    for name in names:
        record_start = len(getattr(predictor, "records", []))
        result = (
            offline_reference(replay) if name == "offline_reference" else replay.run(policies[name])
        )
        records = getattr(predictor, "records", [])[record_start:]
        for record in records:
            record["policy"] = name
        result.metrics["inference_calls"] = len(records)
        result.metrics["inference_failures"] = sum(r["failure"] is not None for r in records)
        result.metrics["inference_latency_s"] = sum(r["latency_s"] for r in records)
        result.metrics["inference_cost_usd"] = (
            sum(r["cost_usd"] for r in records)
            if records and all(r["cost_usd"] is not None for r in records)
            else None
        )
        summary[name] = result.metrics
        with (args.output / f"{name}.jsonl").open("w") as handle:
            for event in result.events:
                handle.write(json.dumps(event) + "\n")
        m = result.metrics
        print(
            f"{name:<24} {m['mean_completion_s']:>10.3f} {m['p95_completion_s']:>10.3f} "
            f"{m['mean_required_wait_s']:>10.3f} {m['unused_speculative_calls']:>8}"
        )
    (args.output / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    if args.history_trace and hasattr(predictor, "records"):
        (args.output / "inference.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in predictor.records)
        )
    print(f"Artifacts: {args.output.resolve()}")


if __name__ == "__main__":
    main()
