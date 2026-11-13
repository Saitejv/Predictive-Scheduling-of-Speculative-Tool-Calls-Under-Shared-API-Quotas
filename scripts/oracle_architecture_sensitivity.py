"""Distinguish candidate accuracy from source triggers, lifetime and screening."""

import argparse
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.artifacts import write_json
from quota_spec.frozen_replay import load_dataset
from quota_spec.latency_study import DURATIONS, change_durations, perfect_predictions, replay
from quota_spec.perfect_gate import exact_gates
from quota_spec.policies import CurrentCapacity


def run(output):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose fresh output")
    root.mkdir(parents=True)
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    evaluation = {t["task_id"] for t in source[20:]}
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for label, scale, fixed in DURATIONS:
            modified = change_durations(source, scale=scale, fixed=fixed)
            for t in modified:
                gate = exact_gates(
                    [t],
                    10000,
                    1,
                    agents=1,
                    max_candidate_age=999,
                    suppress_known_calls=True,
                    release_on_answer=True,
                )["winners"]["pipeline_latency"]["metrics"]
                rows.append(
                    {
                        "duration": label,
                        "task_id": t["task_id"],
                        "evaluation": t["task_id"] in evaluation,
                        "variant": "E_whole_episode_gate",
                        "metrics": gate,
                    }
                )
                for name, age, reuse, screen in [
                    ("F_original_triggers_lifetime_full_generation", 0, False, False),
                    ("F_extended_triggers_lifetime_full_generation", 1, False, False),
                    ("F_whole_episode_original_triggers_full_generation", 999, False, False),
                    ("F_reuse_triggers_full_generation", 999, True, False),
                    ("F_reuse_triggers_empty_source_screen", 999, True, True),
                ]:
                    run = replay(
                        perfect_predictions([t], screen_empty=screen),
                        10000,
                        1,
                        1,
                        policy=CurrentCapacity(),
                        release=True,
                        age=age,
                        suppress=True,
                        generate_on_reuse=reuse,
                    )
                    rows.append(
                        {
                            "duration": label,
                            "task_id": t["task_id"],
                            "evaluation": t["task_id"] in evaluation,
                            "variant": name,
                            "metrics": run["metrics"],
                        }
                    )
            print(label, len(rows), "architecture rows", flush=True)
    write_json(root / "rows.json", rows)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "new_model_calls": 0,
            "warning": "No-quota architecture sensitivity, per-task resource time is not additive when workers release at answer. All modified durations synthetic. Full generation also pays terminal windows that correctly predict no further Search.",
        },
    )


def lookahead_bound(output):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose fresh output")
    root.mkdir(parents=True)
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    evaluation = {t["task_id"] for t in source[20:]}
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for label, scale, fixed in DURATIONS:
            for t in change_durations(source, scale=scale, fixed=fixed):
                for zero in [False, True]:
                    run = replay(
                        perfect_predictions(
                            [t], lookahead=None, zero_overhead=zero, screen_empty=False
                        ),
                        10000,
                        1,
                        1,
                        policy=CurrentCapacity(),
                        release=True,
                        age=999,
                        suppress=True,
                        generate_on_reuse=True,
                    )
                    rows.append(
                        {
                            "duration": label,
                            "task_id": t["task_id"],
                            "evaluation": t["task_id"] in evaluation,
                            "zero_overhead": zero,
                            "metrics": run["metrics"],
                        }
                    )
    write_json(root / "rows.json", rows)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "new_model_calls": 0,
            "warning": "Stronger full-lookahead oracle, not the requested next-Search predictor. One source generation can reveal ALL distinct later Search queries at its saved top-three generation duration. Retains tool costs; no new generation at speculative dispatch. Optimistic architecture reference, not demonstrated predictor capability or a universal upper bound on arbitrary scheduling.",
        },
    )


def retention_controls(output, *, cache_required_results=False):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose fresh output")
    root.mkdir(parents=True)
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    evaluation = {t["task_id"] for t in source[20:]}
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for label, scale, fixed in DURATIONS:
            for t in change_durations(source, scale=scale, fixed=fixed):
                for age in [0, 1, 999] if cache_required_results else [0, 1]:
                    for suppress in [False, True]:
                        solved = exact_gates(
                            [t],
                            10000,
                            1,
                            agents=1,
                            max_candidate_age=age,
                            suppress_known_calls=suppress,
                            release_on_answer=True,
                            cache_required_results=cache_required_results,
                        )
                        rows.append(
                            {
                                "duration": label,
                                "task_id": t["task_id"],
                                "evaluation": t["task_id"] in evaluation,
                                "age": age,
                                "cache_required_results": cache_required_results,
                                "suppress": suppress,
                                "exact_gate_latency_s": solved["winners"]["pipeline_latency"][
                                    "metrics"
                                ]["mean_completion_s"],
                            }
                        )
    write_json(root / "rows.json", rows)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "new_model_calls": 0,
            "protocol": "Exact per-task no-quota retention by duplicate-suppression factorial. Suppression skips every historically requested Search, including completed ordinary results which are not in the speculative cache.",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--lookahead-bound", action="store_true")
    p.add_argument("--retention-controls", action="store_true")
    p.add_argument("--common-cache", action="store_true")
    a = p.parse_args()
    if a.lookahead_bound:
        lookahead_bound(a.output)
    elif a.retention_controls:
        retention_controls(a.output, cache_required_results=a.common_cache)
    else:
        run(a.output)
