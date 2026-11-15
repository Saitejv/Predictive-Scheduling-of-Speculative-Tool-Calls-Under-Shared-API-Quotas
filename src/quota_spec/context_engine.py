"""Observed live agent contexts, asynchronous forecasts and shared Search quota.

No answers or future actions enter this module. The event loop owns all quota
mutations. Forecast I/O runs off-loop; a final claim rechecks required priority,
reset identity and agent revisions without yielding to another coroutine.
"""

import asyncio
import json
import time
from collections import deque
from dataclasses import asdict, replace

from .admission import AdmissionConfig, PredictiveAdmission
from .artifacts import append_json
from .hotpot_runtime import split_action
from .models import AgentState, Call, KnownExecution, Observation, QueuedCall, Snapshot
from .prediction import bounded_context
from .quota import FixedWindowQuota


class ForecastCache:
    """Bounded TTL cache with single-flight requests and immutable exact inputs.

    Each predictor instance serves one request, so adapter decision state and
    telemetry cannot race. Other-agent demand can be shared across candidates;
    candidate-dependent owner forecasts have different keys.
    """

    def __init__(
        self,
        factory,
        *,
        output=None,
        max_requests=400,
        ttl_s=1.0,
        workers=4,
        max_usd=0.25,
        request_reserve_usd=0.01,
        calibration=None,
        mode="progress",
    ):
        self.factory, self.output = factory, output
        self.max_requests, self.ttl_s = max_requests, ttl_s
        self.slots = asyncio.Semaphore(workers)
        self.cache, self.inflight, self.records = {}, {}, []
        self.requests = self.hits = 0
        self.unknown_cost = False
        self.max_usd, self.request_reserve_usd = max_usd, request_reserve_usd
        self.spent = self.reserved = 0.0
        self.calibration = calibration
        if mode not in (
            "task",
            "history",
            "progress",
            "no_history",
            "no_progress",
            "progress_intent",
        ):
            raise ValueError("Unknown forecast context mode")
        self.mode = mode

    async def forecast(self, state, agent):
        # Exact context, including elapsed, is retained. Cache only within the
        # same logical observed phase: elapsed is fixed at its request value.
        context = bounded_context(state, agent, self.mode)
        identity = dict(context)
        identity.pop("elapsed_s", None)
        key = json.dumps(identity, sort_keys=True)
        now = time.perf_counter()
        prior = self.cache.get(key)
        if prior and now - prior[0] <= self.ttl_s:
            self.hits += 1
            return prior[1]
        if key in self.inflight:
            self.hits += 1
            return await asyncio.shield(self.inflight[key])

        async def request():
            async with self.slots:
                if (
                    self.requests >= self.max_requests
                    or self.unknown_cost
                    or self.spent + self.reserved + self.request_reserve_usd > self.max_usd
                ):
                    raise ValueError("Forecast request budget exhausted or cost unknown")
                predictor = self.factory()
                self.requests += 1
                self.reserved += self.request_reserve_usd
                started = time.perf_counter()
                try:
                    result = await asyncio.to_thread(predictor.predict, state, agent)
                    if self.calibration:
                        result = self.calibration.transform(result)
                    self.cache[key] = (time.perf_counter(), result)
                    # Bound retained entries independently of episode count.
                    if len(self.cache) > 1024:
                        self.cache.pop(next(iter(self.cache)))
                    return result
                finally:
                    self.reserved -= self.request_reserve_usd
                    records = list(predictor.records)
                    if not records:
                        records = [{"failure": "MissingTelemetry", "cost_usd": None}]
                    for record in records:
                        row = {
                            **record,
                            "input": context,
                            "observed_at_s": state.now_s,
                            "engine_latency_s": time.perf_counter() - started,
                        }
                        if self.calibration and not record.get("failure"):
                            row["calibrated_forecast"] = asdict(result)
                        self.records.append(row)
                        if self.output:
                            append_json(self.output, row)
                        if record.get("cost_usd") is None:
                            self.unknown_cost = True
                        else:
                            self.spent += record["cost_usd"]

        task = asyncio.create_task(request())
        self.inflight[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            # Cancellation must not orphan paid requests or remove their
            # single-flight identity until the request actually finishes.
            try:
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                self.inflight.pop(key, None)


class FrozenDecision:
    def __init__(self, forecasts):
        self.forecasts = forecasts

    def predict(self, state, agent):
        return self.forecasts[agent.task_id]


class ContextCoordinator:
    def __init__(
        self,
        events,
        *,
        capacity=12,
        window_s=30,
        policy="jev_full",
        history=None,
        forecasts=None,
        reserve=0,
        samples=16,
        horizon_s=30,
    ):
        if policy not in {
            "no_speculation",
            "current_capacity",
            "fixed_reserve",
            "history_full",
            "jev_full",
            "jev_own",
        }:
            raise ValueError("Unknown live policy")
        if not 0 <= reserve <= capacity:
            raise ValueError("Reserve must lie within capacity")
        self.events, self.policy = events, policy
        self.quota = FixedWindowQuota(capacity, window_s)
        self.history, self.forecasts, self.reserve = history, forecasts, reserve
        self.config = AdmissionConfig(samples=samples, horizon_s=horizon_s, nonblocking=True)
        self.agents, self.versions, self.approvals = {}, {}, {}
        self.queue, self.reservations, self.executions = deque(), set(), {}
        self.condition = asyncio.Condition()
        self.recent_required = []
        self.expected_duration_s = 0.5
        self.max_active = 0
        self.decisions = []

    def now(self):
        return self.events.clock() - self.events.start

    def update(self, episode, **fields):
        if episode in self.agents:
            self.agents[episode] = replace(self.agents[episode], observed_at_s=self.now(), **fields)
            self.versions[episode] += 1

    def on_event(self, row):
        event, episode = row["event"], row.get("episode")
        now = self.now()
        if event == "episode_started":
            self.agents[episode] = AgentState(
                episode, now, 0, "thinking", now, task_context=row["question"]
            )
            self.versions[episode] = 0
            self.max_active = max(self.max_active, len(self.agents))
        elif event == "required_action" and episode in self.agents:
            tool, value = split_action(row["action"])
            call = (
                Call.search(value) if tool == "search" else Call(tool, json.dumps({"value": value}))
            )
            self.update(
                episode,
                history=(*self.agents[episode].history[-7:], call),
                phase="queued" if tool == "search" else "running",
                phase_since_s=now,
                intent=row.get("thought", ""),
            )
        elif event == "tool_observed":
            self.update(
                episode,
                completed_calls=row["step"],
                phase="thinking",
                phase_since_s=now,
                result_excerpt=row["observation"][:1024],
            )
        elif event == "answer_ready":
            self.agents.pop(episode, None)
            self.versions.pop(episode, None)
            self.approvals = {k: v for k, v in self.approvals.items() if k[0] != episode}
        elif event == "episode_drained":
            self.executions = {k: v for k, v in self.executions.items() if k[0] != episode}

    def observation(self, episode, query):
        now = self.now()
        snapshot = Snapshot(
            self.quota.capacity,
            self.quota.window_s,
            tuple(self.agents.values()),
            tuple(
                KnownExecution(tid, call, finish)
                for (tid, call), finish in self.executions.items()
                if tid in self.agents
            ),
            tuple(QueuedCall(tid, Call.search(q), ready) for tid, q, ready, _ in self.queue),
            tuple(t for t in self.recent_required if t >= now - self.quota.window_s),
        )
        return Observation(
            now,
            episode,
            self.agents[episode].completed_calls,
            Call.search(query),
            self.quota.remaining(now),
            len(self.queue),
            snapshot,
        )

    async def admit_candidate(self, episode, query, valid):
        if self.policy == "no_speculation":
            return False
        # Retain a ready candidate through quota resets, without occupying a
        # required queue position or creating a cache future the actor could join.
        while valid() and episode in self.agents:
            if not self.queue and self.quota.remaining(self.now()) > self.reserve:
                break
            await asyncio.sleep(
                min(0.05, max(0.001, self.quota.next_refill(self.now()) - self.now()))
            )
        if not valid() or episode not in self.agents:
            return False
        admitted, reason, detail = True, "capacity", {}
        if self.policy in {"jev_full", "jev_own", "history_full"}:
            admitted = False
            for _ in range(2):
                if not valid() or episode not in self.agents:
                    break
                state = self.observation(episode, query)
                versions, window = dict(self.versions), self.quota.window_index
                started = self.now()
                try:
                    if self.policy.startswith("jev"):
                        values = await asyncio.gather(
                            *(self.forecasts.forecast(state, a) for a in state.snapshot.agents),
                            return_exceptions=True,
                        )
                        failure = next((v for v in values if isinstance(v, BaseException)), None)
                        if failure:
                            raise ValueError(str(failure))
                        forecasts = {a.task_id: v for a, v in zip(state.snapshot.agents, values)}
                    else:
                        forecasts = {
                            a.task_id: self.history.predict(state, a) for a in state.snapshot.agents
                        }
                    if not valid() or episode not in self.agents:
                        reason = "expired"
                        break
                    if (
                        versions != self.versions
                        or self.quota.remaining(self.now()) < 1
                        or window != self.quota.window_index
                    ):
                        reason = "context_changed"
                        continue
                    # Refresh quota/executions and elapsed time after real I/O.
                    # Paired rollout runs on current state: no fake latency charge
                    # and no pause of authoritative work while inference runs.
                    current = self.observation(episode, query)
                    rule = PredictiveAdmission(
                        FrozenDecision(forecasts), self.config, own_only=self.policy == "jev_own"
                    )
                    admitted = rule.admit(current)
                    detail = rule.last_decision
                    reason = "forecast"
                    self.approvals[(episode, query)] = (
                        dict(self.versions),
                        self.quota.window_index,
                        self.quota.used,
                    )
                    break
                except (ValueError, OSError, TimeoutError) as exc:
                    reason, detail = (
                        "forecast_failed",
                        {"failure": type(exc).__name__, "reason": str(exc)[:200]},
                    )
                    break
                finally:
                    detail["forecast_wall_s"] = self.now() - started
        row = {
            "episode": episode,
            "query": query,
            "admitted": bool(admitted),
            "reason": reason,
            "detail": detail,
        }
        self.decisions.append(row)
        self.events.emit("admission_decided", **row)
        return admitted

    def claim_candidate(self, episode, query):
        now = self.now()
        remaining = self.quota.remaining(now)
        approval = self.approvals.pop((episode, query), None)
        if self.policy in {"jev_full", "jev_own", "history_full"} and approval != (
            self.versions,
            self.quota.window_index,
            self.quota.used,
        ):
            self.events.emit(
                "admission_claim_rejected", episode=episode, query=query, reason="ledger_changed"
            )
            return False
        if (
            episode not in self.agents
            or self.queue
            or remaining <= self.reserve
            or (episode, query) in self.reservations
        ):
            return False
        if not self.quota.consume(now):
            return False
        self.reservations.add((episode, query))
        self.events.emit(
            "quota_claimed",
            episode=episode,
            query=query,
            speculative=True,
            window_index=self.quota.window_index,
            remaining=self.quota.remaining(now),
        )
        return True

    async def acquire_required(self, episode, query):
        ticket = (episode, query, self.now(), object())
        self.queue.append(ticket)
        self.recent_required.append(ticket[2])
        self.recent_required = self.recent_required[-4096:]
        try:
            async with self.condition:
                while True:
                    now = self.now()
                    if self.queue[0] is ticket and self.quota.consume(now):
                        self.queue.popleft()
                        self.condition.notify_all()
                        self.events.emit(
                            "quota_claimed",
                            episode=episode,
                            query=query,
                            speculative=False,
                            window_index=self.quota.window_index,
                            remaining=self.quota.remaining(now),
                            wait_s=now - ticket[2],
                        )
                        return
                    try:
                        await asyncio.wait_for(
                            self.condition.wait(),
                            timeout=max(0.001, self.quota.next_refill(now) - now),
                        )
                    except TimeoutError:
                        pass
        finally:
            if ticket in self.queue:
                self.queue.remove(ticket)
                async with self.condition:
                    self.condition.notify_all()


class SharedSearch:
    def __init__(self, backend, coordinator):
        self.backend, self.coordinator = backend, coordinator

    async def search(self, query, episode, step, speculative=False):
        c = self.coordinator
        queued = c.now()
        if speculative:
            c.reservations.remove((episode, query))
        else:
            await c.acquire_required(episode, query)
            c.update(episode, phase="running", phase_since_s=c.now())
        key = (episode, Call.search(query))
        quota_wait = c.now() - queued
        c.executions[key] = c.now() + c.expected_duration_s
        try:
            result = await self.backend.search(query, episode, step, speculative)
            c.executions[key] = c.now()
            return {
                **result,
                "quota_wait_s": quota_wait,
                "queue_s": result.get("queue_s", 0) + quota_wait,
            }
        except BaseException:
            c.executions.pop(key, None)
            raise
