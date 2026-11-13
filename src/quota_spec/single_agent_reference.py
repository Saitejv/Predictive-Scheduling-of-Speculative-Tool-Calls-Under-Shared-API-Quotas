"""Single-agent upstream check: original chess analysis + real Hotpot async runtime.

Offline only. Does not substitute a shared-quota simulator for a single agent.
The asyncio clock advances recorded service time without sleeping in wall time;
all prompts/responses and tool results are loaded from immutable saved evidence.
"""

import argparse
import ast
import asyncio
import copy
import hashlib
import json
import math
import socket
import statistics
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from .artifacts import write_json
from .capture import CaptureStore
from .capture_audit import load_module
from .frozen_replay import FrozenReplay, load_dataset
from .hotpot_runtime import Events, Runtime
from .policies import CurrentCapacity, NoSpeculation
from .speculation_audit import unlimited_reference
from .upstream import REVISION


class ServiceTimeLoop(asyncio.SelectorEventLoop):
    """Validation-only asyncio loop; preserve coroutine/timer scheduling order.

    Advance to the next timer only when no task is runnable. No network, threads,
    provider queues, serving limits or new requests are allowed in this adapter.
    """

    def __init__(self):
        self.service_time_s = 0.0
        super().__init__()

    def time(self):
        return self.service_time_s

    def _run_once(self):
        if not self._ready and self._scheduled:
            self.service_time_s = max(self.service_time_s, self._scheduled[0]._when)
        super()._run_once()


def original_chess_analysis(checkout):
    """Compile the unchanged authors' function, avoiding unrelated SDK imports."""
    path = Path(checkout) / "chess-game/guess_analysis.py"
    tree = ast.parse(path.read_text())
    function = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "analyze_with_truncation"
    )
    namespace = {"Dict": Dict, "List": List, "Any": Any, "CONFIDENCE_THRESHOLD": 50.0}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["analyze_with_truncation"]


def chess_reference(steps, horizon=30):
    """Independent two-consecutive-calls recurrence, including the final tail."""
    steps = list(steps.values())[:horizon]
    baseline = sum(s["time_taken_current_agent"] for s in steps)
    elapsed, index, blocks = 0.0, 0, []
    while index < len(steps):
        s = steps[index]
        hit = index + 1 < len(steps) and s["current_move"] in s["guessed_moves"]
        if hit:
            duration = max(
                s["time_taken_current_agent"],
                s["guess_prediction_time"] + steps[index + 1]["time_taken_current_agent"],
            )
            width = 2
        else:
            duration = s["time_taken_current_agent"]
            width = 1
        blocks.append(
            {
                "first_step": index + 1,
                "steps": width,
                "start_s": elapsed,
                "duration_s": duration,
                "hit": hit,
            }
        )
        elapsed += duration
        index += width
    return {"sequential_s": baseline, "speculative_s": elapsed, "blocks": blocks}


def persistent_reference(tape):
    """Independent scalar calculation for episode retention and duplicate checks.

    Generation runs during required tools AND actor messages. Cache entries are
    future completion times; ordinary required results are not cache entries.
    """
    now, pending, cache, requested, hits = 0.0, [], {}, set(), 0
    for row in tape["steps"]:
        ready = now + row["actor_duration_s"]
        later = []
        for at, candidates in sorted(pending, key=lambda item: item[0]):
            if at >= ready:
                later.append((at, candidates))
                continue
            for candidate in candidates:
                query = candidate["query"]
                if candidate["eligible"] and query not in cache and query not in requested:
                    cache[query] = at + candidate["duration_s"]
        pending = later
        hit = row["tool"] == "search" and row["query"] in cache
        if row["tool"] == "search":
            requested.add(row["query"])
        if hit:
            hits += 1
            now = max(ready, cache[row["query"]])
        else:
            now = ready + row["tool_duration_s"]
            if row["tool"] == "search" and row["window"]:
                w = row["window"]
                pending.append(
                    (
                        ready + w["observation_duration_s"] + w["hypothetical_duration_s"],
                        w["candidates"],
                    )
                )
    return {"completion_s": now, "cache_hits": hits}


class SavedEpisode:
    def __init__(self, dataset, tape, module, loop, events):
        self.tape, self.module, self.loop, self.events = tape, module, loop, events
        base = Path(dataset) / "parts" / tape["shard"] if "shard" in tape else Path(dataset)
        self.stores = {
            "live": CaptureStore(base / "live-capture"),
            "bank": CaptureStore(base / "completion"),
        }
        self.calls = {}
        first = self.stores["live"].by_id[tape["steps"][0]["actor_node"]]
        prefix = self.stores["live"].blob(first["input"])["prefix"]
        suffix = "Question: " + tape["question"] + "\n"
        if not prefix.endswith(suffix):
            raise ValueError("Frozen first actor prefix does not match question")
        self.base_prompt = prefix[: -len(suffix)]

    def generation(self, role, step):
        if role == "actor":
            row = self.tape["steps"][step - 1]
            store = self.stores["live"]
            generation = store.by_id[row["actor_node"]]
            duration = row["actor_duration_s"]
        else:
            w = self.tape["steps"][step - 2]["window"]
            store = self.stores[w["hypothetical_store"]]
            generation = store.by_id[w["hypothetical_node"]]
            duration = w["hypothetical_duration_s"]
        inputs = store.blob(generation["input"])
        attempts = [store.by_id[n] for n in inputs["attempts"]]
        tail = duration - sum(n["service_s"] for n in attempts)
        if tail < -1e-8:
            raise ValueError("Generation duration smaller than saved model attempts")
        return store, attempts, max(0, tail)

    async def call(self, prompt, role, episode, step):
        if role == "observation_speculator":
            w = self.tape["steps"][step - 1]["window"]
            store = self.stores[w["observation_store"]]
            node = store.by_id[w["observation_node"]]
            duration = w["observation_duration_s"]
        else:
            store, attempts, tail = self.generation(role, step)
            key = role, step
            offset = self.calls.get(key, 0)
            self.calls[key] = offset + 1
            if offset >= len(attempts):
                raise ValueError("Unrecorded model retry; no online fallback")
            node = attempts[offset]
            duration = node["service_s"] + (tail if offset == len(attempts) - 1 else 0)
        expected = store.blob(node["input"])["prompt"]
        if prompt != expected:
            raise ValueError(f"Exact saved prompt mismatch: {self.tape['task_id']}/{role}/{step}")
        await asyncio.sleep(duration)
        return store.blob(node["output"])["content"]

    async def search(self, query, episode, step, speculative=False):
        if speculative:
            w = self.tape["steps"][step - 2]["window"]
            c = next(c for c in w["candidates"] if c["eligible"] and c["query"] == query)
            duration, reference = c["duration_s"], c["result"]
        else:
            row = self.tape["steps"][step - 1]
            if row["tool"] != "search" or row["query"] != query:
                raise ValueError("Wrong required Search identity")
            duration, reference = row["tool_duration_s"], row["tool_result"]
        self.events.emit(
            "search_started", episode=episode, step=step, query=query, speculative=speculative
        )
        await asyncio.sleep(duration)
        self.events.emit(
            "search_finished",
            episode=episode,
            step=step,
            query=query,
            speculative=speculative,
            duration_s=duration,
        )
        return copy.deepcopy(self.stores[reference["store"]].blob(reference["blob"]))

    async def local_step(self, env, action, step):
        row = self.tape["steps"][step - 1]
        if action != row["action"] or row["tool"] == "search":
            raise ValueError("Wrong authoritative local action")
        result = env.step(row["tool"] + "[" + row["query"] + "]")
        await asyncio.sleep(row["tool_duration_s"])
        return result


def play_runtime(dataset, tape, module, mode, *, candidate_lifetime="next_action"):
    loop = ServiceTimeLoop()
    try:
        events = Events(clock=loop.time)
        saved = SavedEpisode(dataset, tape, module, loop, events)
        runtime = Runtime(
            module,
            saved,
            saved,
            events,
            saved.base_prompt,
            clock=loop.time,
            local_step=saved.local_step,
            candidate_lifetime=candidate_lifetime,
        )
        result = loop.run_until_complete(
            runtime.episode(int(tape["task_id"]), tape["question"], tape["answer"], mode, "saved")
        )
        if result["failure"]:
            raise AssertionError(result["failure"])
        if result["optional_failures"]:
            raise AssertionError("Saved speculative prompt/response playback failed")
        if result["answer"] != tape["answer"]:
            raise AssertionError("Saved answer changed")
        if [r["action"] for r in result["trajectory"]] != [s["action"] for s in tape["steps"]]:
            raise AssertionError("Authoritative path changed")
        return {"result": result, "events": events.rows, "model_generations": saved.calls}
    finally:
        loop.close()


def run(
    output,
    dataset="results/hotpot-dataset-50",
    checkout="tmp/speculative-action-upstream",
    *,
    candidate_lifetime="episode",
    search_scale=1.0,
):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    if candidate_lifetime not in ("episode", "next_action"):
        raise ValueError("Invalid candidate lifetime")
    if not math.isfinite(search_scale) or search_scale <= 0:
        raise ValueError("Search scale must be positive and finite")
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    pristine = (
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "diff",
                "--quiet",
                REVISION,
                "--",
                "chess-game/guess_analysis.py",
                "chess-game/trajectories/sample_trajectories",
            ],
            check=False,
        ).returncode
        == 0
    )
    if revision != REVISION or not pristine:
        raise ValueError("Original chess code and samples must match the pinned revision")
    output.mkdir(parents=True)
    tapes = load_dataset(dataset)["tapes"]
    for tape in tapes:
        for row in tape["steps"]:
            if row["tool"] == "search":
                row["tool_duration_s"] *= search_scale
            if row["window"]:
                for candidate in row["window"]["candidates"]:
                    if candidate["eligible"]:
                        candidate["duration_s"] *= search_scale
    module = load_module(Path("data/raw/speculative-action") / REVISION)
    chess, hotpot = [], []
    analyze = original_chess_analysis(checkout)
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network forbidden")),
    ):
        for path in sorted(
            (Path(checkout) / "chess-game/trajectories/sample_trajectories").glob("*/*guess_3.json")
        ):
            steps = json.loads(path.read_text())
            original = analyze(steps, 30)
            independent = chess_reference(steps)
            assert abs(original["time_regular"] - independent["sequential_s"]) < 1e-8
            assert abs(original["time_speculate"] - independent["speculative_s"]) < 1e-8
            chess.append(
                {
                    "file": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "original": original,
                    "independent": independent,
                }
            )
        for tape in tapes:
            row = {"task_id": tape["task_id"]}
            for mode, policy in [
                ("sequential", NoSpeculation()),
                ("speculative", CurrentCapacity()),
            ]:
                playback = play_runtime(
                    dataset, tape, module, mode, candidate_lifetime=candidate_lifetime
                )
                options = (
                    {"max_candidate_age": 999, "suppress_known_calls": True}
                    if candidate_lifetime == "episode"
                    else {}
                )
                m = FrozenReplay([tape], 10000, 1, **options).run(policy)["metrics"]
                reference = (
                    persistent_reference(tape)
                    if candidate_lifetime == "episode" and mode == "speculative"
                    else unlimited_reference(tape, mode == "speculative")
                )
                result = playback["result"]
                residual = result["completion_s"] - m["mean_completion_s"]
                if abs(residual) > 1e-8 or result["cache_hits"] != m["cache_hits"]:
                    raise AssertionError(
                        (tape["task_id"], mode, "runtime/scheduler mismatch", result, m)
                    )
                if result["prefetches"] != m["speculative_calls"]:
                    raise AssertionError("Async runtime/scheduler prefetch count mismatch")
                if abs(result["resource_s"] - m["resource_makespan_s"]) > 1e-8:
                    raise AssertionError((tape["task_id"], mode, "drain mismatch", result, m))
                assert abs(reference["completion_s"] - result["completion_s"]) < 1e-8
                row[mode] = {
                    "answer_s": result["completion_s"],
                    "resource_s": result["resource_s"],
                    "hits": result["cache_hits"],
                    "residual_s": residual,
                    "prefetches": result["prefetches"],
                }
                # Keep full real-runtime traces, not just event-simulator output.
                playback["model_generations"] = [
                    {"role": k[0], "step": k[1], "attempts": v}
                    for k, v in playback["model_generations"].items()
                ]
                write_json(output / f"{tape['task_id']}-{mode}.json", playback)
            hotpot.append(row)
            print(tape["task_id"], "exact saved prompts and async timing verified", flush=True)
    result = {
        "source_provenance": {
            "revision": revision,
            "selected_original_code_and_data_pristine": pristine,
            "original_chess_analyzer_sha256": hashlib.sha256(
                (Path(checkout) / "chess-game/guess_analysis.py").read_bytes()
            ).hexdigest(),
            "async_runtime_sha256": hashlib.sha256(
                Path(__file__).with_name("hotpot_runtime.py").read_bytes()
            ).hexdigest(),
        },
        "protocol": {
            "agents": 1,
            "search_quota": None,
            "jev": False,
            "required_result_cache": False,
            "model_submission_pacing": False,
            "candidate_lifetime": candidate_lifetime,
            "search_duration_scale": search_scale,
            "synthetic_search_times": search_scale != 1,
            "speculation": "existing runtime, source Search -> observation -> hypothetical actor -> speculative Search",
            "clock": "asyncio service-time playback; not new live provider measurements",
        },
        "chess": chess,
        "hotpot": hotpot,
        "chess_mean_reported_time_saving_percent": statistics.mean(
            r["original"]["time_saved_percentage"] for r in chess
        ),
        "hotpot_mean_sequential_s": statistics.mean(r["sequential"]["answer_s"] for r in hotpot),
        "hotpot_mean_speculative_s": statistics.mean(r["speculative"]["answer_s"] for r in hotpot),
        "new_model_calls": 0,
        "new_model_spend_usd": 0,
    }
    write_json(output / "comparison.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dataset", default="results/hotpot-dataset-50")
    parser.add_argument("--checkout", default="tmp/speculative-action-upstream")
    parser.add_argument(
        "--candidate-lifetime", choices=("episode", "next_action"), default="episode"
    )
    parser.add_argument("--search-scale", type=float, default=1.0)
    args = parser.parse_args()
    result = run(
        args.output,
        args.dataset,
        args.checkout,
        candidate_lifetime=args.candidate_lifetime,
        search_scale=args.search_scale,
    )
    print(json.dumps({k: v for k, v in result.items() if k not in ["chess", "hotpot"]}, indent=2))
