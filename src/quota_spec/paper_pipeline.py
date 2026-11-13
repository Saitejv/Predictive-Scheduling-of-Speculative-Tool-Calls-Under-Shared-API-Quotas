"""Canonical paper workload -> frozen forecasts -> paired multi-agent quota study.

No paid calls unless --backend http or --predictors jev is explicitly selected.
The existing legacy local-BM25 pipeline is not used by this command.
"""

import argparse
import json
from pathlib import Path

from .collect_qa import write_json
from .experiments import run_study, source_hashes
from .forecast_bank import CONTEXTS
from .forecast_bank import prepare as prepare_forecasts
from .paper import REVISION
from .paper_collect import collect
from .search import sha256_json
from .telemetry import summarize_inference


def report(output):
    collection = output / "traces"
    records = [
        json.loads(line) for line in (collection / "inference.jsonl").read_text().splitlines()
    ]
    forecasts = []
    for path in (output / "forecasts").glob("*.json"):
        bank = json.loads(path.read_text())
        forecasts.extend(row["telemetry"] for row in bank.get("responses", {}).values())
        forecasts.extend(row["telemetry"] for row in bank.get("failed_attempts", []))
    usage = {
        role: summarize_inference(r for r in records if r["role"] == role)
        for role in ("actor", "speculative_actor", "observation_speculator")
    }
    usage["forecasts"] = summarize_inference(forecasts)
    write_json(output / "inference_summary.json", usage)
    tasks = [json.loads(p.read_text()) for p in (collection / "tasks").glob("*.json")]
    outcomes = [
        {"task_id": r["task_id"], "split": r["split"], "em": r["em"], "f1": r["f1"]}
        for r in tasks
        if r.get("failure") is None
    ]
    write_json(output / "qa_outcomes.json", outcomes)
    lines = [
        "# Canonical HotpotQA shared-quota study",
        "",
        "The same recorded ReAct actions, observation predictions, next-action candidates, "
        "model latencies and tool durations are replayed under every admission policy. "
        "Only Search spends quota. Lookup/Finish remain local and uncached.",
        "",
        "The primary causal comparison is each frozen predictor's full admission against "
        "its own-agent-only ablation. Both share predictions, timing distributions, samples, "
        "overhead and the global deadline-risk guard; only the gain objective differs.",
        "",
        "| Inference role | Requests | Failures | USD |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {role} | {u['requests']} | {u['failures']} | {u['cost_usd']} |"
        for role, u in usage.items()
    ]
    config = json.loads((output / "study/frozen_config.json").read_text())
    runs = json.loads((output / "study/runs.json").read_text())
    base = next(
        r["setting"]
        for r in runs
        if r["agents"] == 4
        and r["capacity"] == 3
        and r["window_s"] == config["base_window_s"]
        and r["arrival"] == "burst"
        and r["prediction_error"] == 0
    )
    comparisons = json.loads((output / "study/metric_comparisons.json").read_text())
    lines += [
        "",
        "## Base setting: paired mean completion deltas",
        "",
        "Positive deltas mean slower completion. Intervals describe repeated task orders, "
        "not general HotpotQA performance.",
        "",
        "| Policy | Comparator | Delta (s) | 95% interval |",
        "| --- | --- | ---: | --- |",
    ]
    for row in comparisons:
        if row["setting"] == base:
            value = row["metrics"]["mean_completion_s"]
            lines.append(
                f"| {row['policy']} | {row['baseline']} | {value['mean']:.6f} | "
                f"[{value['low']:.6f}, {value['high']:.6f}] |"
            )
    lines += [
        "",
        "## Interpretation",
        "",
        "This is dependency-aware replay of real or explicitly synthetic collected traces, "
        "not an independent live-agent latency measurement. Collection executes branches "
        "serially for measurement; replay releases each proposal from the preceding real "
        "tool's dispatch plus observation-generation and speculative-actor inference time. "
        "Correct Search reuse moves later dependencies; it never exposes a speculative "
        "observation to the authoritative actor.",
        "",
        "Top-one is fixed across policies. Non-Search predictions are logged but do not "
        "request search quota. Forecast banks use bounded phase-entry/running contexts "
        "with elapsed=0; online replay never reads labels or uncompleted tool results. "
        "All predictor timing distributions and tuning come from development tasks. "
        "Unknown costs stay null. Mock results are fixtures, not performance evidence.",
        "",
        "Artifacts: `traces/` (raw authoritative/hypothetical branches, normalized actions, "
        "hashes and model timing); `forecasts/` (frozen probabilities); `study/` (paired "
        "events, outcomes, tuning and comparisons); `qa_outcomes.json` (answer scores).",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines))


def run(args):
    if args.predictors == ["history"]:
        external = []
    else:
        external = [name for name in args.predictors if name != "history"]
    config = {
        "version": 1,
        "source_sha256": source_hashes(),
        "backend": args.backend,
        "actor": args.actor,
        "speculator": args.speculator,
        "count": args.count,
        "predictors": args.predictors,
        "contexts": args.contexts,
        "seeds": args.seeds,
        "samples": args.samples,
        "window_s": args.window_s,
        "plots": not args.no_plots,
        "predictor_timeout_s": args.predictor_timeout_s,
        "source": str(args.source.resolve()),
        "width": 1,
    }
    # Validate settings/providers before collection can make paid calls.
    from .adapters import JevPredictor, MockSystemOnePredictor
    from .admission import AdmissionConfig
    from .models import Task
    from .prediction import HistoryPredictor
    from .quota import FixedWindowQuota

    AdmissionConfig(samples=args.samples)
    FixedWindowQuota(3, args.window_s)
    if not 2 <= args.count <= 20 or not args.seeds or len(set(args.seeds)) != len(args.seeds):
        raise ValueError("Use 2..20 tasks and nonempty unique seeds")
    if len(set(args.predictors)) != len(args.predictors) or len(set(args.contexts)) != len(
        args.contexts
    ):
        raise ValueError("Predictors/contexts must be unique")
    if not args.no_plots:
        __import__("matplotlib")
    for backend in external:
        provider = {"jev": JevPredictor, "mock": MockSystemOnePredictor}[backend](
            HistoryPredictor.fit((Task("configuration_probe", 0, ()),)),
            timeout_s=args.predictor_timeout_s,
        )
        config.setdefault("providers", {})[backend] = {
            "model": provider.model,
            "base_url": provider.base_url,
            "input_price": provider.input_price,
            "output_price": provider.output_price,
        }
    output = args.output
    path = output / "pipeline_config.json"
    if args.resume:
        if not path.exists() or json.loads(path.read_text()) != config:
            raise ValueError("Resume requires unchanged source/configuration")
    elif output.exists() and any(output.iterdir()):
        raise ValueError("Choose a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    write_json(path, config)
    status_path = output / "status.json"
    status = (
        json.loads(status_path.read_text())
        if args.resume and status_path.exists()
        else {"completed": []}
    )
    stage = "collection"
    try:
        collect(
            args.source,
            output / "traces",
            count=args.count,
            actor=args.actor,
            speculator=args.speculator,
            backend=args.backend,
            max_requests=args.max_requests,
            resume=args.resume and (output / "traces/collection_config.json").exists(),
        )
        if stage not in status["completed"]:
            status["completed"].append(stage)
        write_json(status_path, status)
        stage = "forecasts"
        paths = []
        if external:
            result = prepare_forecasts(
                output / "traces",
                output / "forecasts",
                backends=external,
                contexts=args.contexts,
                execute=True,
                resume=args.resume,
                max_requests=args.max_forecast_requests,
                predictor_options={"timeout_s": args.predictor_timeout_s},
            )
            paths = [Path(path) for path in result["banks"]]
        if stage not in status["completed"]:
            status["completed"].append(stage)
        write_json(status_path, status)
        stage = "study"
        if stage not in status["completed"]:
            study = output / "study"
            if study.exists() and any(study.iterdir()):
                raise ValueError("Incomplete study retained; choose a new study/output directory")
            run_study(
                output / "traces",
                study,
                seeds=tuple(args.seeds),
                samples=args.samples,
                bank_paths=paths,
                plots=not args.no_plots,
                window_s=args.window_s,
            )
            status["completed"].append(stage)
        report(output)
        status.pop("failure", None)
        if "report" not in status["completed"]:
            status["completed"].append("report")
        write_json(status_path, status)
        return {
            "output": str(output),
            "completed": status["completed"],
            "mock": args.backend == "mock",
            "config_sha256": sha256_json(config),
        }
    except Exception as exc:
        status["failure"] = {"stage": stage, "type": type(exc).__name__}
        write_json(status_path, status)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("data/raw/speculative-action") / REVISION
    )
    parser.add_argument("--output", type=Path, default=Path("results/paper-study"))
    parser.add_argument("--backend", choices=("mock", "http"), default="mock")
    parser.add_argument("--actor", default="google/gemini-2.5-flash")
    parser.add_argument("--speculator", default="google/gemini-2.5-flash")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument(
        "--predictors", nargs="+", choices=("history", "mock", "jev"), default=["history"]
    )
    parser.add_argument("--contexts", nargs="+", choices=CONTEXTS, default=list(CONTEXTS))
    parser.add_argument("--seeds", nargs="+", type=int, default=[7, 17, 27])
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--window-s", type=float, default=10)
    parser.add_argument("--predictor-timeout-s", type=float, default=5)
    parser.add_argument("--max-requests", type=int, default=512)
    parser.add_argument("--max-forecast-requests", type=int, default=4000)
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--resume", action="store_true")
    print(json.dumps(run(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
