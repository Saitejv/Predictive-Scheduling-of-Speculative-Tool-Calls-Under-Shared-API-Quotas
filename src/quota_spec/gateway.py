"""Single-process asyncio gateway with atomic quota reservation and exact reuse."""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, replace

from .models import AgentState, Call, KnownExecution, Observation, QueuedCall, Snapshot, nonnegative
from .policies import CurrentCapacity
from .quota import FixedWindowQuota


@dataclass
class Entry:
    future: asyncio.Future
    speculative: bool
    expected_finish_s: float
    worker: asyncio.Task | None = None
    used: bool = False
    started_s: float | None = None


class Gateway:
    def __init__(
        self,
        tool,
        capacity=3,
        window_s=10.0,
        policy=None,
        expected_duration_s=0.01,
        required_order="fifo",
    ):
        self.tool, self.policy = tool, policy or CurrentCapacity()
        self.quota = FixedWindowQuota(capacity, window_s)
        self.origin = time.monotonic()
        nonnegative(expected_duration_s, "expected_duration_s")
        self.expected_duration_s = expected_duration_s
        self.completed_execution_count = 0
        if required_order not in ("fifo", "progress"):
            raise ValueError("required_order must be fifo or progress")
        self.required_order = required_order
        self.lock = asyncio.Lock()
        self.prediction_lock = asyncio.Lock()
        self.registry = {}
        self.queue = deque()
        self.wakeup = None
        self.events = []
        self.agents = {}
        self.active_required = {}
        self.revision = 0
        self.considered = set()
        self.recent_required = []
        self.closed = False

    def now(self):
        return time.monotonic() - self.origin

    def log(self, event, **fields):
        self.events.append({"time_s": self.now(), "event": event, **fields})

    async def observe(self, agent: AgentState):
        async with self.lock:
            if self.closed:
                raise RuntimeError("Gateway is closed")
            previous = self.agents.get(agent.task_id)
            if previous and (
                agent.observed_at_s < previous.observed_at_s
                or agent.completed_calls < previous.completed_calls
            ):
                raise ValueError("Progress cannot move backwards")
            if agent.task_id in self.active_required:
                raise ValueError("Cannot replace progress while a required call is pending")
            if agent.observed_at_s > self.now() or agent.phase_since_s > self.now():
                raise ValueError("Future observations are forbidden")
            self.agents[agent.task_id] = agent
            self.revision += 1

    def _new_entry(self, speculative):
        future = asyncio.get_running_loop().create_future()
        # Retrieve failures even when optional work has no required waiter yet.
        future.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        return Entry(future, speculative, self.now() + self.expected_duration_s)

    def _start(self, key, entry):
        now = self.now()
        if not self.quota.consume(now):
            raise RuntimeError("Atomic dispatch without quota")
        entry.expected_finish_s = now + self.expected_duration_s
        entry.started_s = now
        self.log(
            "call_started",
            task_id=key[0],
            arguments_json=key[1].arguments_json,
            speculative=entry.speculative,
            quota_remaining=self.quota.remaining(now),
            window_index=self.quota.window_index,
            dispatch_s=now,
        )
        entry.worker = asyncio.create_task(self._execute(key, entry))
        # Cancellation can happen before the coroutine enters its try block.
        entry.worker.add_done_callback(lambda worker: self._worker_done(key, entry, worker))
        self.revision += 1
        if self.active_required.get(key[0]) == key:
            self.agents[key[0]] = replace(
                self.agents[key[0]], observed_at_s=now, phase="running", phase_since_s=now
            )

    def _pump(self):
        while self.queue and self.quota.remaining(self.now()):
            if self.required_order == "progress":
                self.queue = deque(
                    sorted(
                        self.queue,
                        key=lambda row: (-self.agents[row[0][0]].completed_calls, row[2]),
                    )
                )
            key, entry, ready = self.queue.popleft()
            self.log("required_wait", task_id=key[0], wait_s=self.now() - ready)
            self._start(key, entry)
        if self.queue and self.wakeup is None:
            self.wakeup = asyncio.create_task(self._refill())

    async def _refill(self):
        try:
            await asyncio.sleep(max(0, self.quota.next_refill(self.now()) - self.now()))
            async with self.lock:
                self.wakeup = None
                self._pump()
        except asyncio.CancelledError:
            raise

    def _finish_progress(self, key, result=None, *, failed=False):
        if self.active_required.get(key[0]) != key:
            return
        self.active_required.pop(key[0], None)
        old = self.agents.get(key[0])
        if old is not None:
            now = self.now()
            self.agents[key[0]] = replace(
                old,
                observed_at_s=now,
                phase="thinking",
                phase_since_s=now,
                completed_calls=old.completed_calls + int(not failed),
                result_excerpt=old.result_excerpt if failed else str(result)[:1024],
            )
        self.revision += 1

    def _worker_done(self, key, entry, worker):
        # Runs synchronously on the event loop; no suspension during this mutation.
        if worker.cancelled() and not entry.future.done():
            if self.registry.get(key) is entry:
                if entry.speculative and not entry.used:
                    self.log(
                        "unused_speculation", task_id=key[0], arguments_json=key[1].arguments_json
                    )
                self.registry.pop(key)
            entry.future.cancel()
            self._finish_progress(key, failed=True)
            self.log("call_cancelled", task_id=key[0], failure="CancelledError")

    async def _execute(self, key, entry):
        try:
            result = await self.tool(key[1])
        except (Exception, asyncio.CancelledError) as exc:
            async with self.lock:
                if self.registry.get(key) is entry:
                    if entry.speculative and not entry.used:
                        self.log(
                            "unused_speculation",
                            task_id=key[0],
                            arguments_json=key[1].arguments_json,
                        )
                    self.registry.pop(key)
                self._finish_progress(key, failed=True)
                if not entry.future.done():
                    if isinstance(exc, asyncio.CancelledError):
                        entry.future.cancel()
                    else:
                        entry.future.set_exception(exc)
                self.log(
                    "call_cancelled" if isinstance(exc, asyncio.CancelledError) else "call_failed",
                    task_id=key[0],
                    failure=type(exc).__name__,
                )
            return
        async with self.lock:
            entry.expected_finish_s = self.now()
            duration = entry.expected_finish_s - entry.started_s
            self.completed_execution_count += 1
            self.expected_duration_s += (
                duration - self.expected_duration_s
            ) / self.completed_execution_count
            # Only a matching required request may expose optional results to progress.
            self._finish_progress(key, result)
            if not entry.future.done():
                entry.future.set_result(result)
            self.revision += 1
            self.log(
                "call_finished",
                task_id=key[0],
                speculative=entry.speculative,
                arguments_json=key[1].arguments_json,
                duration_s=self.now() - entry.started_s,
            )

    async def required(self, task_id, call):
        key = (task_id, call)
        async with self.lock:
            if self.closed:
                raise RuntimeError("Gateway is closed")
            pending = self.active_required.get(task_id)
            if pending is not None and pending != key:
                raise ValueError("Only one required call per task may be pending")
            entry = self.registry.get(key)
            if pending is None:
                now = self.now()
                self.recent_required = [
                    t for t in self.recent_required if t >= now - self.quota.window_s
                ]
                self.recent_required.append(now)
                previous = self.agents.get(task_id, AgentState(task_id, now, 0, "thinking", now))
                self.agents[task_id] = replace(
                    previous,
                    observed_at_s=now,
                    phase="queued",
                    phase_since_s=now,
                    history=(*previous.history[-7:], call),
                )
                self.active_required[task_id] = key
                self.revision += 1
                self.log("required_ready", task_id=task_id, arguments_json=call.arguments_json)
            if entry is None:
                entry = self._new_entry(False)
                self.registry[key] = entry
                self.queue.append((key, entry, self.now()))
                self._pump()
            elif entry.future.done():
                self.log("result_reused", task_id=task_id)
                self._finish_progress(key, entry.future.result())
                if pending is None and not entry.speculative:
                    self.log("required_wait", task_id=task_id, wait_s=0.0)
            elif entry.worker is not None:
                old = self.agents[task_id]
                now = self.now()
                self.agents[task_id] = replace(
                    old, observed_at_s=now, phase="running", phase_since_s=now
                )
                self.log("inflight_joined", task_id=task_id)
            if pending is None and entry.speculative:
                self.log("required_wait", task_id=task_id, wait_s=0.0)
            entry.used = True
        # Completion updates progress once, even if every HTTP client disconnects.
        return await asyncio.shield(entry.future)

    async def finish_task(self, task_id):
        workers = []
        async with self.lock:
            if task_id in self.active_required:
                raise ValueError("Cannot finish a task with a pending required call")
            self.agents.pop(task_id, None)
            for key in list(self.registry):
                if key[0] == task_id:
                    entry = self.registry.pop(key)
                    if entry.speculative and not entry.used:
                        self.log(
                            "unused_speculation",
                            task_id=task_id,
                            arguments_json=key[1].arguments_json,
                        )
                    if entry.worker and not entry.worker.done():
                        entry.worker.cancel()
                        workers.append(entry.worker)
                    if not entry.future.done():
                        entry.future.cancel()
            self.considered = {key for key in self.considered if key[0] != task_id}
            self.revision += 1
            self.log("task_finished", task_id=task_id)
        await asyncio.gather(*workers, return_exceptions=True)

    async def speculate(self, task_id, call):
        async with self.prediction_lock:
            async with self.lock:
                if self.closed:
                    raise RuntimeError("Gateway is closed")
                now = self.now()
                key = (task_id, call)
                if task_id not in self.agents:
                    self.agents[task_id] = AgentState(task_id, now, 0, "thinking", now)
                agent = self.agents[task_id]
                step_key = (task_id, agent.completed_calls)
                if (
                    key in self.registry
                    or self.queue
                    or not self.quota.remaining(now)
                    or agent.phase != "thinking"
                    or step_key in self.considered
                ):
                    return False
                self.considered.add(step_key)
                snapshot = Snapshot(
                    self.quota.capacity,
                    self.quota.window_s,
                    tuple(self.agents.values()),
                    tuple(
                        KnownExecution(
                            tid,
                            c,
                            e.expected_finish_s
                            if e.future.done()
                            else max(now, e.started_s + self.expected_duration_s),
                        )
                        for (tid, c), e in self.registry.items()
                        if e.worker is not None
                    ),
                    tuple(QueuedCall(k[0], k[1], ready) for k, _, ready in self.queue),
                    tuple(t for t in self.recent_required if t >= now - self.quota.window_s),
                )
                observation = Observation(
                    now,
                    task_id,
                    agent.completed_calls,
                    call,
                    self.quota.remaining(now),
                    len(self.queue),
                    snapshot,
                )
                revision, window = self.revision, self.quota.window_index
            prediction = asyncio.create_task(asyncio.to_thread(self.policy.admit, observation))
            try:
                admitted = await asyncio.shield(prediction)
            except asyncio.CancelledError:
                # A Python thread cannot be cancelled. Keep serialization until it exits.
                await prediction
                raise
            decision = dict(getattr(self.policy, "last_decision", {}))
            async with self.lock:
                remaining = self.quota.remaining(self.now())
                eligible = (
                    not self.closed
                    and key not in self.registry
                    and not self.queue
                    and remaining > 0
                    and self.revision == revision
                    and self.quota.window_index == window
                )
                admitted = bool(admitted and eligible)
                self.log(
                    "candidate_decided",
                    task_id=task_id,
                    admitted=admitted,
                    stale=not eligible,
                    decision=decision,
                )
                if admitted:
                    entry = self._new_entry(True)
                    self.registry[key] = entry
                    self._start(key, entry)
                return admitted

    async def close(self):
        async with self.lock:
            self.closed = True
            workers = [e.worker for e in self.registry.values() if e.worker and not e.worker.done()]
            if self.wakeup:
                workers.append(self.wakeup)
            for worker in workers:
                worker.cancel()
            for entry in self.registry.values():
                if not entry.future.done():
                    entry.future.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


def create_app(corpus=None, *, capacity=None, window_s=None, policy=None):
    import json
    import os
    from contextlib import asynccontextmanager
    from pathlib import Path

    from fastapi import FastAPI
    from pydantic import BaseModel, Field, field_validator

    from .configuration import configured_policy
    from .search import SearchCorpus

    capacity = int(os.environ.get("QUOTA_CAPACITY", "3")) if capacity is None else capacity
    window_s = float(os.environ.get("QUOTA_WINDOW_S", "10")) if window_s is None else window_s
    policy = configured_policy() if policy is None else policy
    corpus = corpus or SearchCorpus.load(Path(os.environ.get("QUOTA_CORPUS", "data/corpus.json")))

    async def search(call):
        return await asyncio.to_thread(corpus.search, json.loads(call.arguments_json)["query"])

    gateway = Gateway(
        search,
        capacity,
        window_s,
        policy,
        required_order=os.environ.get("QUOTA_REQUIRED_ORDER", "fifo"),
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await gateway.close()

    app = FastAPI(title="Shared quota search gateway", lifespan=lifespan)
    app.state.gateway = gateway

    class Request(BaseModel):
        task_id: str = Field(min_length=1, max_length=256)
        query: str = Field(min_length=1, max_length=2048)

        @field_validator("task_id", "query")
        @classmethod
        def nonblank(cls, value):
            if not value.strip():
                raise ValueError("Value must not be blank")
            return value

    class Progress(BaseModel):
        task_id: str = Field(min_length=1, max_length=256)
        task_context: str = Field(default="", max_length=2048)
        completed_calls: int = Field(default=0, ge=0)
        result_excerpt: str = Field(default="", max_length=1024)
        deadline_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @app.exception_handler(ValueError)
    async def invalid_request(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.post("/finish/{task_id}")
    async def finish(task_id: str):
        await gateway.finish_task(task_id)
        return {"finished": True}

    @app.post("/observe")
    async def observe(body: Progress):
        now = gateway.now()
        old = gateway.agents.get(body.task_id)
        await gateway.observe(
            AgentState(
                body.task_id,
                now,
                body.completed_calls,
                "thinking",
                now,
                deadline_s=body.deadline_s,
                task_context=body.task_context,
                history=old.history if old else (),
                result_excerpt=body.result_excerpt,
            )
        )
        return {"observed_at_s": now}

    @app.post("/required")
    async def required(body: Request):
        return {"results": await gateway.required(body.task_id, Call.search(body.query))}

    @app.post("/candidate")
    async def candidate(body: Request):
        return {"admitted": await gateway.speculate(body.task_id, Call.search(body.query))}

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "capacity": capacity,
            "window_s": window_s,
            "corpus_sha256": corpus.digest,
            "workers": 1,
        }

    return app
