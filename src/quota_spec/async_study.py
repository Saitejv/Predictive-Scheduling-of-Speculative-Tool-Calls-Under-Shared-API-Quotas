"""Test overlapping Jev gates, bounded candidate persistence and worker release.

Default replay behavior remains available as the paired control. Real forecast
latency is always charged; no latency-zero predictor is used in this study.
"""

import argparse
import copy
import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch

from .artifacts import source_hashes, write_json
from .forecast_study import TimedHistory, execute
from .frozen_replay import load_dataset
from .tape_forecasts import digest

VARIANTS = {
    "no_speculation": {"policy_name": "no_speculation"},
    "current_capacity": {"policy_name": "current_capacity"},
    "classic_reserve": {"policy_name": "fixed_reserve"},
    "legacy_jev_full": {"policy_name": "jev_full"},
    "overlap_jev_full": {"policy_name": "jev_full", "nonblocking": True},
    "persistent_jev_own": {
        "policy_name": "jev_own",
        "nonblocking": True,
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "revalidate_reset": True,
    },
    "persistent_jev_full": {
        "policy_name": "jev_full",
        "nonblocking": True,
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "revalidate_reset": True,
    },
    "persistent_history_full": {
        "policy_name": "history_full",
        "nonblocking": True,
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "revalidate_reset": True,
    },
    "persistent_reserve": {
        "policy_name": "fixed_reserve",
        "max_candidate_age": 1,
        "suppress_known_calls": True,
    },
    "hybrid_jev_full": {
        "policy_name": "jev_full",
        "nonblocking": True,
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "revalidate_reset": True,
    },
    "detached_reserve": {
        "policy_name": "fixed_reserve",
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "release_on_answer": True,
    },
    "detached_hybrid": {
        "policy_name": "jev_full",
        "nonblocking": True,
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "revalidate_reset": True,
        "release_on_answer": True,
    },
    "budgeted_reserve": {
        "policy_name": "fixed_reserve",
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "generation_reserve": "tuned",
    },
    "budgeted_hybrid": {
        "policy_name": "jev_full",
        "nonblocking": True,
        "max_candidate_age": 1,
        "suppress_known_calls": True,
        "revalidate_reset": True,
        "generation_reserve": "tuned",
    },
}


def key(capacity, window):
    return f"{capacity}:{window:g}"


def evaluate(tapes, history, bank, variant, choice, **setting):
    options = dict(VARIANTS[variant])
    if variant.startswith("budgeted_"):
        reserve = choice["budgeted_reserve"]
        options["generation_reserve"] = reserve
    elif variant in ["detached_reserve", "detached_hybrid"]:
        reserve = choice["detached_reserve"]
    elif variant in ["persistent_reserve", "hybrid_jev_full"]:
        reserve = choice["persistent_reserve"]
    else:
        reserve = choice["classic_reserve"]
    if variant in ["hybrid_jev_full", "detached_hybrid", "budgeted_hybrid"]:
        options["dispatch_reserve"] = reserve
    row = execute(tapes, history, bank, reserve=reserve, **options, **setting)
    row["variant"] = variant
    return row


def study(
    dataset,
    bank,
    output,
    *,
    settings=None,
    agents=(1, 2, 4, 8),
    seeds=(248, 249, 250, 251, 252),
    variants=None,
    tool_duration_s=None,
    samples=16,
):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    data = load_dataset(dataset)
    dev, evaluation = data["tapes"][:20], data["tapes"][20:]
    training = copy.deepcopy(dev)
    if tool_duration_s is not None:
        for tape in training:
            for step in tape["steps"]:
                if step["tool"] == "search":
                    step["tool_duration_s"] = tool_duration_s
    history = TimedHistory(training)
    saved = json.loads(Path(bank).read_text())
    if (
        saved["config"]["dataset_sha256"]
        != hashlib.sha256((Path(dataset) / "dataset-manifest.json").read_bytes()).hexdigest()
    ):
        raise ValueError("Forecast dataset mismatch")
    if saved["config"].get("max_candidate_age", 0) < 1:
        raise ValueError("Need complete persistent contexts")
    settings = settings or [(c, w) for c in (1, 2, 3, 6, 12) for w in (1, 5, 10, 30, 60)]
    variants = list(variants or VARIANTS)
    if set(variants) - VARIANTS.keys():
        raise ValueError("Unknown variant")
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "version": 1,
            "bank_sha256": digest(saved),
            "settings": settings,
            "agents": agents,
            "seeds": seeds,
            "variants": {name: VARIANTS[name] for name in variants},
            "tool_duration_s": tool_duration_s,
            "samples": samples,
            "development_ids": list(history.training_ids),
            "evaluation_ids": [t["task_id"] for t in evaluation],
            "source": source_hashes(),
            "assumptions": [
                "Same exploratory fixed 20/30 cohort; no new answer-quality result",
                "Jev remains asynchronous with its measured context-specific latency and cost",
                "One extra observed actor action of candidate lifetime; no future trajectory exposed",
                "Required FIFO priority; exact per-task matching; shared quota never refunded",
                "Detached variants release worker at answer, but all background work drains and counts in resource makespan",
                "Unlimited model capacity with fixed recorded service times; background competition for model serving is unmeasured",
                "Reserve selected using development mean completion across worker counts and two order seeds; full 0..capacity range",
            ],
        },
    )
    choices = {}
    scores = []
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("Network during replay")
    ):
        for capacity, window in settings:
            choice = {}
            tuning_variants = ["classic_reserve", "persistent_reserve", "detached_reserve"]
            if any(v.startswith("budgeted_") for v in variants):
                tuning_variants.append("budgeted_reserve")
            for variant in tuning_variants:
                results = []
                for reserve in range(capacity + 1):
                    values = []
                    for count in agents:
                        for seed in seeds[:2]:
                            options = dict(VARIANTS[variant])
                            if variant == "budgeted_reserve":
                                options["generation_reserve"] = reserve
                            row = execute(
                                dev,
                                history,
                                bank,
                                reserve=reserve,
                                **options,
                                agents=count,
                                capacity=capacity,
                                window_s=window,
                                seed=seed,
                                tool_duration_s=tool_duration_s,
                                samples=samples,
                            )
                            values.append(row["mean_completion_s"])
                    results.append((sum(values) / len(values), reserve))
                choice[variant] = min(results)[1]
                scores.append(
                    {
                        "capacity": capacity,
                        "window_s": window,
                        "variant": variant,
                        "scores": results,
                    }
                )
            choices[key(capacity, window)] = choice
    write_json(output / "tuning.json", choices)
    write_json(output / "tuning-scores.json", scores)
    rows = []
    with (
        (output / "rows.jsonl").open("w") as stream,
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network during replay")),
    ):
        for capacity, window in settings:
            for count in agents:
                for seed in seeds:
                    for variant in variants:
                        row = evaluate(
                            evaluation,
                            history,
                            bank,
                            variant,
                            choices[key(capacity, window)],
                            agents=count,
                            capacity=capacity,
                            window_s=window,
                            seed=seed,
                            tool_duration_s=tool_duration_s,
                            samples=samples,
                        )
                        stream.write(json.dumps(row) + "\n")
                        stream.flush()
                        rows.append(row)
            print(f"{capacity}/{window}s: {len(rows)} evaluation replays saved", flush=True)
    groups = {}
    for row in rows:
        groups.setdefault(
            (row["capacity"], row["window_s"], row["agents"], row["variant"]), []
        ).append(row)
    summary = []
    for (capacity, window, count, variant), values in groups.items():
        result = {
            "capacity": capacity,
            "window_s": window,
            "agents": count,
            "variant": variant,
            "seeds": len(values),
        }
        for field in [
            "mean_completion_s",
            "p95_completion_s",
            "resource_makespan_s",
            "answer_makespan_s",
            "throughput_questions_s",
            "mean_required_wait_s",
            "speculative_calls",
            "unused_speculative_calls",
            "cache_hits",
            "inflight_hits",
            "post_action_candidates",
            "post_action_launches",
            "duplicate_candidates_suppressed",
            "logical_forecast_calls",
            "logical_forecast_cost_usd",
            "predictor_overhead_s",
        ]:
            result[field] = sum(v[field] for v in values) / len(values)
        summary.append(result)
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--bank", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--capacities", nargs="+", type=int, default=[1, 2, 3, 6, 12])
    parser.add_argument("--windows", nargs="+", type=float, default=[1, 5, 10, 30, 60])
    parser.add_argument("--agents", nargs="+", type=int, default=[1, 2, 4, 8])
    parser.add_argument("--seeds", nargs="+", type=int, default=[248, 249, 250, 251, 252])
    parser.add_argument("--variants", nargs="+", choices=VARIANTS)
    parser.add_argument("--tool-duration-s", type=float)
    parser.add_argument("--samples", type=int, default=16)
    args = parser.parse_args()
    study(
        args.dataset,
        args.bank,
        args.output,
        settings=[(c, w) for c in args.capacities for w in args.windows],
        agents=args.agents,
        seeds=args.seeds,
        variants=args.variants,
        tool_duration_s=args.tool_duration_s,
        samples=args.samples,
    )


if __name__ == "__main__":
    main()
