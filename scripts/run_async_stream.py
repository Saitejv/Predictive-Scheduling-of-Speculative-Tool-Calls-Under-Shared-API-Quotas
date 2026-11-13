"""Longer-stream diagnostic: repeat the fixed evaluation tapes, never new evidence."""

import argparse
import copy
import json
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.artifacts import source_hashes, write_json
from quota_spec.async_study import evaluate, key
from quota_spec.forecast_study import TimedHistory
from quota_spec.frozen_replay import load_dataset
from quota_spec.tape_forecasts import digest


def run(dataset, bank, tuning, output, repeats=10):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh stream output")
    data = load_dataset(dataset)
    history = TimedHistory(data["tapes"][:20])
    tapes = []
    for index in range(repeats):
        for tape in data["tapes"][20:]:
            clone = copy.deepcopy(tape)
            clone["task_id"] = f"{tape['task_id']}:repeat-{index}"
            tapes.append(clone)
    choices = json.loads(Path(tuning).read_text())
    settings = [(6, 5), (12, 5), (12, 30)]
    variants = [
        "no_speculation",
        "classic_reserve",
        "overlap_jev_full",
        "persistent_jev_full",
        "hybrid_jev_full",
        "budgeted_reserve",
        "budgeted_hybrid",
    ]
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "repeats": repeats,
            "tasks": len(tapes),
            "original_evaluation_tasks": 30,
            "settings": settings,
            "agents": [4, 8],
            "seeds": [248, 249, 250],
            "variants": variants,
            "bank_sha256": digest(json.loads(Path(bank).read_text())),
            "tuning_sha256": digest(choices),
            "source": source_hashes(),
            "warning": "Repeated fixed traces and forecast timings, with new per-task IDs/caches and one persistent quota. Not fresh tasks, independent model trials, or measured live serving capacity.",
        },
    )
    rows = []
    with (
        (output / "rows.jsonl").open("w") as stream,
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network during replay")),
    ):
        for capacity, window in settings:
            for count in [4, 8]:
                for seed in [248, 249, 250]:
                    for variant in variants:
                        row = evaluate(
                            tapes,
                            history,
                            bank,
                            variant,
                            choices[key(capacity, window)],
                            agents=count,
                            capacity=capacity,
                            window_s=window,
                            seed=seed,
                        )
                        stream.write(json.dumps(row) + "\n")
                        stream.flush()
                        rows.append(row)
            print(f"{capacity}/{window}s: {len(rows)} long-stream replays saved", flush=True)
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
            "generation_windows_suppressed",
            "observation_runs",
            "hypothetical_runs",
        ]:
            result[field] = sum(v[field] for v in values) / len(values)
        summary.append(result)
    write_json(output / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--bank", required=True)
    parser.add_argument("--tuning", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    run(args.dataset, args.bank, args.tuning, args.output, args.repeats)
