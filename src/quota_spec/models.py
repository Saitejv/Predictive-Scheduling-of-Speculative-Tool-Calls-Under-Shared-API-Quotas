"""Replay ground truth and the smaller, observed admission-policy interface."""

import json
import math
from dataclasses import dataclass
from typing import Any


def nonnegative(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and nonnegative")


def positive_int(value: int, name: str, minimum=1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class Call:
    tool: str
    arguments_json: str

    def __post_init__(self):
        if not isinstance(self.tool, str) or not self.tool.strip():
            raise ValueError("tool must be a nonempty string")
        try:
            arguments = json.loads(self.arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("Call arguments must be a JSON object")
            if self.tool == "search" and (
                set(arguments) != {"query"}
                or not isinstance(arguments["query"], str)
                or not arguments["query"].strip()
                or len(arguments["query"]) > 2048
            ):
                raise ValueError("Search requires a nonblank query of at most 2048 characters")
            canonical = json.dumps(arguments, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid call arguments: {exc}") from exc
        object.__setattr__(self, "arguments_json", canonical)

    @classmethod
    def search(cls, query: str) -> "Call":
        return cls("search", json.dumps({"query": query}, sort_keys=True))


@dataclass(frozen=True)
class Step:
    """Serial dependency: think, request required call, then advance on completion.

    candidate is an externally recorded hint available at step entry. It must not
    be constructed from the hidden required call by an online candidate generator.
    """

    think_s: float
    required: Call
    duration_s: float
    candidate: Call | None = None
    candidate_duration_s: float = 1.0
    result_excerpt: str = ""
    candidate_delay_s: float = 0.0

    def __post_init__(self) -> None:
        for name in ("think_s", "duration_s", "candidate_duration_s", "candidate_delay_s"):
            nonnegative(getattr(self, name), name)
        if not isinstance(self.required, Call) or (
            self.candidate is not None and not isinstance(self.candidate, Call)
        ):
            raise ValueError("Step calls must be Call objects")
        if not isinstance(self.result_excerpt, str):
            raise ValueError("result_excerpt must be a string")
        if self.candidate == self.required and self.candidate_duration_s != self.duration_s:
            raise ValueError("Exact-match calls must have the same recorded duration")


@dataclass(frozen=True)
class Task:
    task_id: str
    arrival_s: float
    steps: tuple[Step, ...]
    deadline_s: float | None = None  # Absolute experiment time, inclusive.
    task_context: str = ""
    final_think_s: float = 0.0
    final_candidate: Call | None = None
    final_candidate_duration_s: float = 0.0
    final_candidate_delay_s: float = 0.0

    def __post_init__(self) -> None:
        nonnegative(self.arrival_s, "arrival_s")
        if not isinstance(self.task_id, str) or not self.task_id.strip() or len(self.task_id) > 256:
            raise ValueError("task_id must be a nonblank string of at most 256 characters")
        if not isinstance(self.task_context, str):
            raise ValueError("task_context must be a string")
        if not isinstance(self.steps, tuple) or any(
            not isinstance(step, Step) for step in self.steps
        ):
            raise ValueError("steps must be a tuple of Step objects")
        for name in ("final_think_s", "final_candidate_duration_s", "final_candidate_delay_s"):
            nonnegative(getattr(self, name), name)
        if self.final_candidate is not None and not isinstance(self.final_candidate, Call):
            raise ValueError("final_candidate must be a Call")
        if self.deadline_s is not None:
            nonnegative(self.deadline_s, "deadline_s")
            if self.deadline_s < self.arrival_s:
                raise ValueError("Deadline cannot precede arrival")


@dataclass(frozen=True)
class Observation:
    """Only currently observed state; deliberately contains no future trace."""

    now_s: float
    task_id: str
    completed_calls: int
    candidate: Call
    quota_remaining: int
    queued_required: int
    snapshot: "Snapshot | None" = None


@dataclass(frozen=True)
class AgentState:
    task_id: str
    observed_at_s: float
    completed_calls: int
    phase: str
    phase_since_s: float
    deadline_s: float | None = None
    task_context: str = ""
    history: tuple[Call, ...] = ()
    result_excerpt: str = ""

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be nonblank")
        nonnegative(self.observed_at_s, "observed_at_s")
        nonnegative(self.phase_since_s, "phase_since_s")
        positive_int(self.completed_calls, "completed_calls", 0)
        if self.phase not in ("thinking", "running", "queued"):
            raise ValueError("Unknown agent phase")
        if self.phase_since_s > self.observed_at_s:
            raise ValueError("Phase cannot start after observation")
        if self.deadline_s is not None:
            nonnegative(self.deadline_s, "deadline_s")


@dataclass(frozen=True)
class KnownExecution:
    task_id: str
    call: Call
    finish_s: float


@dataclass(frozen=True)
class QueuedCall:
    task_id: str
    call: Call
    ready_s: float


@dataclass(frozen=True)
class Snapshot:
    """Observed ledger and registry only; no future arrivals or hidden steps."""

    capacity: int
    window_s: float
    agents: tuple[AgentState, ...]
    executions: tuple[KnownExecution, ...] = ()
    required: tuple[QueuedCall, ...] = ()
    recent_required_s: tuple[float, ...] = ()


def load_tasks(data: list[dict[str, Any]]) -> tuple[Task, ...]:
    return tuple(
        Task(
            task_id=row["task_id"],
            arrival_s=row["arrival_s"],
            deadline_s=row.get("deadline_s"),
            task_context=row.get("task_context", ""),
            final_think_s=row.get("final_think_s", 0),
            final_candidate=Call.search(row["final_candidate_query"])
            if row.get("final_candidate_query") is not None
            else None,
            final_candidate_duration_s=row.get("final_candidate_duration_s", 0),
            final_candidate_delay_s=row.get("final_candidate_delay_s", 0),
            steps=tuple(
                Step(
                    think_s=s["think_s"],
                    required=Call.search(s["query"]),
                    duration_s=s["duration_s"],
                    candidate=Call.search(s["candidate_query"])
                    if s.get("candidate_query") is not None
                    else None,
                    candidate_duration_s=s.get("candidate_duration_s", s["duration_s"]),
                    result_excerpt=s.get("result_excerpt", ""),
                    candidate_delay_s=s.get("candidate_delay_s", 0),
                )
                for s in row["steps"]
            ),
        )
        for row in data
    )
