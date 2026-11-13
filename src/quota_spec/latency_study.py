"""Offline independent timing audit and synthetic latency experiments.

Never imports a live model client for inference. Frozen Jev contexts and latency
remain native; history service-time distributions follow the synthetic tapes.
"""

import argparse
import copy
import csv
import hashlib
import itertools
import json
import random
import socket
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from .admission import AdmissionConfig, PredictiveAdmission
from .artifacts import source_hashes, write_json
from .forecast_study import validate
from .frozen_replay import FrozenReplay, load_dataset
from .perfect_gate import exact_gates, useful_keys
from .policies import CurrentCapacity, FixedReserve, NoSpeculation
from .tape_forecasts import TapeBankPredictor, TapeHistory

DURATIONS = [
    ("native", 1, None),
    ("scale2", 2, None),
    ("scale5", 5, None),
    ("scale10", 10, None),
    ("fixed1", 1, 1),
    ("fixed2", 1, 2),
    ("fixed5", 1, 5),
    ("fixed10", 1, 10),
]
SETTINGS = [(10000, 1), (12, 5), (3, 10), (12, 30), (6, 60)]
METRICS = [
    "mean_completion_s",
    "p95_completion_s",
    "answer_makespan_s",
    "resource_makespan_s",
    "worker_makespan_s",
    "search_calls",
    "speculative_calls",
    "unused_speculative_calls",
    "cache_hits",
    "inflight_hits",
    "observation_runs",
    "hypothetical_runs",
    "predictor_overhead_s",
    "mean_required_wait_s",
]


def compact_tape_state(state):
    """Drop irrelevant per-task cache entries for completed OTHER episodes.

    TapeBankPredictor/TapeHistory contexts ignore executions. Rollouts reference
    only currently observed agent IDs; task-scoped keys cannot match an inactive
    episode. Spent quota, required queues, active caches, and all forecasts remain
    unchanged. This avoids quadratic cache construction on repeated streams.
    """
    active = {a.task_id for a in state.snapshot.agents}
    return replace(
        state,
        snapshot=replace(
            state.snapshot,
            executions=tuple(e for e in state.snapshot.executions if e.task_id in active),
        ),
    )


class CompactTapeAdmission(PredictiveAdmission):
    """Equivalent bounded tape-forecast admission, with smaller rollout caches."""

    def admit(self, state):
        return super().admit(compact_tape_state(state))


def change_durations(tapes, *, scale=1, fixed=None, equalize_matching=False):
    """Copy tapes; alter required AND eligible speculative Search service times.

    Actor, generation, local tool durations, outputs and original inputs survive.
    The optional equalization isolates overlap from separate measured service
    times for identical required/candidate queries; it is a synthetic diagnostic.
    """
    if scale <= 0 or (fixed is not None and fixed < 0):
        raise ValueError("Invalid Search duration transform")
    tapes = copy.deepcopy(tapes)
    for tape in tapes:
        for index, row in enumerate(tape["steps"]):
            if row["tool"] == "search":
                row["tool_duration_s"] = (
                    fixed if fixed is not None else row["tool_duration_s"] * scale
                )
            if not row["window"]:
                continue
            for c in row["window"]["candidates"]:
                if c["eligible"]:
                    c["duration_s"] = fixed if fixed is not None else c["duration_s"] * scale
                    if equalize_matching:
                        future = next(
                            (
                                s
                                for s in tape["steps"][index + 1 :]
                                if s["tool"] == "search" and s["query"] == c["query"]
                            ),
                            None,
                        )
                        if future is not None:
                            # Future required rows have not been transformed yet.
                            c["duration_s"] = (
                                fixed if fixed is not None else future["tool_duration_s"] * scale
                            )
    return tapes


def perfect_predictions(tapes, *, zero_overhead=False, screen_empty=True, lookahead=1):
    """Replace predictions with the next required Search (privileged future data).

    Generation starts on each authoritative Search demand, including reuse.
    No recursive generation at speculative dispatch, no prediction before the
    first Search, no Lookups prefetched. Each source pays its saved observation
    and hypothetical duration. Nonterminal Search sources all have saved windows.
    Candidate and matching required tool use the SAME service duration/result.
    """
    tapes = copy.deepcopy(tapes)
    if lookahead is not None and (type(lookahead) is not int or lookahead < 1):
        raise ValueError("lookahead must be a positive integer or None for all future Searches")
    for tape in tapes:
        for index, row in enumerate(tape["steps"]):
            future = next((s for s in tape["steps"][index + 1 :] if s["tool"] == "search"), None)
            if row["tool"] == "search" and future is None and row["window"] and not screen_empty:
                row["window"]["candidates"] = []
                if zero_overhead:
                    row["window"]["observation_duration_s"] = 0
                    row["window"]["hypothetical_duration_s"] = 0
                continue
            if row["tool"] != "search" or future is None:
                row["window"] = None
                continue
            if row["window"] is None:
                raise ValueError("No measured generation duration for oracle source")
            targets = {}
            for target in tape["steps"][index + 1 :]:
                if target["tool"] == "search" and target["query"] not in targets:
                    targets[target["query"]] = target
                    if lookahead is not None and len(targets) == lookahead:
                        break
            row["window"] = {
                "observation_duration_s": 0
                if zero_overhead
                else row["window"]["observation_duration_s"],
                "hypothetical_duration_s": 0
                if zero_overhead
                else row["window"]["hypothetical_duration_s"],
                "candidates": [
                    {
                        "rank": rank,
                        "action": target["action"],
                        "tool": "search",
                        "query": target["query"],
                        "eligible": True,
                        "duration_s": target["tool_duration_s"],
                        "result": target.get("tool_result"),
                    }
                    for rank, target in enumerate(targets.values(), 1)
                ],
            }
    return tapes


def perfect_serial_reference(tape, *, zero_overhead=False, generate_on_reuse=True):
    """Independent no-quota scalar recurrence, no replay heap/policies/quota.

    Process generation completions before each required action. Late candidates
    for already requested searches are suppressed. Speculative results stay
    cached, while ordinary required results do not populate that cache.
    """
    steps = tape["steps"]
    now, pending, cache, requested, hits = 0.0, [], {}, set(), 0
    timeline = []
    for i, row in enumerate(steps):
        ready = now + row["actor_duration_s"]
        still_pending = []
        for g, query, duration in sorted(pending):
            if g < ready:
                if query not in requested and query not in cache:
                    cache[query] = g + duration
            else:
                still_pending.append((g, query, duration))
        pending = still_pending
        hit = row["tool"] == "search" and row["query"] in cache
        now = max(ready, cache[row["query"]]) if hit else ready + row["tool_duration_s"]
        hits += hit
        if row["tool"] == "search":
            requested.add(row["query"])
            future = next((s for s in steps[i + 1 :] if s["tool"] == "search"), None)
            if future is not None and (generate_on_reuse or not hit):
                w = row["window"]
                g = (
                    0
                    if zero_overhead
                    else w["observation_duration_s"] + w["hypothetical_duration_s"]
                )
                pending.append((ready + g, future["query"], future["tool_duration_s"]))
        timeline.append(
            {
                "step": i + 1,
                "required_ready_s": ready,
                "step_finished_s": now,
                "cache_hit": bool(hit),
            }
        )
    return {"completion_s": now, "cache_hits": hits, "timeline": timeline}


def overlap_savings(parent_tool, next_actor, generation, next_tool):
    return min(next_tool, max(0, parent_tool + next_actor - generation))


def replay(
    tapes,
    capacity,
    window,
    workers,
    *,
    policy=None,
    forced=None,
    generation_windows=None,
    release=True,
    age=0,
    suppress=False,
    generate_on_reuse=False,
    generation_reserve=None,
    cache_required_results=False,
):
    return FrozenReplay(
        tapes,
        capacity,
        window,
        max_active_agents=workers,
        release_on_answer=release,
        max_candidate_age=age,
        suppress_known_calls=suppress,
        revalidate_reset=True,
        generate_on_reuse=generate_on_reuse,
        generation_reserve=generation_reserve,
        cache_required_results=cache_required_results,
    ).run(policy, forced=forced, generation_windows=generation_windows)


def oracle_gate_search(
    tapes,
    capacity,
    window,
    workers,
    *,
    release,
    age,
    suppress,
    exact_limit=9,
    initial=(),
    generate_on_reuse=False,
):
    """Exact small gate sets; explicitly NONEXACT feasible search for large sets.

    Large sets try none, all, per-task optimum, then forward/reverse additions
    and removals. No claim of globally optimal admission for that branch.
    """
    keys = useful_keys(tapes, max_candidate_age=age, suppress_known_calls=suppress)
    if len(keys) <= exact_limit:
        solved = exact_gates(
            tapes,
            capacity,
            window,
            agents=workers,
            max_candidate_age=age,
            suppress_known_calls=suppress,
            release_on_answer=release,
            max_bits=exact_limit,
            generate_on_reuse=generate_on_reuse,
        )
        return {
            name: {
                "run": solved["winners"][name + "_throughput"]["run"],
                "selected": solved["winners"][name + "_throughput"]["selected"],
                "exact": True,
                "evaluations": solved["schedule_evaluations"],
                "bits": len(keys),
            }
            for name in ["post", "pipeline"]
        }
    winners = {}
    for stage in ["post", "pipeline"]:
        memo = {}

        def evaluate(selected):
            selected = frozenset(selected)
            if selected not in memo:
                allowed = frozenset((t, s) for t, s, _ in selected) if stage == "pipeline" else None
                run = replay(
                    tapes,
                    capacity,
                    window,
                    workers,
                    forced=selected,
                    generation_windows=allowed,
                    release=release,
                    age=age,
                    suppress=suppress,
                    generate_on_reuse=generate_on_reuse,
                )
                m = run["metrics"]
                memo[selected] = (
                    (m["resource_makespan_s"], m["mean_completion_s"], m["speculative_calls"]),
                    run,
                )
            return memo[selected]

        starts = [frozenset(), frozenset(keys), frozenset(initial).intersection(keys)]
        best = min(starts, key=lambda s: evaluate(s)[0])
        for order in [keys, tuple(reversed(keys))]:
            selected = best
            for key in order:
                flipped = selected.symmetric_difference({key})
                if evaluate(flipped)[0] < evaluate(selected)[0]:
                    selected = flipped
            if evaluate(selected)[0] < evaluate(best)[0]:
                best = selected
        winners[stage] = {
            "run": evaluate(best)[1],
            "selected": sorted(best),
            "exact": False,
            "evaluations": len(memo),
            "bits": len(keys),
        }
    return winners


def tune_reserve(dev, capacity, window, workers, *, release, age, suppress, seeds):
    candidates = range(capacity + 1) if capacity < 10000 else [0, capacity]
    values = []
    for reserve in candidates:
        times = []
        for seed in seeds[:2]:
            tapes = list(dev)
            random.Random(seed).shuffle(tapes)
            run = replay(
                tapes,
                capacity,
                window,
                workers,
                policy=FixedReserve(reserve),
                generation_reserve=reserve,
                release=release,
                age=age,
                suppress=suppress,
            )
            times.append(run["metrics"]["resource_makespan_s"])
        values.append({"reserve": reserve, "mean_resource_s": sum(times) / len(times)})
    # Prefer the larger reserve on ties: less unneeded generation/tool work.
    return min(values, key=lambda x: (x["mean_resource_s"], -x["reserve"]))["reserve"], values


def aggregate(rows):
    keys = ["duration", "capacity", "window_s", "workers", "release", "age", "suppress", "policy"]
    groups = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in keys), []).append(r)
    summary = []
    for key, values in groups.items():
        r = dict(zip(keys, key))
        r["orders"] = len(values)
        for field in METRICS + ["logical_forecast_calls", "logical_forecast_cost_usd"]:
            r[field] = sum(v.get(field, 0) for v in values) / len(values)
        r["answer_questions_s"] = sum(v["tasks"] / v["answer_makespan_s"] for v in values) / len(
            values
        )
        r["resource_questions_s"] = sum(
            v["tasks"] / v["resource_makespan_s"] for v in values
        ) / len(values)
        if "exact" in values[0]:
            r["exact"] = all(v["exact"] for v in values)
        summary.append(r)
    index = {tuple(r[k] for k in keys): r for r in summary}
    for r in summary:
        base = index[tuple(r[k] for k in keys[:-1]) + ("A_none",)]
        for metric in ["mean_completion_s", "answer_makespan_s", "resource_makespan_s"]:
            r[metric + "_saved_s"] = base[metric] - r[metric]
            r[metric + "_reduction_pct"] = 100 * (1 - r[metric] / base[metric])
        for metric in ["answer_questions_s", "resource_questions_s"]:
            r[metric + "_gain_pct"] = 100 * (r[metric] / base[metric] - 1)
    return summary


def study(dataset, bank, output, *, seeds=(248, 249, 250), smoke=False):
    root = Path(output)
    if root.exists():
        raise ValueError("Choose a fresh result subdirectory")
    root.mkdir(parents=True)
    source = load_dataset(dataset)["tapes"]
    bank_hash = hashlib.sha256(Path(bank).read_bytes()).hexdigest()
    saved = json.loads(Path(bank).read_text())
    dataset_hash = hashlib.sha256(
        (Path(dataset) / "dataset-manifest.json").read_bytes()
    ).hexdigest()
    if saved["config"]["dataset_sha256"] != dataset_hash:
        raise ValueError("Forecast/dataset mismatch")
    dev, evaluation = source[:20], source[20:]
    durations = DURATIONS[:2] if smoke else DURATIONS
    settings = SETTINGS[:1] if smoke else SETTINGS
    counts = [1, 4] if smoke else [1, 2, 4, 8]
    write_json(
        root / "config.json",
        {
            "durations": durations,
            "settings": settings,
            "workers": counts,
            "seeds": seeds,
            "source": source_hashes(),
            "dataset_sha256": dataset_hash,
            "bank_sha256": bank_hash,
            "development_ids": [t["task_id"] for t in dev],
            "evaluation_ids": [t["task_id"] for t in evaluation],
            "protocol": [
                "All modified Search times are synthetic; same transform applied to required and speculative Searches",
                "Actor/local/generation times and authoritative paths fixed; unlimited serving concurrency beyond Search quota",
                "Jev probabilities and forecast response durations frozen from native timing, elapsed=0; timing history follows transformed development tapes",
                "One persistent quota per full workload. Both answer-release with accounted background work and drain-release tested",
                "Original age0/no duplicate suppression versus age1/duplicate suppression; generation overlaps actor thinking in both",
                "Reserve and generation screen tuned only on 20 development tapes, resource objective, two orders; nonbinding binary enable/disable tuning",
                "E gates exact if at most 9 useful bits; otherwise explicitly best-found feasible schedules, NOT globally perfect",
                "Exact per-task no-quota recorded gate minima provide a rigorous answer-latency ceiling for any recorded-candidate gate at each duration",
                "F perfect-next-Search oracle pays measured source generation and identical required/spec tool duration, generates on reuse, no recursive speculation",
                "G same architecture with zero generation overhead; a conditional upper reference, not unconstrained omniscient dispatch",
            ],
        },
    )
    rows, tuning, arithmetic = [], [], []
    started = time.perf_counter()
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        (root / "rows.jsonl").open("w") as stream,
    ):
        for duration, scale, fixed in durations:
            modified = change_durations(source, scale=scale, fixed=fixed)
            training, test = modified[:20], modified[20:]
            predictor = TapeBankPredictor(TapeHistory(training), bank)
            local_keys = {}
            for age, suppress in [(0, False), (1, True)]:
                selected = []
                for tape in modified:
                    base = replay([tape], 10000, 1, 1, policy=NoSpeculation())["metrics"]
                    solved = exact_gates(
                        [tape],
                        10000,
                        1,
                        agents=1,
                        max_candidate_age=age,
                        suppress_known_calls=suppress,
                        release_on_answer=True,
                    )
                    winner = solved["winners"]["pipeline_latency"]
                    selected.extend(tuple(k) for k in winner["selected"])
                    f = perfect_serial_reference(tape)
                    actual_f = replay(
                        perfect_predictions([tape]),
                        10000,
                        1,
                        1,
                        policy=CurrentCapacity(),
                        age=999,
                        suppress=True,
                        generate_on_reuse=True,
                    )["metrics"]
                    g = perfect_serial_reference(tape, zero_overhead=True)
                    actual_g = replay(
                        perfect_predictions([tape], zero_overhead=True),
                        10000,
                        1,
                        1,
                        policy=CurrentCapacity(),
                        age=999,
                        suppress=True,
                        generate_on_reuse=True,
                    )["metrics"]
                    if (
                        abs(f["completion_s"] - actual_f["mean_completion_s"]) > 1e-8
                        or abs(g["completion_s"] - actual_g["mean_completion_s"]) > 1e-8
                    ):
                        raise AssertionError(
                            ("Perfect recurrence mismatch", duration, tape["task_id"], f, actual_f)
                        )
                    arithmetic.append(
                        {
                            "duration": duration,
                            "task_id": tape["task_id"],
                            "evaluation": tape["task_id"] in {t["task_id"] for t in evaluation},
                            "age": age,
                            "none_s": base["mean_completion_s"],
                            "recorded_gate_exact_mean_s": winner["metrics"]["mean_completion_s"],
                            "perfect_predictor_s": f["completion_s"],
                            "zero_overhead_s": g["completion_s"],
                            "perfect_reference_residual_s": f["completion_s"]
                            - actual_f["mean_completion_s"],
                            "zero_reference_residual_s": g["completion_s"]
                            - actual_g["mean_completion_s"],
                        }
                    )
                local_keys[age] = selected
            for capacity, window in settings:
                for workers, release, (age, suppress) in itertools.product(
                    counts, [True, False], [(0, False), (1, True)]
                ):
                    reserve, evidence = tune_reserve(
                        training,
                        capacity,
                        window,
                        workers,
                        release=release,
                        age=age,
                        suppress=suppress,
                        seeds=seeds,
                    )
                    tuning.append(
                        {
                            "duration": duration,
                            "capacity": capacity,
                            "window_s": window,
                            "workers": workers,
                            "release": release,
                            "age": age,
                            "reserve": reserve,
                            "scores": evidence,
                        }
                    )
                    for seed in seeds:
                        tapes = list(test)
                        random.Random(seed).shuffle(tapes)
                        scenario = {
                            "duration": duration,
                            "capacity": capacity,
                            "window_s": window,
                            "workers": workers,
                            "release": release,
                            "age": age,
                            "suppress": suppress,
                            "seed": seed,
                        }

                        def save(name, run, **extra):
                            validate(run, tapes, capacity, window, workers)
                            m = run["metrics"]
                            if capacity == 10000 and m["mean_required_wait_s"] != 0:
                                raise AssertionError("Nonbinding control has a required wait")
                            row = {
                                **scenario,
                                "policy": name,
                                "tasks": m["tasks"],
                                **{k: m[k] for k in METRICS},
                                **extra,
                            }
                            rows.append(row)
                            stream.write(json.dumps(row) + "\n")

                        save(
                            "A_none",
                            replay(
                                tapes,
                                capacity,
                                window,
                                workers,
                                policy=NoSpeculation(),
                                release=release,
                                age=age,
                                suppress=suppress,
                            ),
                        )
                        save(
                            "B_ungated",
                            replay(
                                tapes,
                                capacity,
                                window,
                                workers,
                                policy=CurrentCapacity(),
                                release=release,
                                age=age,
                                suppress=suppress,
                            ),
                        )
                        save(
                            "C_reserve",
                            replay(
                                tapes,
                                capacity,
                                window,
                                workers,
                                policy=FixedReserve(reserve),
                                generation_reserve=reserve,
                                release=release,
                                age=age,
                                suppress=suppress,
                            ),
                            reserve=reserve,
                        )
                        for own in [True, False]:
                            before_calls, before_cost = (
                                predictor.logical_calls,
                                predictor.logical_cost_usd,
                            )
                            policy = PredictiveAdmission(
                                predictor,
                                AdmissionConfig(
                                    samples=16,
                                    horizon_s=max(30, 2 * window),
                                    seed=seed,
                                    nonblocking=True,
                                ),
                                own_only=own,
                            )
                            run = replay(
                                tapes,
                                capacity,
                                window,
                                workers,
                                policy=policy,
                                release=release,
                                age=age,
                                suppress=suppress,
                            )
                            save(
                                "D_jev_own" if own else "D_jev_all",
                                run,
                                logical_forecast_calls=predictor.logical_calls - before_calls,
                                logical_forecast_cost_usd=predictor.logical_cost_usd - before_cost,
                            )
                        solved = oracle_gate_search(
                            tapes,
                            capacity,
                            window,
                            workers,
                            release=release,
                            age=age,
                            suppress=suppress,
                            initial=local_keys[age],
                            exact_limit=9 if duration == "native" and age == 0 else 0,
                        )
                        for name, winner in solved.items():
                            save(
                                "E_" + name,
                                winner["run"],
                                exact=winner["exact"],
                                selected=winner["selected"],
                                solver_evaluations=winner["evaluations"],
                                oracle_bits=winner["bits"],
                            )
                        for name, zero in [
                            ("F_perfect_predictor", False),
                            ("G_zero_overhead", True),
                        ]:
                            run = replay(
                                perfect_predictions(tapes, zero_overhead=zero),
                                capacity,
                                window,
                                workers,
                                policy=CurrentCapacity(),
                                release=release,
                                age=999,
                                suppress=True,
                                generate_on_reuse=True,
                            )
                            save(name, run)
                    stream.flush()
            print(f"{duration}: {len(rows)} policy runs saved", flush=True)
    summary = aggregate(rows)
    write_json(root / "summary.json", summary)
    with (root / "summary.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in summary for k in r}))
        writer.writeheader()
        writer.writerows(summary)
    write_json(root / "tuning.json", tuning)
    write_json(root / "noquota-exact-arithmetic.json", arithmetic)
    write_json(
        root / "completion.json",
        {
            "complete": True,
            "rows": len(rows),
            "aggregate_rows": len(summary),
            "elapsed_wall_s": time.perf_counter() - started,
            "new_model_calls": 0,
            "network_blocked": True,
            "perfect_recurrence_checks": len(arithmetic) * 2,
        },
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", default="results/hotpot-dataset-50")
    p.add_argument("--bank", default="results/hotpot-jev-persistent-progress-50/bank.json")
    p.add_argument("--output", required=True)
    p.add_argument("--seeds", nargs="+", type=int, default=[248, 249, 250])
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args()
    study(a.dataset, a.bank, a.output, seeds=a.seeds, smoke=a.smoke)
