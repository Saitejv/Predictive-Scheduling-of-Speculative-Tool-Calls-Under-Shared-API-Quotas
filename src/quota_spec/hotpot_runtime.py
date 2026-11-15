"""Live single-agent HotpotQA: sequential versus concurrent Search speculation.

Uses pinned upstream prompts/parser/Wikipedia tools. Every authoritative actor
call uses true observations. Only exact Search arguments can reuse a prefetch;
Lookup and Finish always execute on authoritative state. No quotas or Jev.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import statistics
import time
import types
from pathlib import Path

from .artifacts import append_json, source_hashes, write_json
from .capture import Capture, snapshot
from .telemetry import summarize_inference
from .transport import InvalidProviderResponse, LiveChat, OptionalExpired  # compatibility export
from .upstream import REVISION, load_upstream, prepare, workload_indices
from .wiki_http import WikiHTTP


class Events:
    def __init__(self, path=None, *, clock=None):
        self.clock = clock or time.perf_counter
        self.path, self.start, self.rows = path, self.clock(), []

    def emit(self, event, **fields):
        row = {"event": event, "time_s": self.clock() - self.start, **fields}
        self.rows.append(row)
        if self.path:
            append_json(self.path, row)
        return row


class WikiSearch:
    def __init__(self, module, events, *, min_interval_s=0):
        self.module, self.events = module, events
        import requests

        self.http = WikiHTTP(requests.get, interval_s=min_interval_s)

        # Isolate the dependency override to this imported upstream module.
        module.environment.requests = types.SimpleNamespace(get=self.http.get)

    async def search(self, query, episode, step, speculative=False):
        self.events.emit(
            "search_started", episode=episode, step=step, query=query, speculative=speculative
        )

        submitted = time.perf_counter()

        def fetch():
            worker_started = time.perf_counter()
            self.http.begin()
            env = self.module.environment.WikiEnv("unused")
            state_before = snapshot(env)
            env.search_step(query)
            return {
                "state_before": state_before,
                "state_after": snapshot(env),
                "queue_s": worker_started - submitted + self.http.local.pacing_s,
                "service_s": time.perf_counter() - worker_started - self.http.local.pacing_s,
                "collection_pacing_s": self.http.local.pacing_s,
                "http_backoff_s": self.http.local.backoff_s,
                "http_attempts": self.http.local.attempts,
                "http_mutex_wait_s": self.http.local.mutex_s,
                "http_network_s": self.http.local.network_s,
                "obs": env.obs,
                "page": env.page,
                "result_titles": getattr(env, "result_titles", None),
            }

        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(fetch)
            self.events.emit(
                "search_finished",
                episode=episode,
                step=step,
                query=query,
                speculative=speculative,
                duration_s=time.perf_counter() - started,
            )
            return result
        except Exception as exc:
            self.events.emit(
                "search_failed",
                episode=episode,
                step=step,
                query=query,
                speculative=speculative,
                failure=type(exc).__name__,
            )
            raise


class MockChat:
    records = ()

    async def call(self, prompt, role, episode, step):
        await asyncio.sleep(0.002 if role == "observation_speculator" else 0.004)
        if role == "observation_speculator":
            return "Mock entity has a keyword. It is a mock page."
        action = {1: "Search[Mock first]", 2: "Search[Mock second]", 3: "Lookup[keyword]"}.get(
            step, "Finish[mock answer]"
        )
        if role == "speculative_actor":
            action += ", Search[Mock wrong], Search[Mock other]"
        return f"Thought {step}: Use the evidence.\nAction {step}: {action}"


class MockSearch:
    def __init__(self, events):
        self.events = events

    async def search(self, query, episode, step, speculative=False):
        self.events.emit(
            "search_started", episode=episode, step=step, query=query, speculative=speculative
        )
        started = time.perf_counter()
        await asyncio.sleep(0.03)
        self.events.emit(
            "search_finished",
            episode=episode,
            step=step,
            query=query,
            speculative=speculative,
            duration_s=0.03,
        )
        return {
            "obs": "A mock keyword article.",
            "page": "A mock keyword article.",
            "result_titles": None,
            "service_s": time.perf_counter() - started,
            "queue_s": 0.0,
            "state_before": {"page": None, "obs": None, "steps": 0, "answer": None},
            "state_after": {
                "page": "A mock keyword article.",
                "obs": "A mock keyword article.",
                "steps": 0,
                "answer": None,
            },
        }


class Runtime:
    def __init__(
        self,
        module,
        chat,
        search,
        events,
        base_prompt,
        max_steps=7,
        capture=None,
        *,
        clock=None,
        local_step=None,
        candidate_lifetime="episode",
        coordinator=None,
        speculative_width=3,
        model_retries=0,
        max_generation_step=None,
    ):
        self.module, self.chat, self.search, self.events = module, chat, search, events
        self.base_prompt, self.max_steps = base_prompt, max_steps
        self.parser = module.HotPotQARun.__new__(module.HotPotQARun)
        self.capture = capture
        self.generations = {}
        self.clock = clock or time.perf_counter
        self.local_step = local_step
        if candidate_lifetime not in ("episode", "next_action"):
            raise ValueError("candidate_lifetime must be episode or next_action")
        self.candidate_lifetime = candidate_lifetime
        self.coordinator = coordinator
        if speculative_width not in (1, 3):
            raise ValueError("speculative_width must be 1 or 3")
        self.speculative_width = speculative_width
        self.model_retries = model_retries
        if max_generation_step is not None and (
            type(max_generation_step) is not int or max_generation_step < 0
        ):
            raise ValueError("Generation step budget must be a nonnegative integer")
        self.max_generation_step = max_generation_step

    async def model(self, prompt, role, episode, step, dependencies=()):
        import httpx

        for attempt in range(self.model_retries + 1):
            try:
                if self.capture:
                    return await self.capture.model(
                        self.chat, prompt, role, episode, step, dependencies
                    )
                return await self.chat.call(prompt, role, episode, step), None
            except (httpx.HTTPStatusError, httpx.TransportError, InvalidProviderResponse) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if attempt == self.model_retries or (
                    status is not None and status not in (429, 502, 503, 504)
                ):
                    raise
                self.events.emit(
                    "inference_retry",
                    episode=episode,
                    step=step,
                    role=role,
                    attempt=attempt + 1,
                    http_status=status,
                )
                await asyncio.sleep(0.2 * 2**attempt)

    async def search_call(self, query, episode, step, speculative=False, dependencies=()):
        if self.capture:
            return await self.capture.search(
                self.search, query, episode, step, speculative, dependencies
            )
        return await self.search.search(query, episode, step, speculative)

    def record(
        self,
        kind,
        episode,
        step,
        dependencies=(),
        inputs=None,
        output=None,
        branch="authoritative",
        **fields,
    ):
        if self.capture:
            return self.capture.instant(
                kind, episode, step, branch, dependencies, inputs, output, **fields
            )
        return None

    async def generate(self, prefix, step, width, role, episode, dependencies=()):
        prompt = prefix + self.module.PromptTemplates.ACTION_GUESS_PROMPT.format(
            i=step, num_guesses=width
        )
        content, node = await self.model(prompt, role, episode, step, dependencies)
        attempts = [node] if node else []
        thought, actions = self.parser.separate_thought_and_actions(step, content)
        for attempt in range(1, (1 if role == "actor" else 3) + 1):
            if actions:
                break
            retry = prefix + self.module.PromptTemplates.RETRY_PROMPT.format(
                attempt=attempt, role=self.module.constants.agent_role, num_guesses=width
            )
            response, node = await self.model(retry, role, episode, step, [node])
            if node:
                attempts.append(node)
            actions = self.parser.extract_actions(response)
        if not actions:
            raise ValueError("No action after upstream retry budget")
        self.generations[(episode, role, step)] = self.record(
            "generation",
            episode,
            step,
            [node],
            {"prefix": prefix, "width": width, "role": role, "attempts": attempts},
            {"thought": thought, "actions": actions[:width], "all_parsed_actions": actions},
            branch=role,
        )
        return thought, actions[:width]

    @staticmethod
    def apply_search(env, result):
        # A failed exact-page search preserves the authoritative prior page and
        # lookup cursor, just as upstream search_step does.
        if result["page"] is not None:
            env.page = result["page"]
            env.lookup_keyword = env.lookup_list = env.lookup_cnt = None
        if result.get("result_titles") is not None:
            env.result_titles = result["result_titles"]
        env.obs = result["obs"]
        env.steps += 1

    async def episode(self, index, question, answer, mode, backend="http"):
        episode = f"{index}:{mode}"
        env = self.module.environment.WikiEnv("unused")
        prefix = self.base_prompt + "Question: " + question + "\n"
        cache, windows, window_tasks, trajectory = {}, [], [], []
        requested_queries = set()
        actor_phase = {"step": 0, "thinking": False}
        stats = {
            "cache_hits": 0,
            "inflight_hits": 0,
            "prefetches": 0,
            "late_windows": 0,
            "optional_failures": 0,
            "prefetches_while_actor_thinking": 0,
            "duplicate_candidates_suppressed": 0,
            "generation_windows_suppressed": 0,
        }
        self.events.emit(
            "episode_started", episode=episode, mode=mode, question_index=index, question=question
        )
        started, failure = self.clock(), None
        previous = self.record(
            "episode_start",
            episode,
            0,
            inputs={"question": question, "mode": mode},
            output=snapshot(env),
        )
        step_captures = []

        async def speculate(window, old_prefix, thought, action, step, query, boundary):
            try:
                prediction, prediction_node = await self.model(
                    self.module.PromptTemplates.GUESS_STEP_PROMPT.format(query),
                    "observation_speculator",
                    episode,
                    step,
                    [boundary],
                )
                if not window["valid"]:
                    stats["late_windows"] += 1
                    return
                obs = self.module.environment.WikiEnv.get_page_obs(prediction).replace("\n", "")
                hypothetical = old_prefix + self.module.PromptTemplates.NEXT_STEP_PROMPT.format(
                    i=step, thought=thought, action=action, obs=obs
                )
                _, candidates = await self.generate(
                    hypothetical,
                    step + 1,
                    self.speculative_width,
                    "speculative_actor",
                    episode,
                    [prediction_node],
                )
                self.events.emit(
                    "candidates_ready",
                    episode=episode,
                    step=step + 1,
                    actions=candidates,
                    on_time=window["valid"],
                    actor_thinking=actor_phase["thinking"],
                    actor_step=actor_phase["step"],
                    candidate_lifetime=self.candidate_lifetime,
                )
                candidates_node = self.record(
                    "candidates",
                    episode,
                    step + 1,
                    [self.generations[(episode, "speculative_actor", step + 1)]],
                    {"boundary": boundary},
                    {
                        "actions": candidates,
                        "on_time": window["valid"],
                        "actor_thinking": actor_phase["thinking"],
                        "actor_step": actor_phase["step"],
                        "candidate_lifetime": self.candidate_lifetime,
                    },
                    branch="hypothetical",
                )
                if not window["valid"]:
                    stats["late_windows"] += 1
                    return

                async def launch(candidate):
                    parsed = split_action(candidate)
                    if parsed[0] != "search":
                        return
                    guessed_query = parsed[1]
                    # Don't turn the already-running required call into a free
                    # generic cache entry for the next step.
                    if (
                        guessed_query == query
                        or guessed_query in cache
                        or (
                            self.candidate_lifetime == "episode"
                            and guessed_query in requested_queries
                        )
                    ):
                        stats["duplicate_candidates_suppressed"] += 1
                        return
                    if self.coordinator:

                        def valid():
                            return (
                                window["valid"]
                                and guessed_query not in cache
                                and guessed_query not in requested_queries
                            )

                        if not await self.coordinator.admit_candidate(
                            episode, guessed_query, valid
                        ):
                            return
                        # No suspension between final validation, quota claim and
                        # cache installation. Required work can advance while the
                        # forecast runs and must never join an unadmitted draft.
                        if not valid() or not self.coordinator.claim_candidate(
                            episode, guessed_query
                        ):
                            return
                    cache[guessed_query] = asyncio.create_task(
                        self.search_call(guessed_query, episode, step + 1, True, [candidates_node])
                    )
                    stats["prefetches"] += 1
                    stats["prefetches_while_actor_thinking"] += actor_phase["thinking"]
                    self.events.emit(
                        "prefetch_launched",
                        episode=episode,
                        step=step + 1,
                        query=guessed_query,
                        source_step=step,
                        actor_step=actor_phase["step"],
                        actor_thinking=actor_phase["thinking"],
                    )

                await asyncio.gather(*(launch(candidate) for candidate in candidates))
            except OptionalExpired:
                stats["late_windows"] += 1
                self.events.emit("optional_expired_unsent", episode=episode, step=step)
            except Exception as exc:
                stats["optional_failures"] += 1
                self.events.emit(
                    "optional_failed", episode=episode, step=step, failure=type(exc).__name__
                )

        try:
            for step in range(1, self.max_steps + 1):
                actor_phase.update(step=step, thinking=True)
                self.events.emit("actor_started", episode=episode, step=step)
                thought, actions = await self.generate(
                    prefix, step, 1, "actor", episode, [previous]
                )
                actor_phase["thinking"] = False
                self.events.emit("actor_completed", episode=episode, step=step)
                # Thinking never expires a window. The legacy option expires at
                # the returned action; the current mode retains it until answer.
                if self.candidate_lifetime == "next_action":
                    for window in windows:
                        window["valid"] = False
                action = actions[0]
                tool, value = split_action(action)
                self.events.emit(
                    "required_action", episode=episode, step=step, action=action, thought=thought
                )
                actor_node = self.generations[(episode, "actor", step)]
                boundary = self.record(
                    "boundary",
                    episode,
                    step,
                    [actor_node],
                    {"prefix": prefix, "thought": thought, "action": action},
                    snapshot(env),
                )
                state_before = snapshot(env)
                wait_started = self.clock()
                result = None
                if tool == "search":
                    requested_queries.add(value)
                hit = tool == "search" and value in cache
                if hit:
                    pending = cache[value]
                    joined = not pending.done()
                    stats["inflight_hits"] += int(joined)
                    try:
                        result = await pending
                        stats["cache_hits"] += 1
                        self.events.emit(
                            "cache_joined" if joined else "cache_reused",
                            episode=episode,
                            step=step,
                            query=value,
                            requested_at_s=wait_started - self.events.start,
                        )
                    except Exception:
                        hit = False
                        self.events.emit("cache_failed", episode=episode, step=step, query=value)
                if tool == "search":
                    if not hit:
                        required = asyncio.create_task(
                            self.search_call(value, episode, step, False, [boundary])
                        )
                        if mode == "speculative" and step < self.max_steps:
                            if (
                                self.max_generation_step is not None
                                and step > self.max_generation_step
                            ):
                                stats["generation_windows_suppressed"] += 1
                            else:
                                window = {"valid": True}
                                windows.append(window)
                                window_tasks.append(
                                    asyncio.create_task(
                                        speculate(
                                            window, prefix, thought, action, step, value, boundary
                                        )
                                    )
                                )
                        result = await required
                    self.apply_search(env, result)
                    obs, done = env.obs, False
                else:
                    local_started = self.clock()
                    if self.local_step is None:
                        obs, _, done, _ = env.step(tool + "[" + value + "]")
                    else:
                        obs, _, done, _ = await self.local_step(env, action, step)
                    local_service = self.clock() - local_started
                tool_wait_s = self.clock() - wait_started
                if self.coordinator:
                    self.events.emit(
                        "tool_observed",
                        episode=episode,
                        step=step,
                        action=action,
                        observation=obs,
                        done=done,
                    )
                previous = self.record(
                    "application",
                    episode,
                    step,
                    [boundary]
                    + ([result["capture_node"]] if result and "capture_node" in result else []),
                    {"state_before": state_before, "action": action, "prefetch_hit": hit},
                    {"state_after": snapshot(env), "observation": obs, "done": done},
                    tool_wait_s=tool_wait_s,
                    local_service_s=local_service if tool != "search" else None,
                )
                if self.capture:
                    step_captures.append(
                        {
                            "episode": episode,
                            "step": step,
                            "boundary": boundary,
                            "actor": actor_node,
                            "application": previous,
                            "search": result.get("capture_node") if result else None,
                            "tool": tool,
                            "query": value,
                            "prefetch_hit": hit,
                        }
                    )
                obs = obs.replace("\\n", "")
                trajectory.append(
                    {
                        "step": step,
                        "thought": thought,
                        "action": action,
                        "observation": obs,
                        "tool_wait_s": tool_wait_s,
                        "prefetch_hit": hit,
                    }
                )
                prefix += self.module.PromptTemplates.NEXT_STEP_PROMPT.format(
                    i=step, thought=thought, action=action, obs=obs
                )
                if done:
                    break
            if env.answer is None:
                forced_before = snapshot(env)
                env.step("finish[]")
                previous = self.record(
                    "forced_finish",
                    episode,
                    self.max_steps,
                    [previous],
                    forced_before,
                    snapshot(env),
                )
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        actor_phase["thinking"] = False
        answer_at = self.clock()
        completion_s = answer_at - started
        for window in windows:
            window["valid"] = False
        self.events.emit(
            "answer_ready",
            episode=episode,
            completion_s=completion_s,
            failure=failure,
            time_s=answer_at - self.events.start,
        )
        answer_node = self.record(
            "answer",
            episode,
            len(trajectory),
            [previous],
            output={"answer": env.answer, "state": snapshot(env)},
        )
        # Drain rather than cancel paid requests: account for every billed branch
        # and prevent leftover work from contaminating the next paired run.
        await asyncio.gather(*window_tasks, return_exceptions=True)
        await asyncio.gather(*cache.values(), return_exceptions=True)
        stats["optional_failures"] += sum(f.exception() is not None for f in cache.values())
        drained_at = self.clock()
        resource_s = drained_at - started
        used = {split_action(r["action"])[1] for r in trajectory if r["prefetch_hit"]}
        stats["unused_prefetches"] = len(set(cache) - used)
        em = self.module.wrappers.normalize_answer(
            env.answer or ""
        ) == self.module.wrappers.normalize_answer(answer)
        f1 = self.module.wrappers.f1_score(env.answer or "", answer)[0]
        row = {
            "backend": backend,
            "episode": episode,
            "question_index": index,
            "mode": mode,
            "question": question,
            "answer": env.answer,
            "reference_answer": answer,
            "failure": failure,
            "completion_s": completion_s,
            "resource_s": resource_s,
            "drain_s": resource_s - completion_s,
            "timing_version": 1,
            "started_at_s": started - self.events.start,
            "answer_at_s": answer_at - self.events.start,
            "drained_at_s": drained_at - self.events.start,
            "candidate_lifetime": self.candidate_lifetime,
            "trajectory": trajectory,
            **stats,
            "em": float(em) if backend == "http" and failure is None else None,
            "f1": f1 if backend == "http" and failure is None else None,
            "forced_finish": bool(
                trajectory and split_action(trajectory[-1]["action"])[0] != "finish"
            ),
        }
        self.events.emit(
            "episode_drained",
            episode=episode,
            resource_s=resource_s,
            time_s=drained_at - self.events.start,
            **stats,
        )
        if self.capture:
            all_work = [
                n["id"]
                for n in self.capture.nodes
                if n["episode"] == episode and n["kind"] in ("model", "search")
            ]
            self.record("drain", episode, len(trajectory), [answer_node] + all_work, output=row)
            append_json(
                self.capture.output / "steps.jsonl", {"episode": episode, "steps": step_captures}
            )
        return row


def split_action(action):
    # Preserve arguments exactly, including case and whitespace. The upstream
    # agreement scorer is case-insensitive; executable cache identity is not.
    boundary = action.index("[")
    return action[:boundary].lower(), action[boundary + 1 : -1]


def measurement_protocol(backend, interval_s=0.0):
    """Describe the actual submission regime separately from Search quotas."""
    if not math.isfinite(interval_s) or interval_s < 0:
        raise ValueError("Request interval must be finite and nonnegative")
    applied = interval_s if backend == "http" else 0.0
    return {
        "backend": backend,
        "shared_model_submission_interval_s": applied,
        "kind": "mock"
        if backend == "mock"
        else "paced_model_submission"
        if applied
        else "unpaced_model_submission",
        "actor_and_optional_requests_share_pacing": bool(applied),
        "wall_time_note": "Mock service durations; no live inference"
        if backend == "mock"
        else "Includes contention at the shared model submission gate; do not compare directly with an unpaced live benchmark"
        if applied
        else "No artificial local model submission pacing; provider/network variability remains",
    }


def validate_run_protocol(backend, interval_s, purpose):
    """Keep paced evidence collection separate from an unpaced speed benchmark."""
    if purpose not in ("benchmark", "capture"):
        raise ValueError("Purpose must be benchmark or capture")
    protocol = measurement_protocol(backend, interval_s)
    if purpose == "benchmark" and protocol["actor_and_optional_requests_share_pacing"]:
        raise ValueError(
            "A speed benchmark cannot share artificial submission pacing between actor and "
            "speculation. Remove --min-request-interval-s, or explicitly use --purpose capture."
        )
    return {**protocol, "purpose": purpose}


def paired_summary(rows, records, *, protocol=None):
    result = {
        "episodes": len(rows),
        "by_mode": {},
        "live_execution": bool(rows) and all(r["backend"] == "http" for r in rows),
        "no_quotas_or_jev": True,
        "limitations": [
            "Independent stochastic actor trajectories; paired by question, not identical action tapes",
            f"One {len({r['question_index'] for r in rows})}-question pass; timing includes provider/network variation",
            "Search-only speculation; stateful Lookup/Finish are authoritative local actions",
        ],
    }
    for mode in ("sequential", "speculative"):
        values = [r for r in rows if r["mode"] == mode and r["failure"] is None]
        times = sorted(r["completion_s"] for r in values)
        result["by_mode"][mode] = {
            "complete": len(values),
            "failures": sum(r["failure"] is not None for r in rows if r["mode"] == mode),
            "mean_s": statistics.mean(times) if times else None,
            "median_s": statistics.median(times) if times else None,
            "p95_s": times[max(0, math.ceil(0.95 * len(times)) - 1)] if times else None,
            "answer_time_total_s": sum(times),
            "resource_time_total_s": sum(r["resource_s"] for r in values),
            "mean_actions": statistics.mean(len(r["trajectory"]) for r in values)
            if values
            else None,
            "em": statistics.mean(r["em"] for r in values)
            if values and all(r["em"] is not None for r in values)
            else None,
            "f1": statistics.mean(r["f1"] for r in values)
            if values and all(r["f1"] is not None for r in values)
            else None,
            **{
                key: sum(r[key] for r in values)
                for key in (
                    "cache_hits",
                    "inflight_hits",
                    "prefetches",
                    "unused_prefetches",
                    "late_windows",
                    "optional_failures",
                )
            },
            "usage": summarize_inference(r for r in records if r["episode"].endswith(":" + mode)),
        }
    pairs = []
    for index in dict.fromkeys(r["question_index"] for r in rows):
        match = {
            r["mode"]: r for r in rows if r["question_index"] == index and r["failure"] is None
        }
        if len(match) == 2:
            seq, spec = match["sequential"], match["speculative"]
            pairs.append(
                {
                    "question_index": index,
                    "sequential_s": seq["completion_s"],
                    "speculative_s": spec["completion_s"],
                    "saving_s": seq["completion_s"] - spec["completion_s"],
                    "same_actions": [r["action"] for r in seq["trajectory"]]
                    == [r["action"] for r in spec["trajectory"]],
                }
            )
    rng = random.Random(248)
    boot = (
        sorted(statistics.mean(rng.choice(pairs)["saving_s"] for _ in pairs) for _ in range(5000))
        if pairs
        else []
    )
    seq_total = sum(r["sequential_s"] for r in pairs)
    spec_total = sum(r["speculative_s"] for r in pairs)
    result["paired"] = {
        "questions": len(pairs),
        "pairs": pairs,
        "mean_saving_s": statistics.mean(r["saving_s"] for r in pairs) if pairs else None,
        "bootstrap_95_mean_saving_s": [boot[124], boot[4874]] if boot else None,
        "relative_total_time_saved": (seq_total - spec_total) / seq_total if seq_total else None,
        "identical_action_pairs": sum(r["same_actions"] for r in pairs),
    }
    result["usage"] = summarize_inference(records)
    if protocol is not None:
        result["measurement_protocol"] = protocol
    return result


async def run(args):
    if args.output.exists():
        raise ValueError("Choose a fresh output directory")
    if not math.isfinite(args.max_usd) or args.max_usd <= 0 or args.max_requests <= 0:
        raise ValueError("Use positive finite dollar and request budgets")
    protocol = validate_run_protocol(
        args.backend,
        getattr(args, "min_request_interval_s", 0.0),
        getattr(args, "purpose", "benchmark"),
    )
    candidate_lifetime = getattr(args, "candidate_lifetime", "episode")
    if candidate_lifetime not in ("episode", "next_action"):
        raise ValueError("candidate_lifetime must be episode or next_action")
    protocol["candidate_lifetime"] = candidate_lifetime
    protocol["inference_slots"] = (
        {"total": 4, "reserved_for_actor": 1} if args.backend == "http" else None
    )
    indices = workload_indices(args.count, getattr(args, "offset", 0))
    key = os.environ.get("OPENROUTER_API_KEY")
    if args.backend == "http" and not key:
        raise ValueError("Set OPENROUTER_API_KEY")
    root = prepare(args.source)
    output = args.output.resolve()
    output.mkdir(parents=True)
    (output / "tasks").mkdir()
    sources = output / "source-snapshot"
    sources.mkdir()
    package_root = Path(__file__).resolve().parent
    for name in source_hashes():
        (sources / name).write_bytes((package_root / name).read_bytes())

    class NoSyncClient:
        def __init__(self, **kwargs):
            pass

        def call(self, *a, **kw):
            raise AssertionError("All inference must use the audited async transport")

    module = load_upstream(root, NoSyncClient)
    examples = json.loads((root / "hotpotqa/prompts/prompts_naive.json").read_text())[
        "webthink_simple6"
    ]
    base = module.Utils.join_prompt(
        module.PromptTemplates.REACT_INSTRUCTION,
        examples,
        module.PromptTemplates.PROMPT_INSTRUCTION,
    )
    data = json.loads((root / "hotpotqa/data/hotpot_dev_v1_simplified.json").read_text())
    events = Events(output / "events.jsonl")
    capture = Capture(output / "capture", events.start)

    write_json(
        output / "config.json",
        {
            "capture_version": 2,
            "offset": getattr(args, "offset", 0),
            "backend": args.backend,
            "purpose": protocol["purpose"],
            "candidate_lifetime": candidate_lifetime,
            "actor": args.actor,
            "speculator": args.speculator,
            "indices": indices,
            "width": 3,
            "max_steps": 7,
            "max_usd": args.max_usd,
            "max_requests": args.max_requests,
            "request_timeout_s": getattr(args, "request_timeout_s", 180),
            "min_request_interval_s": getattr(args, "min_request_interval_s", 0.0),
            "measurement_protocol": protocol,
            "upstream": json.loads((root / "upstream.json").read_text()),
            "source_sha256": source_hashes(),
            "runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "comparison": "Live autonomous paired-question runs; alternate sequential/speculative order",
            "cache_identity": "Exact case-sensitive Search argument; no Lookup/Finish caching",
            "timing": "Answer readiness and full resource drain are reported separately",
            "speculation": "Uncached required Search opens a window; generation and prefetch overlap actor thinking; episode windows persist until answer; already requested queries are suppressed"
            if candidate_lifetime == "episode"
            else "Legacy windows expire when the next actor returns its action",
        },
    )
    import httpx

    async with httpx.AsyncClient(timeout=getattr(args, "request_timeout_s", 180)) as client:
        if args.backend == "http":
            response = await client.get("https://openrouter.ai/api/v1/models")
            response.raise_for_status()
            prices = {m["id"]: m["pricing"] for m in response.json()["data"]}
            write_json(output / "pricing.json", prices)
            chat = LiveChat(
                client,
                key,
                prices,
                output,
                events,
                args.max_usd,
                args.max_requests,
                args.actor,
                args.speculator,
                min_request_interval_s=getattr(args, "min_request_interval_s", 0.0),
            )
            search = WikiSearch(module, events)
        else:
            chat, search = MockChat(), MockSearch(events)
        runtime = Runtime(
            module,
            chat,
            search,
            events,
            base,
            capture=capture,
            candidate_lifetime=candidate_lifetime,
        )
        rows = []
        for position, index in enumerate(indices):
            modes = (
                ("sequential", "speculative")
                if position % 2 == 0
                else ("speculative", "sequential")
            )
            for mode in modes:
                row = await runtime.episode(
                    index, data[index]["question"], data[index]["answer"], mode, args.backend
                )
                rows.append(row)
                write_json(output / "tasks" / f"{index}-{mode}.json", row)
                write_json(
                    output / "summary.json", paired_summary(rows, chat.records, protocol=protocol)
                )
                print(
                    f"{position + 1}/{args.count} {mode} {index}: {row['completion_s']:.3f}s, hits={row['cache_hits']}, failure={row['failure']}",
                    flush=True,
                )
                if row["failure"] or (isinstance(chat, LiveChat) and chat.unknown):
                    capture.seal()
                    return paired_summary(rows, chat.records, protocol=protocol)
        summary = paired_summary(rows, chat.records, protocol=protocol)
        write_json(output / "summary.json", summary)
        capture.seal()
        return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("mock", "http"), default="mock")
    p.add_argument("--purpose", choices=("benchmark", "capture"), default="benchmark")
    p.add_argument("--candidate-lifetime", choices=("episode", "next_action"), default="episode")
    p.add_argument("--source", type=Path, default=Path("data/raw/speculative-action") / REVISION)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--actor", default="google/gemini-2.5-flash")
    p.add_argument("--speculator", default="openai/gpt-4.1-nano")
    p.add_argument("--max-usd", type=float, default=0.5)
    p.add_argument("--max-requests", type=int, default=800)
    p.add_argument("--request-timeout-s", type=float, default=180)
    p.add_argument("--min-request-interval-s", type=float, default=0.0)
    summary = asyncio.run(run(p.parse_args()))
    print(json.dumps(summary, indent=2))
    if any(r["failures"] for r in summary["by_mode"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
