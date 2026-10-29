"""One-command collection, forecast freezing, paired experiments and live QA validation."""

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from .admission import AdmissionConfig, PredictiveAdmission
from .collect_qa import collect, write_json
from .experiments import batches, run_study, source_hashes, summarize
from .forecast_bank import CONTEXTS, prepare
from .models import load_tasks
from .policies import CurrentCapacity, FixedReserve, NoSpeculation, UsageForecastReserve
from .prediction import HistoryPredictor
from .qa import HTTPQA, evaluate
from .replay import Replay, offline_reference
from .search import sha256_json


def report(output):
    from .telemetry import audit_pipeline

    telemetry = audit_pipeline(output)
    write_json(output / "inference_summary.json", telemetry)
    study = output / "study"
    config = json.loads((study / "frozen_config.json").read_text())
    rows = json.loads((study / "metric_comparisons.json").read_text())
    runs = json.loads((study / "runs.json").read_text())
    # Base 4-agent setting is derived from saved configuration, not positional IDs.
    base = next(
        r["setting"]
        for r in runs
        if r["agents"] == 4
        and r["capacity"] == 3
        and r["window_s"] == config["base_window_s"]
        and r["arrival"] == "burst"
        and r["prediction_error"] == 0
    )
    lines = [
        "# Experiment results",
        "",
        f"Workload: {config['data_agent']}.",
        "",
        "Positive latency deltas are regressions. Intervals bootstrap paired whole-seed aggregates; "
        "they describe this workload and seed variation, not general HotpotQA performance.",
        "",
        "## Base setting: four agents, three dispatches per quota window",
        "",
        "| Policy | Comparator | Mean latency delta (s) | 95% interval |",
        "| --- | --- | ---: | --- |",
    ]
    for row in rows:
        if row["setting"] == base:
            value = row["metrics"]["mean_completion_s"]
            lines.append(
                f"| {row['policy']} | {row['baseline']} | {value['mean']:.6f} | "
                f"[{value['low']:.6f}, {value['high']:.6f}] |"
            )
    lines += [
        "",
        "## Actual inference usage",
        "",
        "Counts include retained failed attempts and interrupted live stages. Unknown costs "
        "remain null. Replay does not make new paid requests. Mock calls are fixtures.",
        "",
        "| Stage | Requests | Failures | Cost (USD) | Requests with unknown cost |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            f"| {name} | {r['requests']} | {r['failures']} | {r['cost_usd']} | "
            f"{r['unknown_cost_usd_requests']} |"
            for name, r in telemetry.items()
        ],
        "",
        "## Interpretation and limits",
        "",
        "The predictive-versus-own-agent comparison isolates the cross-agent admission objective. "
        "Predictor banks freeze phase-entry probabilities and charge saved inference latency on every "
        "modeled use. Timing distributions come only from development. Contexts use elapsed=0 in "
        "banks; adaptive live inference uses actual elapsed progress.",
        "",
        "The fixed candidate generator proposes the question and then the top observed title. "
        "It is a documented heuristic, not a reproduction of a learned speculative-action generator. "
        "The bounded rollout approximates completion by the end of the predicted tool chain; "
        "observed final answer-generation time is included in replay outcomes.",
        "",
        "Live model runs are independent and may produce different decisions. Their answer scores "
        "validate the agent integration; they are not paired causal latency comparisons. "
        "Mock answers and probabilities provide no evidence of real model quality.",
        "",
        "## Artifacts",
        "",
        "- `traces/`: resumable per-task records, split traces, QA answers and inference costs.",
        "- `forecasts/`: observed inputs, immutable probabilities, calibration and provider telemetry.",
        "- `study/`: frozen tuning/source hashes, events, outcomes, all metric intervals and plots.",
        "- `reference.json`: privileged development-only lookahead diagnostic.",
        "- `live/`: fresh QA answers, scores, gateway events and inference records.",
        "- `inference_summary.json`: actual calls, failures, tokens and known/unknown costs by stage.",
        "",
    ]
    if (output / "live/summary.json").exists():
        live = json.loads((output / "live/summary.json").read_text())
        lines += [
            "## Live QA",
            "",
            "| Policy | Tasks | Failures | Exact match | F1 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for name, row in live.items():
            lines.append(
                f"| {name} | {row['tasks']} | {row['failures']} | "
                f"{row['exact_match']} | {row['f1']} |"
            )
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")


def run(args):
    from .models import positive_int
    from .quota import FixedWindowQuota

    positive_int(args.count, "count", 2)
    positive_int(args.max_calls, "max_calls")
    positive_int(args.max_requests, "max_requests")
    if args.max_calls > 16:
        raise ValueError("max-calls must be <= 16")
    FixedWindowQuota(3, args.window_s)
    AdmissionConfig(samples=args.samples)
    if not args.seeds or len(set(args.seeds)) != len(args.seeds):
        raise ValueError("Seeds must be nonempty and unique")
    if len(set(args.predictors)) != len(args.predictors) or len(set(args.contexts)) != len(
        args.contexts
    ):
        raise ValueError("Predictors and contexts must be unique")
    if args.live_count < 0:
        raise ValueError("live-count must be nonnegative")
    if not args.no_plots:
        __import__("matplotlib")  # Fail before paid collection if plotting is unavailable.
    qa_model = (
        HTTPQA(
            timeout_s=args.qa_timeout_s,
            input_price=args.qa_input_price,
            output_price=args.qa_output_price,
        )
        if args.backend == "http"
        else None
    )
    from .adapters import JevPredictor, KevPredictor, MockSystemOnePredictor

    constructors = {"jev": JevPredictor, "kev": KevPredictor, "mock": MockSystemOnePredictor}
    preliminary = HistoryPredictor.fit(
        load_tasks(json.loads((args.data / "development.json").read_text()))
    )
    external = [b for b in args.predictors if b != "history"]
    providers = {
        backend: constructors[backend](
            preliminary,
            timeout_s=args.predictor_timeout_s,
            input_usd_per_million=args.predictor_input_price,
            output_usd_per_million=args.predictor_output_price,
        )
        for backend in external
    }

    # Resolve environment defaults before checkpointing; never persist credentials.
    def model_identity(model):
        return (
            {
                field: getattr(model, field, None)
                for field in (
                    "model",
                    "url",
                    "base_url",
                    "model_revision",
                    "timeout_s",
                    "decision_timeout_s",
                    "input_price",
                    "output_price",
                    "token_parameter",
                    "max_tokens",
                )
            }
            if model is not None
            else None
        )

    config = {
        "version": 2,
        "qa_model": model_identity(qa_model),
        "predictor_models": {name: model_identity(model) for name, model in providers.items()},
        "plots": not args.no_plots,
        "data": str(args.data.resolve()),
        "backend": args.backend,
        "count": args.count,
        "max_calls": args.max_calls,
        "predictors": args.predictors,
        "contexts": args.contexts,
        "window_s": args.window_s,
        "seeds": args.seeds,
        "samples": args.samples,
        "live_count": args.live_count,
        "qa_timeout_s": args.qa_timeout_s,
        "predictor_timeout_s": args.predictor_timeout_s,
        "qa_input_price": args.qa_input_price,
        "qa_output_price": args.qa_output_price,
        "predictor_input_price": args.predictor_input_price,
        "predictor_output_price": args.predictor_output_price,
        "source_sha256": source_hashes(),
        "source_data_sha256": {
            name: sha256_json(json.loads((args.data / name).read_text()))
            for name in (
                "development.json",
                "evaluation.json",
                "manifest.json",
                "corpus.json",
                "labels.json",
            )
        },
    }
    output = args.output
    path = output / "pipeline_config.json"
    if args.resume:
        if not path.exists() or json.loads(path.read_text()) != config:
            raise ValueError("Resume requires unchanged inputs, source and experiment settings")
    elif output.exists() and any(output.iterdir()):
        raise ValueError("Pipeline output is not empty; choose a fresh directory or --resume")
    output.mkdir(parents=True, exist_ok=True)
    write_json(path, config)
    state_path = output / "status.json"
    state = (
        json.loads(state_path.read_text())
        if args.resume and state_path.exists()
        else {"completed": []}
    )

    def finished(stage):
        if stage not in state["completed"]:
            state["completed"].append(stage)
        state.pop("failure", None)
        write_json(state_path, state)

    data = output / "traces"
    qa_options = {
        "timeout_s": args.qa_timeout_s,
        "input_price": args.qa_input_price,
        "output_price": args.qa_output_price,
    }
    predictor_options = {
        "timeout_s": args.predictor_timeout_s,
        "input_usd_per_million": args.predictor_input_price,
        "output_usd_per_million": args.predictor_output_price,
    }
    stage = "collection"
    try:
        # Revalidates model/source identity even when all collection tasks are saved.
        asyncio.run(
            collect(
                args.data,
                data,
                backend=args.backend,
                count=args.count,
                max_calls=args.max_calls,
                resume=args.resume and (data / "collection_config.json").exists(),
                model_options=qa_options,
            )
        )
        finished(stage)
        stage = "forecasts"
        if external:
            prepare(
                data,
                output / "forecasts",
                backends=external,
                contexts=args.contexts,
                resume=args.resume,
                execute=True,
                max_requests=args.max_requests,
                predictor_options=predictor_options,
            )
        bank_paths = [
            output / "forecasts" / f"{backend}-{context}.json"
            for backend in external
            for context in args.contexts
        ]
        finished(stage)
        stage = "study"
        if stage not in state["completed"]:
            study = output / "study"
            if study.exists() and any(study.iterdir()):
                # Preserve incomplete artifacts; never overwrite a partial study on resume.
                suffix = 1
                while (output / f"study-interrupted-{suffix}").exists():
                    suffix += 1
                study.rename(output / f"study-interrupted-{suffix}")
            run_study(
                data,
                study,
                seeds=tuple(args.seeds),
                samples=args.samples,
                plots=not args.no_plots,
                bank_paths=bank_paths,
                window_s=args.window_s,
            )
            finished(stage)
        frozen = json.loads((output / "study/frozen_config.json").read_text())
        history = HistoryPredictor.fit(
            load_tasks(json.loads((data / "development.json").read_text()))
        )
        cfg = AdmissionConfig(**frozen["admission"])
        stage = "reference"
        if stage not in state["completed"]:
            development = load_tasks(json.loads((data / "development.json").read_text()))[:8]
            groups = list(batches(development, 4, 7, "burst", args.window_s))
            reference = summarize(
                [
                    offline_reference(
                        Replay(
                            g, 3, args.window_s, expected_duration_s=frozen["expected_duration_s"]
                        )
                    )
                    for g in groups
                ]
            )
            write_json(
                output / "reference.json",
                {
                    "privileged": True,
                    "split": "development",
                    "greedy_not_optimal": True,
                    **reference,
                },
            )
            finished(stage)
        stage = "live"
        if args.live_count and stage not in state["completed"]:
            policies = {
                "no_speculation": NoSpeculation(),
                "current_capacity": CurrentCapacity(),
                "fixed_reserve": FixedReserve(frozen["reserve"]),
                "usage_forecast": UsageForecastReserve(),
                "progress_order": NoSpeculation(),
                "progress_current_capacity": CurrentCapacity(),
                "predictive": PredictiveAdmission(history, cfg),
                "own_agent_only": PredictiveAdmission(history, cfg, own_only=True),
            }
            for backend in external:
                for own in (False, True):
                    name = f"{backend}_{'own' if own else 'full'}"
                    policies[name] = PredictiveAdmission(
                        constructors[backend](history, context="progress", **predictor_options),
                        replace(cfg),
                        own_only=own,
                    )
            live = output / "live"
            if live.exists() and any(live.iterdir()):
                suffix = 1
                while (output / f"live-interrupted-{suffix}").exists():
                    suffix += 1
                live.rename(output / f"live-interrupted-{suffix}")
            summary = asyncio.run(
                evaluate(
                    data,
                    live,
                    backend=args.backend,
                    count=min(args.live_count, args.count // 2),
                    agents=4,
                    max_calls=args.max_calls,
                    capacity=3,
                    window_s=args.window_s,
                    policies=policies,
                    model_options=qa_options,
                    expected_duration_s=frozen["expected_duration_s"],
                )
            )
            if any(row["failures"] or row["predictor_failures"] for row in summary.values()):
                raise ValueError(
                    "Live QA failures recorded; fix access and resume. Partial live run retained"
                )
            finished(stage)
        report(output)
        finished("report")
        return {
            "output": str(output),
            "report": str(output / "REPORT.md"),
            "mock": args.backend == "mock",
            "completed": state["completed"],
        }
    except Exception as exc:
        state["failure"] = {"stage": stage, "type": type(exc).__name__}
        write_json(state_path, state)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("results/pipeline"))
    parser.add_argument("--backend", choices=("mock", "http"), default="mock")
    parser.add_argument(
        "--predictors", nargs="+", choices=("history", "mock", "jev", "kev"), default=["history"]
    )
    parser.add_argument("--contexts", nargs="+", choices=CONTEXTS, default=list(CONTEXTS))
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--max-calls", type=int, default=3)
    parser.add_argument("--window-s", type=float, default=10)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 17, 27, 37, 47])
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--live-count", type=int, default=4)
    parser.add_argument("--max-requests", type=int, default=10000)
    parser.add_argument("--qa-timeout-s", type=float, default=30)
    parser.add_argument("--predictor-timeout-s", type=float, default=2)
    parser.add_argument("--qa-input-price", type=float)
    parser.add_argument("--qa-output-price", type=float)
    parser.add_argument("--predictor-input-price", type=float)
    parser.add_argument("--predictor-output-price", type=float)
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args)
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
