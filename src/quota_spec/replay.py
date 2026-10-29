"""Deterministic discrete-event replay with serial per-task dependencies."""

import heapq
import math
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Callable

from .models import (
    AgentState,
    Call,
    KnownExecution,
    Observation,
    QueuedCall,
    Snapshot,
    Task,
    nonnegative,
)
from .policies import NoSpeculation, Policy
from .quota import FixedWindowQuota

DecisionKey = tuple[str, int]


@dataclass
class Execution:
    task_id: str
    call: Call
    finish_s: float
    speculative: bool
    used: bool = False
    done: bool = False
    started_s: float = 0.0
    waiters: list[tuple[str, int, float]] = field(default_factory=list)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; intentionally explicit for small pilot samples."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else 0.0


@dataclass
class ReplayResult:
    metrics: dict
    events: list[dict]
    decisions: dict[DecisionKey, bool]


class Replay:
    # Stable tie order: tool completion, required readiness, task/step entry,
    # quota wakeup, then optional admission. Required work wins same-time ties.
    PRIORITY = {"finish": 0, "required": 1, "enter": 2, "refill": 3, "candidate": 4}

    def __init__(
        self,
        tasks: tuple[Task, ...],
        capacity: int,
        window_s: float,
        *,
        required_order="fifo",
        expected_duration_s=1.0,
    ):
        if not tasks or len({t.task_id for t in tasks}) != len(tasks):
            raise ValueError("Provide nonempty tasks with unique IDs")
        self.tasks = {t.task_id: t for t in tasks}
        self.capacity, self.window_s = capacity, window_s
        if required_order not in ("fifo", "progress"):
            raise ValueError("required_order must be fifo or progress")
        nonnegative(expected_duration_s, "expected_duration_s")
        self.expected_duration_s = expected_duration_s
        self.required_order = required_order
        FixedWindowQuota(capacity, window_s)  # Fail before beginning an experiment.

    def run(
        self,
        policy: Policy | None = None,
        *,
        forced: dict[DecisionKey, bool] | None = None,
        decide: Callable[[Observation, DecisionKey, dict], bool] | None = None,
    ) -> ReplayResult:
        started = time.perf_counter()
        policy = policy or NoSpeculation()
        forced = forced or {}
        quota = FixedWindowQuota(self.capacity, self.window_s)
        heap: list[tuple] = []
        queue: deque = deque()
        cache: dict[tuple[str, Call], Execution] = {}
        executions: list[Execution] = []
        completed = {tid: 0 for tid in self.tasks}
        finish_times: dict[str, float] = {}
        waiting = {tid: 0.0 for tid in self.tasks}
        waits: list[float] = []
        events: list[dict] = []
        decisions: dict[DecisionKey, bool] = {}
        serial = 0
        scheduled_refill: float | None = None
        reuse_hits = 0
        agents: dict[str, AgentState] = {}
        histories: dict[str, list[Call]] = {tid: [] for tid in self.tasks}
        recent_required: list[float] = []
        blocked_until: dict[str, float] = {}
        modeled_overhead = 0.0

        def push(at: float, kind: str, payload=None) -> None:
            nonlocal serial
            serial += 1
            heapq.heappush(heap, (at, self.PRIORITY[kind], serial, kind, payload))

        def log(kind: str, **fields) -> None:
            events.append({"time_s": now, "event": kind, **fields})

        def advance(tid: str, index: int) -> None:
            completed[tid] += 1
            if index + 1 == len(self.tasks[tid].steps):
                finish_times[tid] = now
                log("task_finished", task_id=tid)
                agents.pop(tid, None)
            else:
                push(now, "enter", (tid, index + 1))

        def start(tid: str, call: Call, duration: float, speculative: bool) -> Execution:
            if not quota.consume(now):
                raise RuntimeError("Execution started without quota")
            ex = Execution(tid, call, now + duration, speculative, started_s=now)
            cache[(tid, call)] = ex
            executions.append(ex)
            push(ex.finish_s, "finish", ex)
            log(
                "call_started",
                task_id=tid,
                speculative=speculative,
                tool=call.tool,
                arguments_json=call.arguments_json,
                quota_remaining=quota.remaining(now),
            )
            return ex

        def dispatch() -> None:
            nonlocal scheduled_refill
            while queue and quota.remaining(now):
                if self.required_order == "progress":
                    ordered = sorted(queue, key=lambda row: (-completed[row[0]], row[2]))
                    queue.clear()
                    queue.extend(ordered)
                tid, index, ready = queue.popleft()
                step = self.tasks[tid].steps[index]
                delay = now - ready
                waits.append(delay)
                waiting[tid] += delay
                ex = start(tid, step.required, step.duration_s, False)
                ex.used = True
                ex.waiters.append((tid, index, ready))
                agents[tid] = replace(
                    agents[tid],
                    observed_at_s=now,
                    phase="running",
                    phase_since_s=now,
                    history=tuple(histories[tid][-8:]),
                )
            if queue and scheduled_refill is None:
                scheduled_refill = quota.next_refill(now)
                push(scheduled_refill, "refill")

        for task in self.tasks.values():
            push(task.arrival_s, "enter", (task.task_id, 0))

        while heap:
            now, _, _, kind, payload = heapq.heappop(heap)
            if kind == "enter":
                tid, index = payload
                step = self.tasks[tid].steps[index]
                agents[tid] = AgentState(
                    tid,
                    now,
                    completed[tid],
                    "thinking",
                    now,
                    self.tasks[tid].deadline_s,
                    self.tasks[tid].task_context,
                    tuple(histories[tid][-8:]),
                    self.tasks[tid].steps[index - 1].result_excerpt if index else "",
                )
                log("step_entered", task_id=tid, step=index)
                push(now + step.think_s, "required", payload)
                if step.candidate is not None:
                    push(now, "candidate", payload)
            elif kind == "candidate":
                tid, index = payload
                step = self.tasks[tid].steps[index]
                key = (tid, index)
                completed_executions = [ex for ex in executions if ex.done]
                observed_duration = (
                    sum(ex.finish_s - ex.started_s for ex in completed_executions)
                    / len(completed_executions)
                    if completed_executions
                    else self.expected_duration_s
                )
                snapshot = Snapshot(
                    self.capacity,
                    self.window_s,
                    tuple(agents.values()),
                    tuple(
                        KnownExecution(
                            ex.task_id,
                            ex.call,
                            ex.finish_s if ex.done else max(now, ex.started_s + observed_duration),
                        )
                        for ex in executions
                    ),
                    tuple(
                        QueuedCall(t, self.tasks[t].steps[i].required, ready)
                        for t, i, ready in queue
                    ),
                    tuple(t for t in recent_required if t >= now - self.window_s),
                )
                state = Observation(
                    now,
                    tid,
                    completed[tid],
                    step.candidate,
                    quota.remaining(now),
                    len(queue),
                    snapshot,
                )
                # Do not issue duplicate work for a call already ready or in flight.
                eligible = (
                    tid in agents
                    and agents[tid].phase == "thinking"
                    and completed[tid] == index
                    and not queue
                    and state.quota_remaining > 0
                    and (tid, step.candidate) not in cache
                )
                if not eligible:
                    admitted = False
                elif key in forced:
                    admitted = forced[key]
                elif decide is not None:
                    admitted = decide(state, key, dict(decisions))
                else:
                    admitted = policy.admit(state)
                details = (
                    dict(getattr(policy, "last_decision", {}))
                    if eligible and key not in forced
                    else {}
                )
                overhead = getattr(policy, "overhead_s", 0.0) if details else 0.0
                modeled_overhead += overhead
                blocked_until[tid] = now + overhead
                decisions[key] = admitted
                log(
                    "candidate_decided",
                    task_id=tid,
                    step=index,
                    admitted=admitted,
                    eligible=eligible,
                    **details,
                )
                if admitted:
                    start(tid, step.candidate, step.candidate_duration_s + overhead, True)
            elif kind == "required":
                tid, index = payload
                if now < blocked_until.get(tid, now):
                    push(blocked_until[tid], "required", payload)
                    continue
                step = self.tasks[tid].steps[index]
                histories[tid].append(step.required)
                recent_required.append(now)
                log("required_ready", task_id=tid, step=index)
                ex = cache.get((tid, step.required))
                if ex is not None:
                    reuse_hits += 1
                    ex.used = True
                    waits.append(0.0)
                    log("result_reused" if ex.done else "inflight_joined", task_id=tid, step=index)
                    if ex.done:
                        advance(tid, index)
                    else:
                        ex.waiters.append((tid, index, now))
                        agents[tid] = replace(
                            agents[tid],
                            observed_at_s=now,
                            phase="running",
                            phase_since_s=now,
                            history=tuple(histories[tid][-8:]),
                        )
                else:
                    agents[tid] = replace(
                        agents[tid],
                        observed_at_s=now,
                        phase="queued",
                        phase_since_s=now,
                        history=tuple(histories[tid][-8:]),
                    )
                    queue.append((tid, index, now))
                    dispatch()
            elif kind == "finish":
                ex = payload
                ex.done = True
                log("call_finished", task_id=ex.task_id, speculative=ex.speculative)
                for tid, index, _ in ex.waiters:
                    advance(tid, index)
            elif kind == "refill":
                scheduled_refill = None
                log("quota_refilled")
                dispatch()

        if len(finish_times) != len(self.tasks):
            raise RuntimeError("Replay ended with incomplete tasks")
        durations = [finish_times[t.task_id] - t.arrival_s for t in self.tasks.values()]
        deadline_tasks = [t for t in self.tasks.values() if t.deadline_s is not None]
        deadline_misses = sum(finish_times[t.task_id] > t.deadline_s for t in deadline_tasks)
        spec = [ex for ex in executions if ex.speculative]
        metrics = {
            "tasks": len(self.tasks),
            "mean_completion_s": sum(durations) / len(durations),
            "p95_completion_s": percentile(durations, 0.95),
            "mean_required_wait_s": sum(waits) / len(waits),
            "p95_required_wait_s": percentile(waits, 0.95),
            "deadline_tasks": len(deadline_tasks),
            "deadline_misses": deadline_misses,
            "deadline_completion_rate": 1 - deadline_misses / len(deadline_tasks)
            if deadline_tasks
            else None,
            "calls_started": len(executions),
            "speculative_calls": len(spec),
            "unused_speculative_calls": sum(not ex.used for ex in spec),
            "reuse_hits": reuse_hits,
            "per_agent_wait_s": waiting,
            "task_finish_s": finish_times,
            "per_agent_completion_s": {
                t.task_id: finish_times[t.task_id] - t.arrival_s for t in self.tasks.values()
            },
            "required_waits_s": waits,
            "modeled_decision_overhead_s": modeled_overhead,
            "required_order": self.required_order,
            "replay_wall_s": time.perf_counter() - started,
        }
        return ReplayResult(metrics, events, decisions)


def offline_reference(replay: Replay) -> ReplayResult:
    """Privileged greedy lookahead; never a deployable policy or global optimum.

    At each candidate, replay admit/reject using known future dependencies, while
    disabling undecided future speculation. Commit previous decisions identically
    to both branches. This isolates the value of accurate information for a pilot.
    """

    def decide(state: Observation, key: DecisionKey, previous: dict) -> bool:
        reject = replay.run(forced={**previous, key: False}).metrics
        admit = replay.run(forced={**previous, key: True}).metrics
        return (
            admit["mean_completion_s"] < reject["mean_completion_s"]
            and admit["deadline_misses"] <= reject["deadline_misses"]
        )

    return replay.run(decide=decide)
