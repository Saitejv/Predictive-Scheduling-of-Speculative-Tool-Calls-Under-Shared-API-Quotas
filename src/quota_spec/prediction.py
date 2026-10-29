"""Bounded observed-state forecasts; training labels are development-only."""

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Protocol

from .models import AgentState, Observation, Task, nonnegative


@dataclass(frozen=True)
class Forecast:
    reuse_probability: float
    next_probability: float
    delays_s: tuple[float, ...]
    durations_s: tuple[float, ...]
    continue_probability: float

    def __post_init__(self):
        for p in (self.reuse_probability, self.next_probability, self.continue_probability):
            nonnegative(p, "probability")
            if p > 1:
                raise ValueError("Forecast probabilities must be finite and in [0, 1]")
        for values in (self.delays_s, self.durations_s):
            if not 1 <= len(values) <= 128:
                raise ValueError("Forecast distributions require 1..128 nonnegative finite values")
            for value in values:
                nonnegative(value, "forecast timing")


class Predictor(Protocol):
    def predict(self, state: Observation, agent: AgentState) -> Forecast: ...


class HistoryPredictor:
    """Empirical progress-conditioned transitions with Laplace smoothing."""

    def __init__(self, rows: dict[int, list[dict]], training_ids=()):
        self.rows = rows
        self.training_ids = tuple(sorted(training_ids))
        if not rows or not any(rows.values()):
            raise ValueError("History requires development examples")
        self.last_record = {}

    @classmethod
    def fit(cls, tasks: tuple[Task, ...]):
        rows: dict[int, list[dict]] = {}
        for task in tasks:
            for index, step in enumerate(task.steps):
                rows.setdefault(index, []).append(
                    {
                        "delay": step.think_s,
                        "duration": step.duration_s,
                        "reuse": step.candidate == step.required,
                        "continues": index + 1 < len(task.steps),
                        "has_next": True,
                    }
                )
            if task.final_think_s or task.final_candidate or not task.steps:
                rows.setdefault(len(task.steps), []).append(
                    {
                        "delay": task.final_think_s,
                        "duration": 0,
                        "reuse": False,
                        "continues": False,
                        "has_next": False,
                    }
                )
        return cls(rows, (t.task_id for t in tasks))

    def predict(self, state: Observation, agent: AgentState) -> Forecast:
        pending = agent.phase in ("running", "queued")
        index = agent.completed_calls + int(pending)
        examples = self.rows.get(index)
        next_probability = 1.0
        if pending:
            current = self.rows.get(agent.completed_calls, [])
            next_probability = (sum(x["continues"] for x in current) + 1) / (len(current) + 2)
        if not examples:
            # Beyond observed development support: conservatively predict another call.
            examples = [row for rows in self.rows.values() for row in rows]
        all_examples = examples
        if not pending:
            next_probability = (
                (sum(x.get("has_next", True) for x in all_examples) + 1) / (len(all_examples) + 2)
                if any(not x.get("has_next", True) for x in all_examples)
                else 1.0
            )
        examples = [x for x in examples if x.get("has_next", True)]
        if not examples:
            examples = [
                row for rows in self.rows.values() for row in rows if row.get("has_next", True)
            ] or all_examples
        # Subsample across all development tasks, rather than biasing toward the first 128.
        n = len(examples)
        timings = [examples[min(n - 1, i * n // min(n, 128))] for i in range(min(n, 128))]
        return Forecast(
            (sum(x["reuse"] for x in examples) + 1) / (n + 2),
            next_probability,
            tuple(x["delay"] for x in timings),
            tuple(x["duration"] for x in timings),
            (sum(x["continues"] for x in examples) + 1) / (n + 2),
        )

    def save(self, path):
        path.write_text(
            json.dumps(
                {"version": 1, "training_ids": self.training_ids, "rows": self.rows}, indent=2
            )
            + "\n"
        )

    @classmethod
    def load(cls, path):
        data = json.loads(path.read_text())
        if data["version"] != 1:
            raise ValueError("Unsupported history version")
        return cls({int(k): v for k, v in data["rows"].items()}, data["training_ids"])


class PerturbedPredictor:
    """Controlled probability error; never consults evaluation labels."""

    def __init__(self, base: Predictor, error: float):
        if not 0 <= error <= 1:
            raise ValueError("error must be in [0, 1]")
        self.base, self.error = base, error

    @property
    def measured_overhead(self):
        return getattr(self.base, "measured_overhead", False)

    @property
    def decision_overhead_s(self):
        return getattr(self.base, "decision_overhead_s", 0.0)

    def begin_decision(self):
        if hasattr(self.base, "begin_decision"):
            self.base.begin_decision()

    def end_decision(self):
        if hasattr(self.base, "end_decision"):
            self.base.end_decision()

    def predict(self, state, agent):
        p = self.base.predict(state, agent)
        return replace(
            p,
            reuse_probability=(1 - self.error) * p.reuse_probability
            + self.error * (1 - p.reuse_probability),
        )


def decision_seed(state: Observation, seed: int) -> int:
    identity = [seed, state.task_id, state.completed_calls, state.candidate.arguments_json]
    return int.from_bytes(hashlib.sha256(json.dumps(identity).encode()).digest()[:8], "big")


def bounded_context(state: Observation, agent: AgentState, mode="progress") -> dict:
    if mode not in ("task", "history", "progress", "no_history", "no_progress"):
        raise ValueError("Unknown context mode")
    if agent.observed_at_s > state.now_s or agent.phase_since_s > state.now_s:
        raise ValueError("Future observations are forbidden")
    result = {
        "task": agent.task_context[:2048],
        # Other agents forecast their own demand, not reuse of somebody else's call.
        "candidate": asdict(state.candidate) if agent.task_id == state.task_id else None,
        "candidate_belongs_to_agent": agent.task_id == state.task_id,
    }
    if mode in ("history", "progress", "no_progress"):
        result["history"] = [asdict(c) for c in agent.history[-8:]]
    if mode in ("progress", "no_history", "no_progress"):
        result["excerpt"] = agent.result_excerpt[:1024]
    if mode in ("progress", "no_history"):
        result.update(
            completed_calls=agent.completed_calls,
            phase=agent.phase,
            elapsed_s=state.now_s - agent.phase_since_s,
        )
    return result


def calibration(rows: list[tuple[float, bool]]) -> dict:
    if not rows:
        return {"count": 0, "brier": None, "ece": None, "bins": []}
    bins = []
    for i in range(10):
        bucket = [(p, y) for p, y in rows if min(int(p * 10), 9) == i]
        if bucket:
            bins.append(
                {
                    "count": len(bucket),
                    "probability": sum(p for p, _ in bucket) / len(bucket),
                    "frequency": sum(y for _, y in bucket) / len(bucket),
                }
            )
    return {
        "count": len(rows),
        "brier": sum((p - y) ** 2 for p, y in rows) / len(rows),
        "ece": sum(b["count"] * abs(b["probability"] - b["frequency"]) for b in bins) / len(rows),
        "bins": bins,
    }
