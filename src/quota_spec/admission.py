"""Paired, bounded demand rollouts constructed exclusively from observed state."""

import heapq
import json
import math
import random
import time
from dataclasses import dataclass

from .models import Call, Observation, nonnegative, positive_int
from .prediction import Predictor, decision_seed
from .quota import FixedWindowQuota


@dataclass(frozen=True)
class Demand:
    delay_s: float
    duration_s: float
    call: Call


@dataclass(frozen=True)
class AdmissionConfig:
    samples: int = 16
    horizon_s: float = 30.0
    max_calls: int = 4
    epsilon: float = 0.05
    overhead_s: float = 0.001
    seed: int = 7

    def __post_init__(self):
        positive_int(self.samples, "samples")
        positive_int(self.max_calls, "max_calls")
        for name in ("horizon_s", "overhead_s", "epsilon"):
            nonnegative(getattr(self, name), name)
        if not 1 <= self.samples <= 256 or not 1 <= self.max_calls <= 16:
            raise ValueError("samples must be 1..256 and max_calls 1..16")
        if (
            not math.isfinite(self.horizon_s)
            or self.horizon_s <= 0
            or not math.isfinite(self.overhead_s)
            or self.overhead_s < 0
            or not math.isfinite(self.epsilon)
            or not 0 <= self.epsilon <= 1
        ):
            raise ValueError("Invalid horizon, overhead or risk threshold")


def sample_scenarios(state, predictor, config):
    rng = random.Random(decision_seed(state, config.seed))
    if hasattr(predictor, "begin_decision"):
        predictor.begin_decision()
    try:
        forecasts = {a.task_id: predictor.predict(state, a) for a in state.snapshot.agents}
    finally:
        if hasattr(predictor, "end_decision"):
            predictor.end_decision()
    scenarios = []
    for _ in range(config.samples):
        scenario = {}
        for agent in state.snapshot.agents:
            forecast = forecasts[agent.task_id]
            chain = []
            if rng.random() < forecast.next_probability:
                for index in range(config.max_calls):
                    delay = rng.choice(forecast.delays_s)
                    if index == 0 and agent.phase == "thinking":
                        delay = max(0.0, delay - (state.now_s - agent.phase_since_s))
                    call = (
                        state.candidate
                        if agent.task_id == state.task_id
                        and index == 0
                        and rng.random() < forecast.reuse_probability
                        else Call(
                            "__forecast__", json.dumps({"task": agent.task_id, "index": index})
                        )
                    )
                    chain.append(Demand(delay, rng.choice(forecast.durations_s), call))
                    if rng.random() >= forecast.continue_probability:
                        break
            scenario[agent.task_id] = tuple(chain)
        scenarios.append(scenario)
    return scenarios, forecasts


def rollout(state: Observation, scenario: dict, admit: bool, overhead_s: float, horizon_s: float):
    """Censored projected chain completion; retain spent quota until actual refill.

    Known queued/running required work is inserted before sampled continuations.
    Past completed results and in-flight work preserve exact reuse semantics.
    Calls ready outside the horizon contribute the censored horizon endpoint.
    """
    snapshot = state.snapshot
    end = state.now_s + horizon_s
    # Preserve a strict miss at a deadline exactly on the censoring boundary.
    censored = math.nextafter(end, math.inf)
    quota = FixedWindowQuota(snapshot.capacity, snapshot.window_s)
    quota.remaining(state.now_s)
    quota.used = snapshot.capacity - state.quota_remaining
    cache = {(e.task_id, e.call): e.finish_s for e in snapshot.executions}
    queue = []
    serial = 0
    finishes = {a.task_id: state.now_s for a in snapshot.agents}

    def push(
        ready,
        tid,
        call,
        duration,
        index,
        *,
        waiting=False,
        original_ready=None,
        original_serial=None,
    ):
        nonlocal serial
        serial += 1
        heapq.heappush(
            queue,
            (
                ready,
                0 if waiting else 1,
                ready if original_ready is None else original_ready,
                serial if original_serial is None else original_serial,
                tid,
                call,
                duration,
                index,
            ),
        )

    if admit:
        if not quota.consume(state.now_s):
            raise ValueError("Ineligible speculative rollout")
        own = scenario[state.task_id]
        duration = own[0].duration_s if own else 1.0
        cache[state.task_id, state.candidate] = state.now_s + overhead_s + duration
    known = {q.task_id: q for q in snapshot.required}
    for agent in snapshot.agents:
        chain = scenario[agent.task_id]
        if agent.task_id in known:
            q = known[agent.task_id]
            # Preserve observed FIFO; readiness is already known, duration is forecast.
            duration = chain[0].duration_s if chain else 1.0
            push(
                state.now_s,
                agent.task_id,
                q.call,
                duration,
                -1,
                waiting=True,
                original_ready=q.ready_s,
            )
        elif agent.phase == "running":
            # The most recently dispatched required call is identified by history[-1].
            call = agent.history[-1] if agent.history else None
            finish = max(state.now_s, cache.get((agent.task_id, call), state.now_s))
            finishes[agent.task_id] = min(censored, finish)
            if chain:
                d = chain[0]
                push(finish + d.delay_s, agent.task_id, d.call, d.duration_s, 0)
        elif chain:
            d = chain[0]
            ready = state.now_s + d.delay_s
            if agent.task_id == state.task_id:
                ready = max(ready, state.now_s + overhead_s)
            push(ready, agent.task_id, d.call, d.duration_s, 0)
    while queue:
        ready, _, original_ready, original_serial, tid, call, duration, index = heapq.heappop(queue)
        if ready > end:
            finishes[tid] = censored
            continue
        if (tid, call) in cache:
            finish = max(ready, cache[tid, call])
        else:
            # FIFO wait for quota. Reinsert at refill so earlier completions can
            # generate dependency requests before this pending work is dispatched.
            if not quota.consume(ready):
                refill = quota.next_refill(ready)
                # Process all existing earlier work before this future reservation.
                push(
                    refill,
                    tid,
                    call,
                    duration,
                    index,
                    waiting=True,
                    original_ready=original_ready,
                    original_serial=original_serial,
                )
                continue
            finish = ready + duration
            cache[tid, call] = finish
        finishes[tid] = min(censored, finish)
        chain = scenario[tid]
        if index + 1 < len(chain):
            d = chain[index + 1]
            push(finish + d.delay_s, tid, d.call, d.duration_s, index + 1)
    return finishes


class PredictiveAdmission:
    def __init__(
        self, predictor: Predictor, config: AdmissionConfig | None = None, *, own_only=False
    ):
        self.predictor, self.config = predictor, config or AdmissionConfig()
        self.own_only = own_only
        self.last_decision = {}
        self.overhead_s = 0.0

    def admit(self, state):
        started = time.perf_counter()
        self.last_decision = {}
        try:
            if state.snapshot is None:
                raise ValueError("Observed snapshot unavailable")
            if state.queued_required or state.quota_remaining < 1:
                raise ValueError("Required queue or exhausted quota")
            scenarios, forecasts = sample_scenarios(state, self.predictor, self.config)
            simulation_overhead = (
                max(self.config.overhead_s, time.perf_counter() - started)
                if getattr(self.predictor, "measured_overhead", False)
                else self.config.overhead_s
            )
            gains, owner_gains, added_misses = [], [], []
            # Risk denominator: every observed deadline within the horizon in each sample.
            deadlines = {
                a.task_id: a.deadline_s
                for a in state.snapshot.agents
                if a.deadline_s is not None and a.deadline_s <= state.now_s + self.config.horizon_s
            }
            for scenario in scenarios:
                rejected = rollout(
                    state, scenario, False, simulation_overhead, self.config.horizon_s
                )
                admitted = rollout(
                    state, scenario, True, simulation_overhead, self.config.horizon_s
                )
                owner_gains.append(rejected[state.task_id] - admitted[state.task_id])
                gains.append(
                    sum(
                        rejected[t] - admitted[t]
                        for t in rejected
                        if not self.own_only or t == state.task_id
                    )
                )
                added_misses.append(
                    sum(admitted[t] > d and rejected[t] <= d for t, d in deadlines.items())
                )
            gain = sum(gains) / len(gains)
            risk = sum(added_misses) / (len(gains) * len(deadlines)) if deadlines else 0.0
            decision_wall_s = time.perf_counter() - started
            self.overhead_s = (
                max(self.config.overhead_s, decision_wall_s)
                if getattr(self.predictor, "measured_overhead", False)
                else self.config.overhead_s
            )
            # Own-only ablation changes only the gain objective, retaining global risk.
            result = gain > self.overhead_s and risk <= self.config.epsilon
            self.last_decision = {
                "estimated_gain_s": gain,
                "owner_gain_s": sum(owner_gains) / len(gains),
                "incremental_miss_risk": risk,
                "deadline_denominator": len(deadlines),
                "samples": self.config.samples,
                "horizon_s": self.config.horizon_s,
                "max_calls": self.config.max_calls,
                "own_only": self.own_only,
                "reuse_probability": forecasts[state.task_id].reuse_probability,
                "overhead_s": self.overhead_s,
                "decision_wall_s": decision_wall_s,
                "fallback": None,
            }
            return result
        except (ValueError, OSError, TimeoutError, KeyError, TypeError) as exc:
            wall = time.perf_counter() - started
            self.overhead_s = (
                max(self.config.overhead_s, wall)
                if getattr(self.predictor, "measured_overhead", False)
                else self.config.overhead_s
            )
            self.last_decision = {
                "fallback": type(exc).__name__,
                "reason": str(exc)[:200],
                "overhead_s": self.overhead_s,
                "decision_wall_s": wall,
            }
            return False
