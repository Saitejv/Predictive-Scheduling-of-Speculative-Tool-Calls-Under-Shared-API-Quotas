"""Paired quota/reset sweeps on recorded HotpotQA tapes; no network fallback.

Tune reserve/horizon on development, then run disjoint exploratory evaluation.
All policies use the same worker stream, quota, candidate ranks and service times.
"""

import argparse
import copy
import csv
import json
import math
import random
import socket
import time
from pathlib import Path
from unittest.mock import patch

from .admission import AdmissionConfig, PredictiveAdmission
from .artifacts import write_json
from .frozen_replay import FrozenReplay, load_dataset
from .policies import CurrentCapacity, FixedReserve, NoSpeculation, UsageForecastReserve
from .tape_forecasts import TapeBankPredictor, TapeHistory, digest


class TimedHistory(TapeHistory):
    measured_overhead = True


class TimedBank(TapeBankPredictor):
    measured_overhead = True


class ReserveFloor:
    """Cheap reserve before inference and again at asynchronous dispatch."""

    def __init__(self, policy, reserve):
        self.policy, self.dispatch_reserve = policy, reserve
        self.overhead_s, self.last_decision = 0.0, {}

    def admit(self, state):
        self.overhead_s = 0.0
        self.last_decision = {"reserve_blocked": True, "fallback": None}
        if state.quota_remaining <= self.dispatch_reserve:
            return False
        answer = self.policy.admit(state)
        self.overhead_s = self.policy.overhead_s
        self.last_decision = dict(getattr(self.policy, "last_decision", {}))
        return answer


def validate(run, tapes, capacity, window_s, workers):
    if run["metrics"]["answers"] != {t["task_id"]: t["answer"] for t in tapes}:
        raise AssertionError("Frozen answer changed")
    windows, active, peak = {}, 0, 0
    for event in run["events"]:
        kind = event["event"]
        if kind == "search_started":
            index = math.floor(event["time_s"] / window_s)
            windows[index] = windows.get(index, 0) + 1
        active += kind == "task_started"
        active -= kind == "worker_released"
        peak = max(peak, active)
    if any(v > capacity for v in windows.values()) or active != 0 or peak > workers:
        raise AssertionError("Quota or worker accounting failure")
    if any(d.get("forecast", {}).get("fallback") for d in run["decisions"]):
        raise AssertionError("Predictor fallback is not an experimental result")


def execute(
    tapes,
    history,
    bank,
    *,
    policy_name,
    agents,
    capacity,
    window_s,
    seed,
    reserve=1,
    horizon_s=30,
    samples=16,
    tool_duration_s=None,
    nonblocking=False,
    max_candidate_age=0,
    release_on_answer=False,
    suppress_known_calls=False,
    revalidate_reset=False,
    dispatch_reserve=None,
    generation_reserve=None,
):
    ordered = list(tapes)
    random.Random(seed).shuffle(ordered)
    predictor = None
    if policy_name == "no_speculation":
        policy = NoSpeculation()
    elif policy_name == "current_capacity":
        policy = CurrentCapacity()
    elif policy_name == "fixed_reserve":
        policy = FixedReserve(reserve)
    elif policy_name == "usage_reserve":
        policy = UsageForecastReserve()
    else:
        if policy_name.startswith("history"):
            predictor = history
        else:
            predictor = TimedBank(
                history,
                bank,
                parallel="serial" not in policy_name,
                latency_scale=0 if "zero_latency" in policy_name else 1,
            )
        policy = PredictiveAdmission(
            predictor,
            AdmissionConfig(
                samples=samples,
                horizon_s=horizon_s,
                overhead_s=0.001,
                seed=seed,
                nonblocking=nonblocking,
            ),
            own_only="own" in policy_name,
        )
    if dispatch_reserve is not None and isinstance(policy, PredictiveAdmission):
        policy = ReserveFloor(policy, dispatch_reserve)
    started = time.perf_counter()
    run = FrozenReplay(
        ordered,
        capacity,
        window_s,
        max_active_agents=agents,
        tool_duration_s=tool_duration_s,
        max_candidate_age=max_candidate_age,
        release_on_answer=release_on_answer,
        suppress_known_calls=suppress_known_calls,
        revalidate_reset=revalidate_reset,
        generation_reserve=generation_reserve,
    ).run(policy)
    wall = time.perf_counter() - started
    validate(run, ordered, capacity, window_s, agents)
    metrics = run["metrics"]
    return {
        "policy": policy_name,
        "agents": agents,
        "capacity": capacity,
        "window_s": window_s,
        "seed": seed,
        "tool_duration_s": tool_duration_s,
        "reserve": reserve,
        "horizon_s": horizon_s,
        "samples": samples,
        "experiment_wall_s": wall,
        "nonblocking": nonblocking,
        "max_candidate_age": max_candidate_age,
        "release_on_answer": release_on_answer,
        "dispatch_reserve": dispatch_reserve,
        "generation_reserve": generation_reserve,
        **{
            k: v
            for k, v in metrics.items()
            if k not in ("answers", "task_start_s", "task_finish_s", "required_waits_s")
        },
        "throughput_questions_s": len(tapes) / metrics["resource_makespan_s"],
        "decisions": run["decisions"],
        "logical_forecast_calls": getattr(predictor, "logical_calls", 0),
        "logical_forecast_cost_usd": getattr(predictor, "logical_cost_usd", 0),
        "unknown_cost_calls": getattr(predictor, "unknown_cost_calls", 0),
        "decision_cpu_s": sum(
            d.get("forecast", {}).get("decision_wall_s", 0) for d in run["decisions"]
        ),
    }


def study(
    dataset,
    bank,
    output,
    *,
    agents=(1, 2, 4, 8),
    seeds=(248, 249, 250, 251, 252),
    settings=None,
    tool_duration_s=None,
    policies=None,
    tuning=None,
    horizon_s=None,
):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose fresh study output")
    output.mkdir(parents=True)
    data = load_dataset(dataset)
    dev, evaluation = data["tapes"][:20], data["tapes"][20:]
    training = copy.deepcopy(dev)
    if tool_duration_s is not None:
        for tape in training:
            for step in tape["steps"]:
                if step["tool"] == "search":
                    step["tool_duration_s"] = tool_duration_s
    history = TimedHistory(training)
    if set(history.training_ids) & {t["task_id"] for t in evaluation}:
        raise ValueError("Split overlap")
    config = json.loads(Path(bank).read_text())["config"]
    if (
        config["dataset_sha256"]
        != __import__("hashlib")
        .sha256((Path(dataset) / "dataset-manifest.json").read_bytes())
        .hexdigest()
    ):
        raise ValueError("Forecast dataset mismatch")
    settings = settings or [(c, w) for c in (1, 2, 3, 6, 12) for w in (1, 5, 10, 30, 60)]
    policies = policies or [
        "no_speculation",
        "current_capacity",
        "fixed_reserve",
        "usage_reserve",
        "history_own",
        "history_full",
        "jev_own",
        "jev_full",
    ]
    write_json(
        output / "config.json",
        {
            "bank_sha256": digest(json.loads(Path(bank).read_text())),
            "agents": agents,
            "seeds": seeds,
            "settings": settings,
            "policies": policies,
            "tool_duration_s": tool_duration_s,
            "development_ids": list(history.training_ids),
            "evaluation_ids": [t["task_id"] for t in evaluation],
            "source": {
                p.name: __import__("hashlib").sha256(p.read_bytes()).hexdigest()
                for p in Path(__file__).parent.glob("*.py")
            },
            "assumptions": [
                "Exploratory 20/30 split",
                "elapsed=0 finite forecast contexts; actual thinking elapsed conditions history timing",
                "Parallel per-agent predictor calls, max measured response latency per candidate decision unless serial ablation",
                "Fresh logical forecast calls charged per decision; no free warm bank cache",
                "Measured scheduler CPU plus measured forecast latency charged asynchronously",
                "Fixed single-agent model/tool service durations, unlimited provider concurrency",
                "No speculation skips candidate generation; predictive reject still pays started generators",
                "Answer correctness held fixed; no live multi-agent serving claim",
            ],
        },
    )
    tuning_rows = []
    if tuning:
        selected = {
            f"{int(key.split(':')[0])}:{float(key.split(':')[1]):g}": value
            for key, value in json.loads(Path(tuning).read_text()).items()
        }
    else:
        # Choose by mean completion over four worker counts and two development orders.
        selected = {}
        with patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network during replay")
        ):
            for capacity, window in settings:
                options = []
                for reserve in range(capacity + 1):
                    values = []
                    for count in agents:
                        for seed in seeds[:2]:
                            row = execute(
                                dev,
                                history,
                                bank,
                                policy_name="fixed_reserve",
                                agents=count,
                                capacity=capacity,
                                window_s=window,
                                seed=seed,
                                reserve=reserve,
                                tool_duration_s=tool_duration_s,
                            )
                            values.append(row["mean_completion_s"])
                    score = sum(values) / len(values)
                    options.append((score, reserve))
                selected[f"{capacity}:{window:g}"] = {"reserve": min(options)[1], "horizon_s": 30.0}
                tuning_rows.append(
                    {"capacity": capacity, "window_s": window, "reserve_scores": options}
                )
        write_json(output / "tuning-scores.json", tuning_rows)
    write_json(output / "tuning.json", selected)
    n = 0
    with (
        (output / "rows.jsonl").open("w") as stream,
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network during replay")),
    ):
        for capacity, window in settings:
            choice = selected[f"{capacity}:{window:g}"]
            for count in agents:
                for seed in seeds:
                    for policy in policies:
                        row = execute(
                            evaluation,
                            history,
                            bank,
                            policy_name=policy,
                            agents=count,
                            capacity=capacity,
                            window_s=window,
                            seed=seed,
                            reserve=choice["reserve"],
                            horizon_s=choice["horizon_s"] if horizon_s is None else horizon_s,
                            tool_duration_s=tool_duration_s,
                        )
                        stream.write(json.dumps(row) + "\n")
                        stream.flush()
                        n += 1
            print(f"{capacity} calls/{window}s: {n} paired evaluation runs saved", flush=True)
    summarize(output)


def summarize(output):
    output = Path(output)
    rows = [json.loads(line) for line in (output / "rows.jsonl").read_text().splitlines()]
    groups = {}
    for r in rows:
        groups.setdefault((r["capacity"], r["window_s"], r["agents"], r["policy"]), []).append(r)
    aggregate = []
    for (c, w, a, p), values in groups.items():
        row = {"capacity": c, "window_s": w, "agents": a, "policy": p, "seeds": len(values)}
        for field in [
            "mean_completion_s",
            "p95_completion_s",
            "mean_required_wait_s",
            "resource_makespan_s",
            "throughput_questions_s",
            "cache_hits",
            "speculative_calls",
            "unused_speculative_calls",
            "predictor_overhead_s",
            "logical_forecast_calls",
            "logical_forecast_cost_usd",
            "decision_cpu_s",
        ]:
            row[field] = sum(v[field] for v in values) / len(values)
        aggregate.append(row)
    write_json(output / "summary.json", aggregate)
    with (output / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(aggregate[0]))
        writer.writeheader()
        writer.writerows(aggregate)
    return aggregate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset")
    p.add_argument("--bank", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--agents", type=int, nargs="+", default=[1, 2, 4, 8])
    p.add_argument("--seeds", type=int, nargs="+", default=[248, 249, 250, 251, 252])
    p.add_argument("--capacities", type=int, nargs="+", default=[1, 2, 3, 6, 12])
    p.add_argument("--windows", type=float, nargs="+", default=[1, 5, 10, 30, 60])
    p.add_argument("--policies", nargs="+")
    p.add_argument("--tool-duration-s", type=float)
    p.add_argument("--tuning")
    p.add_argument("--horizon-s", type=float)
    a = p.parse_args()
    study(
        a.dataset,
        a.bank,
        a.output,
        agents=a.agents,
        seeds=a.seeds,
        settings=[(c, w) for c in a.capacities for w in a.windows],
        tool_duration_s=a.tool_duration_s,
        policies=a.policies,
        tuning=a.tuning,
        horizon_s=a.horizon_s,
    )


if __name__ == "__main__":
    main()
