"""Multi-candidate, dependency-driven scheduling on complete frozen HotpotQA tapes.

Uses the existing fixed-window quota and observed policy interfaces. It makes no
model or network calls. Candidate identity includes task, boundary and rank.
"""

import argparse
import hashlib
import heapq
import json
import math
import random
from collections import deque
from pathlib import Path

from .artifacts import write_json
from .models import AgentState, Call, KnownExecution, Observation, QueuedCall, Snapshot
from .policies import CurrentCapacity, FixedReserve, NoSpeculation
from .quota import FixedWindowQuota
from .replay import percentile


def load_dataset(root):
    root = Path(root)
    if (root / "INVALID_TIMING.json").exists():
        raise ValueError("Dataset has invalidated native timing; use its corrected replacement")
    manifest = json.loads((root / "dataset-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"Dataset integrity failure: {name}")
    data = json.loads((root / "tapes.json").read_text())
    if data["version"] != 1 or not data["complete"]:
        raise ValueError("Scheduling requires a complete supported frozen tape bank")
    if len({t["task_id"] for t in data["tapes"]}) != len(data["tapes"]):
        raise ValueError("Duplicate tape task IDs")
    for task in data["tapes"]:
        if not task["steps"]:
            raise ValueError("Empty authoritative tape")
        for row in task["steps"]:
            base = root / "parts" / task["shard"] if "shard" in task else root

            def check_result(reference):
                directory = {"live": "live-capture", "bank": "completion"}[reference["store"]]
                identity = reference["blob"]
                if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
                    raise ValueError("Invalid frozen result reference")
                path = base / directory / "blobs" / (identity + ".json")
                if not path.is_file():
                    raise ValueError("Missing frozen tool result; online fallback is forbidden")
                result = json.loads(path.read_text())
                if "state_before" not in result or "state_after" not in result:
                    raise ValueError("Missing full frozen tool state")

            if row["tool"] == "search":
                check_result(row["tool_result"])
            values = [row["actor_duration_s"], row["tool_duration_s"]]
            window = row["window"]
            if window:
                values += [window["observation_duration_s"], window["hypothetical_duration_s"]]
                for candidate in window["candidates"]:
                    if candidate["eligible"]:
                        values.append(candidate["duration_s"])
                        if "result" not in candidate:
                            raise ValueError("Missing candidate tool output")
                        check_result(candidate["result"])
            if any(
                not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values
            ):
                raise ValueError("Invalid captured duration")
    return data


class FrozenReplay:
    """Replay simultaneous agents or a closed-loop worker pool; required calls keep FIFO order."""

    PRIORITY = {
        "tool_done": 0,
        "local_done": 0,
        "actor_done": 1,
        "refill": 2,
        "observation_done": 3,
        "hypothetical_done": 4,
        "decision": 5,
        "retry_candidates": 5,
    }

    def __init__(
        self,
        tapes,
        capacity,
        window_s,
        *,
        tool_duration_s=None,
        max_active_agents=None,
        max_candidate_age=0,
        candidate_ttl_s=None,
        release_on_answer=False,
        suppress_known_calls=False,
        revalidate_reset=False,
        generation_reserve=None,
        generate_on_reuse=False,
        cache_required_results=False,
        generation_trigger="dispatch",
        retry_candidates=False,
        max_generation_step=None,
    ):
        self.tapes = {t["task_id"]: t for t in tapes}
        if not self.tapes or len(self.tapes) != len(tapes):
            raise ValueError("Provide nonempty unique tapes")
        FixedWindowQuota(capacity, window_s)
        if tool_duration_s is not None and (
            not math.isfinite(tool_duration_s) or tool_duration_s < 0
        ):
            raise ValueError("Tool override must be finite and nonnegative")
        self.capacity, self.window_s, self.tool_duration_s = capacity, window_s, tool_duration_s
        if max_active_agents is not None and (
            type(max_active_agents) is not int or max_active_agents < 1
        ):
            raise ValueError("Active agent limit must be a positive integer")
        self.max_active_agents = max_active_agents or len(tapes)
        if type(max_candidate_age) is not int or max_candidate_age < 0:
            raise ValueError("max_candidate_age must be a nonnegative integer")
        if candidate_ttl_s is not None and (
            not math.isfinite(candidate_ttl_s) or candidate_ttl_s <= 0
        ):
            raise ValueError("candidate_ttl_s must be positive and finite")
        self.max_candidate_age, self.candidate_ttl_s = max_candidate_age, candidate_ttl_s
        self.release_on_answer = release_on_answer
        self.suppress_known_calls, self.revalidate_reset = suppress_known_calls, revalidate_reset
        if generation_reserve is not None and (
            type(generation_reserve) is not int or generation_reserve < 0
        ):
            raise ValueError("generation_reserve must be a nonnegative integer")
        self.generation_reserve = generation_reserve
        self.generate_on_reuse = generate_on_reuse
        self.cache_required_results = cache_required_results
        if generation_trigger not in ("dispatch", "request"):
            raise ValueError("generation_trigger must be dispatch or request")
        self.generation_trigger = generation_trigger
        self.retry_candidates = retry_candidates
        if max_generation_step is not None and (
            type(max_generation_step) is not int or max_generation_step < 0
        ):
            raise ValueError("Generation step budget must be a nonnegative integer")
        self.max_generation_step = max_generation_step

    def run(
        self,
        policy=None,
        *,
        forced=None,
        generation_windows=None,
        record_events=True,
        record_decisions=True,
    ):
        """Schedule recorded dependencies; optional offline controls never enter policies.

        forced: set of (task_id, one-based source step, rank) admitted when eligible.
        generation_windows: optional set of (task_id, one-based source step).
        These are privileged oracle-analysis inputs, not observed model context.
        """
        policy = policy or NoSpeculation()
        speculation = forced is not None or not isinstance(policy, NoSpeculation)
        quota = FixedWindowQuota(self.capacity, self.window_s)
        heap, serial, events = [], 0, []
        queue, cache, executions = deque(), {}, []
        completed = {tid: 0 for tid in self.tapes}
        current = {tid: -1 for tid in self.tapes}
        histories = {tid: [] for tid in self.tapes}
        phases, since = {}, {}
        answers, finish, waits = {}, {}, []
        agent_waits = {tid: 0.0 for tid in self.tapes}
        recent, decisions = [], []
        requested = set()
        deferred = {}
        retry_scheduled = False
        stats = {
            "cache_hits": 0,
            "inflight_hits": 0,
            "late_windows": 0,
            "observation_runs": 0,
            "hypothetical_runs": 0,
            "actor_runs": 0,
            "predictor_overhead_s": 0.0,
            "duplicate_candidates_suppressed": 0,
            "post_action_candidates": 0,
            "post_action_launches": 0,
            "generation_windows_suppressed": 0,
            "candidates_deferred": 0,
            "deferred_candidates_expired": 0,
        }
        wakeup = None
        now = 0.0
        arrivals, released, drained, opened = {}, set(), set(), {}
        worker_release_times = {}
        pending = {tid: 0 for tid in self.tapes}
        workload = deque(self.tapes)

        def owner(kind, data):
            return (
                None
                if kind in ("refill", "retry_candidates")
                else data["task_id"]
                if kind == "tool_done"
                else data[0]
            )

        def push(at, kind, data):
            nonlocal serial
            serial += 1
            heapq.heappush(heap, (at, self.PRIORITY[kind], serial, kind, data))
            task_id = owner(kind, data)
            if task_id is not None:
                pending[task_id] += 1

        def log(kind, **fields):
            if record_events:
                events.append({"time_s": now, "event": kind, **fields})

        def duration(value):
            return value if self.tool_duration_s is None else self.tool_duration_s

        def active(tid, index, at=None):
            return (
                tid not in finish
                and index <= current[tid] <= index + self.max_candidate_age
                and (
                    self.candidate_ttl_s is None
                    or (now if at is None else at) - opened[tid, index] <= self.candidate_ttl_s
                )
            )

        def known(tid, query):
            return (tid, query) in cache or (
                self.suppress_known_calls
                and (
                    (tid, query) in requested
                    if self.generation_trigger == "request" or self.retry_candidates
                    else any(e["task_id"] == tid and e["query"] == query for e in executions)
                )
            )

        def enter(tid, index):
            if index == 0:
                arrivals[tid] = now
                log("task_started", task_id=tid)
            if index == len(self.tapes[tid]["steps"]):
                finish[tid] = now
                answers[tid] = self.tapes[tid]["answer"]
                phases.pop(tid, None)
                log("answer_ready", task_id=tid, answer=answers[tid])
                return
            phases[tid], since[tid] = "thinking", now
            stats["actor_runs"] += 1
            row = self.tapes[tid]["steps"][index]
            push(now + row["actor_duration_s"], "actor_done", (tid, index))
            log("actor_started", task_id=tid, step=index + 1)

        def release(tid):
            if tid in finish and tid not in drained and pending[tid] == 0:
                drained.add(tid)
                log("task_drained", task_id=tid)
            if (
                tid in finish
                and tid not in released
                and (self.release_on_answer or pending[tid] == 0)
            ):
                released.add(tid)
                worker_release_times[tid] = now
                log("worker_released", task_id=tid)
                if workload:
                    enter(workload.popleft(), 0)

        def advance(tid, index):
            completed[tid] = index + 1
            enter(tid, index + 1)

        def start(tid, query, seconds, speculative, index):
            if not quota.consume(now):
                raise RuntimeError("Search dispatch without quota")
            execution = {
                "task_id": tid,
                "query": query,
                "start_s": now,
                "end_s": now + duration(seconds),
                "done": False,
                "speculative": speculative,
                "used": not speculative,
                "waiters": [],
                "index": index,
            }
            executions.append(execution)
            if speculative or self.cache_required_results:
                cache[tid, query] = execution
            push(execution["end_s"], "tool_done", execution)
            log(
                "search_started",
                task_id=tid,
                query=query,
                speculative=speculative,
                quota_remaining=quota.remaining(now),
            )
            return execution

        def generate(tid, index):
            row = self.tapes[tid]["steps"][index]
            allowed = self.generation_reserve is None or (
                not queue and quota.remaining(now) > self.generation_reserve
            )
            if generation_windows is not None:
                allowed = allowed and (tid, index + 1) in generation_windows
            if self.max_generation_step is not None:
                allowed = allowed and index < self.max_generation_step
            if speculation and row["window"] and not allowed:
                stats["generation_windows_suppressed"] += 1
            if speculation and row["window"] and allowed:
                opened[tid, index] = now
                stats["observation_runs"] += 1
                log(
                    "generation_started",
                    task_id=tid,
                    step=index + 1,
                    trigger=self.generation_trigger,
                )
                push(
                    now + row["window"]["observation_duration_s"],
                    "observation_done",
                    (tid, index),
                )

        def schedule_retry():
            nonlocal retry_scheduled
            if deferred and not retry_scheduled:
                retry_scheduled = True
                push(now, "retry_candidates", None)

        def dispatch():
            nonlocal wakeup
            while queue and quota.remaining(now):
                tid, index, ready = queue.popleft()
                row = self.tapes[tid]["steps"][index]
                wait = now - ready
                waits.append(wait)
                agent_waits[tid] += wait
                execution = start(tid, row["query"], row["tool_duration_s"], False, index)
                execution["waiters"].append((tid, index))
                phases[tid], since[tid] = "running", now
                if self.generation_trigger == "dispatch":
                    generate(tid, index)
            if queue and wakeup is None:
                wakeup = quota.next_refill(now)
                push(wakeup, "refill", None)
            schedule_retry()

        def observed(tid, index, candidate):
            done = [e for e in executions if e["done"]]
            expected = sum(e["end_s"] - e["start_s"] for e in done) / len(done) if done else 1.0
            states = []
            for task_id in self.tapes:
                if task_id in finish or task_id not in phases:
                    continue
                states.append(
                    AgentState(
                        task_id,
                        now,
                        completed[task_id],
                        phases[task_id],
                        since[task_id],
                        task_context=self.tapes[task_id]["question"],
                        history=tuple(histories[task_id][-8:]),
                        # Displayed observations are attached only after completion.
                        result_excerpt=self.tapes[task_id]["steps"][completed[task_id] - 1].get(
                            "observed_excerpt", ""
                        )
                        if completed[task_id]
                        else "",
                        intent=(
                            self.tapes[task_id]["steps"][
                                completed[task_id] + int(phases[task_id] != "thinking") - 1
                            ].get("thought")
                            or ""
                        )
                        if completed[task_id] + int(phases[task_id] != "thinking")
                        else "",
                    )
                )
            snapshot = Snapshot(
                self.capacity,
                self.window_s,
                tuple(states),
                tuple(
                    KnownExecution(
                        e["task_id"],
                        Call.search(e["query"]),
                        e["end_s"] if e["done"] else max(now, e["start_s"] + expected),
                    )
                    for e in executions
                ),
                tuple(
                    QueuedCall(t, Call.search(self.tapes[t]["steps"][i]["query"]), ready)
                    for t, i, ready in queue
                ),
                tuple(t for t in recent if t >= now - self.window_s),
            )
            return Observation(
                now,
                tid,
                completed[tid],
                Call.search(candidate["query"]),
                quota.remaining(now),
                len(queue),
                snapshot,
            )

        def decide(tid, index, candidate):
            eligible = not queue and quota.remaining(now) > 0
            if forced is not None:
                admitted = eligible and (tid, index + 1, candidate["rank"]) in forced
                overhead, details = 0.0, {"offline_forced": True}
            else:
                state = observed(tid, index, candidate)
                admitted = bool(eligible and policy.admit(state))
                overhead = float(getattr(policy, "overhead_s", 0.0)) if eligible else 0.0
                details = dict(getattr(policy, "last_decision", {})) if eligible else {}
            if not math.isfinite(overhead) or overhead < 0:
                raise ValueError("Invalid predictor overhead")
            stats["predictor_overhead_s"] += overhead
            if details.get("reason") == "Uncovered exact predictor context":
                raise ValueError("Uncovered exact predictor context; extend the frozen bank")
            decision = (tid, index, candidate, admitted, quota.window_index, details, now)
            if overhead:
                push(now + overhead, "decision", decision)
                return
            admitted = bool(
                admitted
                and active(tid, index)
                and not queue
                and quota.remaining(now) > getattr(policy, "dispatch_reserve", 0)
                and not known(tid, candidate["query"])
            )
            if record_decisions:
                decisions.append(
                    {
                        "task_id": tid,
                        "step": index + 1,
                        "rank": candidate["rank"],
                        "admitted": admitted,
                        "time_s": now,
                        "forecast": details,
                        "requested_at_s": now,
                        "post_action": current[tid] > index,
                    }
                )
            if admitted:
                stats["post_action_launches"] += current[tid] > index
                start(tid, candidate["query"], candidate["duration_s"], True, index)

        for _ in range(min(self.max_active_agents, len(workload))):
            enter(workload.popleft(), 0)
        while heap:
            at, _, _, kind, data = heapq.heappop(heap)
            if (
                kind == "refill"
                and not queue
                and not any(
                    active(tid, index, at) and not known(tid, candidate["query"])
                    for tid, index, candidate in deferred.values()
                )
            ):
                # A previously scheduled retry must not extend resource time
                # after its question has answered or its candidate was consumed.
                wakeup = None
                continue
            now = at
            task_owner = owner(kind, data)
            if task_owner is not None:
                pending[task_owner] -= 1
            if kind == "actor_done":
                tid, index = data
                current[tid] = index  # bounded candidate age controls older windows
                row = self.tapes[tid]["steps"][index]
                histories[tid].append(
                    Call.search(row["query"])
                    if row["tool"] == "search"
                    else Call(row["tool"], json.dumps({"value": row["query"]}))
                )
                log("required_ready", task_id=tid, step=index + 1, action=row["action"])
                if row["tool"] != "search":
                    phases[tid], since[tid] = "running", now
                    push(now + row["tool_duration_s"], "local_done", (tid, index))
                    continue
                recent.append(now)
                requested.add((tid, row["query"]))
                execution = cache.get((tid, row["query"]))
                if execution is not None:
                    execution["used"] = True
                    stats["cache_hits"] += 1
                    waits.append(0.0)
                    if self.generate_on_reuse:
                        generate(tid, index)
                    if execution["done"]:
                        log("result_reused", task_id=tid, step=index + 1, query=row["query"])
                        advance(tid, index)
                    else:
                        stats["inflight_hits"] += 1
                        phases[tid], since[tid] = "running", now
                        execution["waiters"].append((tid, index))
                        log("inflight_joined", task_id=tid, step=index + 1, query=row["query"])
                else:
                    phases[tid], since[tid] = "queued", now
                    if self.generation_trigger == "request":
                        generate(tid, index)
                    queue.append((tid, index, now))
                    dispatch()
            elif kind == "local_done":
                advance(*data)
            elif kind == "tool_done":
                data["done"] = True
                log(
                    "search_finished",
                    task_id=data["task_id"],
                    query=data["query"],
                    speculative=data["speculative"],
                )
                for waiter in data["waiters"]:
                    advance(*waiter)
            elif kind == "refill":
                wakeup = None
                log("quota_refilled")
                dispatch()
            elif kind == "observation_done":
                tid, index = data
                if active(tid, index):
                    stats["hypothetical_runs"] += 1
                    window = self.tapes[tid]["steps"][index]["window"]
                    push(now + window["hypothetical_duration_s"], "hypothetical_done", data)
                else:
                    stats["late_windows"] += 1
            elif kind == "hypothetical_done":
                tid, index = data
                if not active(tid, index):
                    stats["late_windows"] += 1
                    release(tid)
                    continue
                for candidate in self.tapes[tid]["steps"][index]["window"]["candidates"]:
                    if not candidate["eligible"]:
                        continue
                    if known(tid, candidate["query"]):
                        stats["duplicate_candidates_suppressed"] += 1
                        continue
                    stats["post_action_candidates"] += current[tid] > index
                    selected = forced is None or (tid, index + 1, candidate["rank"]) in forced
                    if self.retry_candidates and selected:
                        key = (tid, index, candidate["rank"])
                        deferred[key] = (tid, index, candidate)
                        if queue or quota.remaining(now) == 0:
                            stats["candidates_deferred"] += 1
                            log(
                                "candidate_deferred",
                                task_id=tid,
                                step=index + 1,
                                query=candidate["query"],
                            )
                        schedule_retry()
                    else:
                        decide(tid, index, candidate)
            elif kind == "retry_candidates":
                retry_scheduled = False
                for key, (tid, index, candidate) in list(deferred.items()):
                    if not active(tid, index) or known(tid, candidate["query"]):
                        deferred.pop(key)
                        stats["deferred_candidates_expired"] += 1
                for key, (tid, index, candidate) in list(deferred.items()):
                    if queue or quota.remaining(now) == 0:
                        break
                    deferred.pop(key)
                    if not known(tid, candidate["query"]):
                        decide(tid, index, candidate)
                if deferred and wakeup is None:
                    wakeup = quota.next_refill(now)
                    push(wakeup, "refill", None)
            elif kind == "decision":
                tid, index, candidate, admitted, window_index, details, requested_at = data
                remaining = quota.remaining(now)
                admitted = bool(
                    admitted
                    and active(tid, index)
                    and not queue
                    and remaining > getattr(policy, "dispatch_reserve", 0)
                    and (self.revalidate_reset or window_index == quota.window_index)
                    and not known(tid, candidate["query"])
                )
                if record_decisions:
                    decisions.append(
                        {
                            "task_id": tid,
                            "step": index + 1,
                            "rank": candidate["rank"],
                            "admitted": admitted,
                            "time_s": now,
                            "forecast": details,
                            "requested_at_s": requested_at,
                            "post_action": current[tid] > index,
                        }
                    )
                if admitted:
                    stats["post_action_launches"] += current[tid] > index
                    start(tid, candidate["query"], candidate["duration_s"], True, index)
            if task_owner is not None:
                release(task_owner)
        if len(finish) != len(self.tapes):
            raise ValueError("Frozen replay ended with incomplete agents")
        latency = {tid: finish[tid] - arrivals[tid] for tid in self.tapes}
        saving = list(latency.values())
        spec = [e for e in executions if e["speculative"]]
        metrics = {
            "tasks": len(self.tapes),
            "mean_completion_s": sum(saving) / len(saving),
            "p95_completion_s": percentile(saving, 0.95),
            "answer_makespan_s": max(finish.values()),
            "resource_makespan_s": now,
            "worker_makespan_s": max(worker_release_times.values()),
            "release_on_answer": self.release_on_answer,
            "search_calls": len(executions),
            "speculative_calls": len(spec),
            "unused_speculative_calls": sum(not e["used"] for e in spec),
            "required_waits_s": waits,
            "per_agent_wait_s": agent_waits,
            "mean_required_wait_s": sum(waits) / len(waits) if waits else 0.0,
            "per_agent_completion_s": latency,
            "task_start_s": arrivals,
            "task_finish_s": finish,
            "max_active_agents": min(self.max_active_agents, len(self.tapes)),
            "answers": answers,
            **stats,
            "fairness_jain_completion": sum(saving) ** 2
            / (len(saving) * sum(v * v for v in saving))
            if any(saving)
            else 1.0,
        }
        return {"metrics": metrics, "events": events, "decisions": decisions}


def recorded_candidate_options(tapes, candidate_lifetime="recorded"):
    """Do not replay fresh persistent-window recordings with legacy expiry."""
    if candidate_lifetime == "recorded":
        lifetimes = {t.get("candidate_lifetime", "next_action") for t in tapes}
        if len(lifetimes) != 1:
            raise ValueError("Mixed recorded candidate lifetimes; choose an explicit lifetime")
        candidate_lifetime = lifetimes.pop()
    if candidate_lifetime not in ("episode", "next_action"):
        raise ValueError("Unknown candidate lifetime")
    return candidate_lifetime, (
        {"max_candidate_age": 999, "suppress_known_calls": True}
        if candidate_lifetime == "episode"
        else {}
    )


def study(
    dataset,
    output,
    *,
    agents=(1, 2, 4, 8),
    capacity=3,
    window_s=10,
    seed=248,
    tool_duration_s=None,
    candidate_lifetime="recorded",
    scheduling="overlap",
    cache_required_results=False,
):
    if Path(output).exists():
        raise ValueError("Choose a fresh study directory")
    tapes = list(dataset["tapes"])
    lifetime, replay_options = recorded_candidate_options(tapes, candidate_lifetime)
    replay_options.update(scheduling_options(scheduling))
    replay_options["cache_required_results"] = cache_required_results
    random.Random(seed).shuffle(tapes)
    rows = []
    policies = {
        "no_speculation": NoSpeculation,
        "current_capacity": CurrentCapacity,
        "fixed_reserve": lambda: FixedReserve(1),
    }
    for count in agents:
        if type(count) is not int or count < 1:
            raise ValueError("Agent counts must be positive integers")
        for name, factory in policies.items():
            batches = [
                FrozenReplay(
                    tapes,
                    capacity,
                    window_s,
                    tool_duration_s=tool_duration_s,
                    max_active_agents=count,
                    **replay_options,
                ).run(factory())
            ]
            wall = sum(b["metrics"]["resource_makespan_s"] for b in batches)
            durations = [
                v for b in batches for v in b["metrics"]["per_agent_completion_s"].values()
            ]
            waiting = [w for b in batches for w in b["metrics"]["required_waits_s"]]
            rows.append(
                {
                    "agents": count,
                    "policy": name,
                    "tasks": len(tapes),
                    "resource_time_s": wall,
                    "throughput_questions_s": len(tapes) / wall,
                    "mean_completion_s": sum(durations) / len(durations),
                    "p95_completion_s": percentile(durations, 0.95),
                    "mean_required_wait_s": sum(waiting) / len(waiting) if waiting else 0,
                    "speculative_calls": sum(b["metrics"]["speculative_calls"] for b in batches),
                    "unused_speculative_calls": sum(
                        b["metrics"]["unused_speculative_calls"] for b in batches
                    ),
                    "cache_hits": sum(b["metrics"]["cache_hits"] for b in batches),
                    "batches": batches,
                }
            )
    root = Path(output)
    root.mkdir(parents=True)
    result = {
        "version": 1,
        "capacity": capacity,
        "window_s": window_s,
        "seed": seed,
        "tool_duration_override_s": tool_duration_s,
        "candidate_lifetime": lifetime,
        "scheduling": scheduling,
        "replay_options": replay_options,
        "assumptions": dataset["assumptions"]
        + [
            "Continuous closed-loop worker pool; one shared quota persists across the entire question stream",
            (
                "A worker takes its next question at answer readiness; started background work remains charged"
                if replay_options["release_on_answer"]
                else "A worker takes its next question after its previous question drains started work"
            ),
            "Unlimited model concurrency with fixed recorded single-agent durations",
            "Per-agent Search cache, shared Search quota, FIFO required ordering",
            "Answer outputs held fixed; this is not new answer-quality evidence",
        ],
        "rows": rows,
    }
    write_json(root / "study.json", result)
    lines = [
        "# Frozen shared-quota smoke study",
        "",
        "Measured durations on fixed authoritative tapes; no new model/tool calls. "
        "These exploratory results use one seed and no predictor yet.",
        "",
        "| Agents | Policy | Questions/s | Mean completion (s) | Required wait (s) | Hits | Unused |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {r['agents']} | {r['policy']} | {r['throughput_questions_s']:.4f} | {r['mean_completion_s']:.3f} | {r['mean_required_wait_s']:.3f} | {r['cache_hits']} | {r['unused_speculative_calls']} |"
        for r in rows
    ]
    lines += ["", *["- " + a for a in result["assumptions"]]]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


def scheduling_options(name):
    """Named, recorded controls keep historical studies reproducible."""
    if name not in ("legacy", "overlap"):
        raise ValueError("scheduling must be legacy or overlap")
    return {
        "generation_trigger": "request" if name == "overlap" else "dispatch",
        "retry_candidates": name == "overlap",
        "release_on_answer": name == "overlap",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capacity", type=int, default=3)
    parser.add_argument("--window-s", type=float, default=10)
    parser.add_argument("--agents", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--seed", type=int, default=248)
    parser.add_argument("--tool-duration-s", type=float)
    parser.add_argument(
        "--candidate-lifetime", choices=("recorded", "episode", "next_action"), default="recorded"
    )
    parser.add_argument("--scheduling", choices=("legacy", "overlap"), default="overlap")
    parser.add_argument("--cache-required-results", action="store_true")
    args = parser.parse_args()
    result = study(
        load_dataset(args.dataset),
        args.output,
        agents=args.agents,
        capacity=args.capacity,
        window_s=args.window_s,
        seed=args.seed,
        tool_duration_s=args.tool_duration_s,
        candidate_lifetime=args.candidate_lifetime,
        scheduling=args.scheduling,
        cache_required_results=args.cache_required_results,
    )
    print(
        json.dumps(
            [{k: v for k, v in row.items() if k != "batches"} for row in result["rows"]], indent=2
        )
    )


if __name__ == "__main__":
    main()
