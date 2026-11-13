"""Independent fixtures, old-result reproduction, and repeated-stream diagnostic."""

import argparse
import copy
import hashlib
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.admission import AdmissionConfig
from quota_spec.artifacts import write_json
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset
from quota_spec.latency_study import (
    CompactTapeAdmission,
    change_durations,
    overlap_savings,
    perfect_predictions,
    replay,
)
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.speculation_audit import unlimited_reference
from quota_spec.tape_forecasts import TapeBankPredictor, TapeHistory


def tape():
    return {
        "task_id": "hand",
        "question": "hand derived timeline",
        "answer": "answer",
        "steps": [
            {
                "tool": "search",
                "action": "Search[A]",
                "query": "A",
                "actor_duration_s": 0.1,
                "tool_duration_s": 1,
                "window": {
                    "observation_duration_s": 0.1,
                    "hypothetical_duration_s": 0.1,
                    "candidates": [
                        {
                            "rank": 1,
                            "action": "Search[B]",
                            "tool": "search",
                            "query": "B",
                            "duration_s": 1,
                            "eligible": True,
                        }
                    ],
                },
            },
            {
                "tool": "search",
                "action": "Search[B]",
                "query": "B",
                "actor_duration_s": 0.5,
                "tool_duration_s": 1,
                "window": None,
            },
            {
                "tool": "finish",
                "action": "Finish[answer]",
                "query": "answer",
                "actor_duration_s": 0.1,
                "tool_duration_s": 0,
                "window": None,
            },
        ],
    }


def audit(root):
    tapes = load_dataset("results/hotpot-dataset-50")["tapes"]
    residuals = []
    fixtures = []
    examples = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for t in tapes:
            for enabled, policy in [(False, NoSpeculation()), (True, CurrentCapacity())]:
                expected = unlimited_reference(t, enabled)
                actual = FrozenReplay([t], 10000, 1).run(policy)["metrics"]
                residuals.append(abs(expected["completion_s"] - actual["mean_completion_s"]))
                assert expected["cache_hits"] == actual["cache_hits"]
        for parent, actor, generation, next_tool in [
            (4, 3, 1, 4),
            (1, 0.5, 0.2, 4),
            (1, 0.5, 1.5, 4),
        ]:
            t = tape()
            t["steps"][0]["tool_duration_s"] = parent
            w = t["steps"][0]["window"]
            w["observation_duration_s"] = generation / 2
            w["hypothetical_duration_s"] = generation / 2
            w["candidates"] = w["candidates"][:1]
            w["candidates"][0]["duration_s"] = next_tool
            t["steps"][1].update(actor_duration_s=actor, tool_duration_s=next_tool)
            baseline = 0.1 + parent + actor + next_tool + 0.1
            expected = baseline - overlap_savings(parent, actor, generation, next_tool)
            run = FrozenReplay([t], 10000, 1).run(CurrentCapacity())
            assert abs(expected - run["metrics"]["mean_completion_s"]) < 1e-9
            fixtures.append(
                {
                    "parent_tool_s": parent,
                    "next_actor_s": actor,
                    "generation_s": generation,
                    "next_tool_s": next_tool,
                    "hand_none_s": baseline,
                    "hand_spec_s": expected,
                    "run": run,
                }
            )
        prior = [
            json.loads(x)
            for x in Path("results/full-gate-analysis-2026-11-13/rows.jsonl")
            .read_text()
            .splitlines()
        ]
        for capacity, window, workers in [(12, 30, 4), (6, 60, 2)]:
            chosen = []
            for old in prior:
                if (old["capacity"], old["window_s"], old["agents"]) != (capacity, window, workers):
                    continue
                name = old["policy"]
                if name not in ["none", "ideal_post_throughput", "ideal_pipeline_throughput"]:
                    continue
                ordered = list(tapes[20:])
                random.Random(old["seed"]).shuffle(ordered)
                selected = frozenset(tuple(k) for k in old.get("selected", []))
                forced = None if name == "none" else selected
                windows = (
                    frozenset((t, s) for t, s, _ in selected)
                    if name.startswith("ideal_pipeline")
                    else None
                )
                run = FrozenReplay(ordered, capacity, window, max_active_agents=workers).run(
                    NoSpeculation(), forced=forced, generation_windows=windows
                )
                validate(run, ordered, capacity, window, workers)
                assert (
                    abs(old["resource_makespan_s"] - run["metrics"]["resource_makespan_s"]) < 1e-9
                )
                assert abs(old["mean_completion_s"] - run["metrics"]["mean_completion_s"]) < 1e-9
                chosen.append(
                    {
                        "seed": old["seed"],
                        "policy": name,
                        "selected": sorted(selected),
                        "metrics": run["metrics"],
                    }
                )
                write_json(
                    root / f"prior-{capacity}-{window}-{workers}-{old['seed']}-{name}.json", run
                )
            totals = {}
            for name in ["none", "ideal_post_throughput", "ideal_pipeline_throughput"]:
                rows = [r["metrics"] for r in chosen if r["policy"] == name]
                totals[name] = {
                    "mean_resource_s": sum(r["resource_makespan_s"] for r in rows) / len(rows),
                    "mean_questions_s": sum(30 / r["resource_makespan_s"] for r in rows)
                    / len(rows),
                }
            for name, r in totals.items():
                r["elapsed_reduction_percent"] = 100 * (
                    1 - r["mean_resource_s"] / totals["none"]["mean_resource_s"]
                )
                r["throughput_gain_percent"] = 100 * (
                    r["mean_questions_s"] / totals["none"]["mean_questions_s"] - 1
                )
            examples.append(
                {
                    "capacity": capacity,
                    "window_s": window,
                    "workers": workers,
                    "release_on_answer": False,
                    "age": 0,
                    "totals": totals,
                    "rows": chosen,
                }
            )
        equalization = []
        legacy = []
        for t in tapes:
            base = FrozenReplay([t], 10000, 1).run(NoSpeculation())["metrics"]["mean_completion_s"]
            recorded = FrozenReplay([t], 10000, 1).run(CurrentCapacity())["metrics"][
                "mean_completion_s"
            ]
            equal = FrozenReplay(change_durations([t], equalize_matching=True), 10000, 1).run(
                CurrentCapacity()
            )["metrics"]["mean_completion_s"]
            equalization.append(
                {
                    "task_id": t["task_id"],
                    "none_s": base,
                    "recorded_s": recorded,
                    "equalized_spec_s": equal,
                }
            )
            for on in [False, True]:
                f = replay(
                    perfect_predictions([t]),
                    10000,
                    1,
                    1,
                    policy=CurrentCapacity(),
                    age=999,
                    suppress=True,
                    generate_on_reuse=on,
                )["metrics"]
                legacy.append(
                    {
                        "task_id": t["task_id"],
                        "generate_on_reuse": on,
                        "completion_s": f["mean_completion_s"],
                    }
                )
    assert max(residuals) < 1e-8
    write_json(
        root / "arithmetic-audit.json",
        {
            "reference_checks": len(residuals),
            "max_residual_s": max(residuals),
            "fixtures": fixtures,
            "prior_examples": examples,
            "equalized_service_sensitivity": equalization,
            "perfect_trigger_sensitivity": legacy,
            "new_model_calls": 0,
        },
    )


def streams(root):
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for label, factor in [("native", 1), ("scale10", 10)]:
            modified = change_durations(source, scale=factor)
            predictor = TapeBankPredictor(
                TapeHistory(modified[:20]), "results/hotpot-jev-persistent-progress-50/bank.json"
            )
            for repeats in [1, 10]:
                for seed in [248, 249, 250]:
                    # Repeat one shuffled 30-task order, preserving the empirical mixture.
                    order = list(modified[20:])
                    random.Random(seed).shuffle(order)
                    tapes = []
                    for r in range(repeats):
                        for t in order:
                            clone = copy.deepcopy(t)
                            clone["task_id"] += f":repeat-{r}"
                            tapes.append(clone)
                    for cap, window in [(10000, 1), (12, 30), (6, 60)]:
                        for workers in [1, 2, 4, 8]:
                            for release in [False, True]:
                                for name in [
                                    "A_none",
                                    "B_ungated",
                                    "D_jev_all",
                                    "F_perfect_predictor",
                                    "G_zero_overhead",
                                ]:
                                    if name == "A_none":
                                        policy = NoSpeculation()
                                    elif name == "D_jev_all":
                                        policy = CompactTapeAdmission(
                                            predictor,
                                            AdmissionConfig(
                                                samples=16,
                                                horizon_s=max(30, 2 * window),
                                                seed=seed,
                                                nonblocking=True,
                                            ),
                                        )
                                    else:
                                        policy = CurrentCapacity()
                                    oracle = name.startswith(("F_", "G_"))
                                    batch = (
                                        perfect_predictions(
                                            tapes, zero_overhead=name.startswith("G_")
                                        )
                                        if oracle
                                        else tapes
                                    )
                                    run = replay(
                                        batch,
                                        cap,
                                        window,
                                        workers,
                                        policy=policy,
                                        release=release,
                                        age=999 if oracle else 0,
                                        suppress=oracle,
                                        generate_on_reuse=oracle,
                                    )
                                    validate(run, batch, cap, window, workers)
                                    m = run["metrics"]
                                    # Middle 10%-90% finish interval reduces startup and final drain.
                                    finishes = sorted(m["task_finish_s"].values())
                                    lo = len(finishes) // 10
                                    hi = 9 * len(finishes) // 10
                                    interior = (hi - lo) / (finishes[hi] - finishes[lo])
                                    rows.append(
                                        {
                                            "duration": label,
                                            "repeats": repeats,
                                            "seed": seed,
                                            "capacity": cap,
                                            "window_s": window,
                                            "workers": workers,
                                            "release": release,
                                            "policy": name,
                                            "tasks": len(tapes),
                                            "mean_completion_s": m["mean_completion_s"],
                                            "answer_makespan_s": m["answer_makespan_s"],
                                            "resource_makespan_s": m["resource_makespan_s"],
                                            "questions_s": len(tapes) / m["resource_makespan_s"],
                                            "interior_questions_s": interior,
                                            "speculative_calls": m["speculative_calls"],
                                            "unused_speculative_calls": m[
                                                "unused_speculative_calls"
                                            ],
                                        }
                                    )
                print(f"{label}, repeats={repeats}: {len(rows)} stream rows", flush=True)
    write_json(
        root / "repeated-stream.json",
        {
            "warning": "Repeated frozen paths, not fresh evidence or a proof of asymptotic steady state. One shared quota across 30/300 tasks. Interior throughput uses ordered answer finishes 10%-90%; excludes endpoints but may retain quota phase effects.",
            "rows": rows,
        },
    )


def verify_protected(root):
    before = json.loads((root / "protected-before.json").read_text())
    changed = [
        name
        for name, expected in before.items()
        if not Path(name).is_file()
        or hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected
    ]
    write_json(
        root / "protected-verification.json",
        {"protected_files": len(before), "changed_files": changed, "all_unchanged": not changed},
    )
    if changed:
        raise AssertionError(changed)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--streams", action="store_true")
    p.add_argument("--streams-only", action="store_true")
    a = p.parse_args()
    if (a.output / "arithmetic-audit.json").exists():
        raise ValueError("Choose fresh audit root")
    a.output.mkdir(parents=True, exist_ok=True)
    if not a.streams_only:
        audit(a.output)
    if a.streams or a.streams_only:
        streams(a.output)
    if (a.output / "protected-before.json").exists():
        verify_protected(a.output)
