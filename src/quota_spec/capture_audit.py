"""Socket-blocked validation of captured HotpotQA states, graph and prompt history."""

import argparse
import json
import math
import socket
from collections import Counter
from graphlib import TopologicalSorter
from pathlib import Path
from unittest.mock import patch

from .artifacts import write_json
from .capture import CaptureStore, restore, snapshot
from .hotpot_runtime import Runtime, split_action
from .upstream import REVISION, load_upstream


def load_module(source):
    class NoInference:
        def __init__(self, **kwargs):
            pass

        def call(self, *args, **kwargs):
            raise AssertionError("Frozen validation cannot call inference")

    return load_upstream(source, NoInference)


def audit(root, source=None):
    root = Path(root)
    store = CaptureStore(root / "capture")
    config = json.loads((root / "config.json").read_text())
    source = Path(source or Path("data/raw/speculative-action") / REVISION)
    # Verify the pinned source before importing any of its code, without downloading.
    for path, identity in config["upstream"]["files"].items():
        import hashlib

        if hashlib.sha256((source / path).read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError(f"Pinned source mismatch: {path}")
    module = load_module(source)
    parser = module.HotPotQARun.__new__(module.HotPotQARun)
    nodes = store.by_id
    graph = {n["id"]: n["dependencies"] for n in store.nodes}
    order = list(TopologicalSorter(graph).static_order())
    if any(identity not in nodes for identity in order):
        raise ValueError("Missing stage dependency")
    replay_end, replay_error, checked_states, checked_prompts = {}, [], 0, 0
    for identity in order:
        node = nodes[identity]
        for field in ("ready_s", "start_s", "end_s", "service_s", "queue_s"):
            if not math.isfinite(node[field]) or node[field] < 0:
                raise ValueError(f"Invalid timing: {identity}/{field}")
        if not node["ready_s"] <= node["start_s"] <= node["end_s"]:
            raise ValueError("Stage timing order invalid")
        store.blob(node["input"])
        store.blob(node["output"])
        parents = [nodes[d] for d in node["dependencies"]]
        if any(p["episode"] != node["episode"] for p in parents):
            raise ValueError("Cross-episode stage dependency")
        parent_end = max((p["end_s"] for p in parents), default=node["ready_s"])
        lag = node["ready_s"] - parent_end
        if lag < -1e-6:
            raise ValueError(f"Stage became ready before its dependency completed: {identity}")
        # Replay the observed schedule with measured per-edge dispatch/processing
        # lags. These lags are not a counterfactual scheduling model.
        replay_ready = max((replay_end[p["id"]] for p in parents), default=node["ready_s"]) + lag
        replay_end[identity] = replay_ready + node["end_s"] - node["ready_s"]
        replay_error.append(abs(replay_end[identity] - node["end_s"]))
        if node["kind"] == "search" and node["status"] == "completed":
            result = store.blob(node["output"])
            if "state_before" not in result or "state_after" not in result:
                raise ValueError("Full tool state missing")
            if (
                result["state_after"]["page"] != result["page"]
                or result["state_after"]["obs"] != result["obs"]
            ):
                raise ValueError("Search payload and worker state disagree")
    steps = [json.loads(line) for line in (store.root / "steps.jsonl").read_text().splitlines()]
    tasks = {p.stem: json.loads(p.read_text()) for p in (root / "tasks").glob("*.json")}
    event_path = root / "events.jsonl"
    if not event_path.exists() and any(t.get("timing_version") == 1 for t in tasks.values()):
        raise ValueError("Modern recording is missing its event log")
    event_rows = (
        [json.loads(line) for line in event_path.read_text().splitlines()]
        if event_path.exists()
        else []
    )
    timing_checks = thinking_launches = 0
    for task in tasks.values():
        if task.get("timing_version") != 1:
            continue  # Historical captures predate the explicit endpoint fields.
        start, answer, drain = (task[k] for k in ("started_at_s", "answer_at_s", "drained_at_s"))
        if (
            not all(math.isfinite(v) for v in (start, answer, drain))
            or not 0 <= start <= answer <= drain
        ):
            raise ValueError("Invalid episode timing endpoints")
        for actual, expected in [
            (task["completion_s"], answer - start),
            (task["resource_s"], drain - start),
            (task["drain_s"], drain - answer),
        ]:
            if abs(actual - expected) > 1e-6:
                raise ValueError("Episode duration does not match recorded endpoints")
        drains = [
            n for n in store.nodes if n["episode"] == task["episode"] and n["kind"] == "drain"
        ]
        if len(drains) != 1 or store.blob(drains[0]["output"]) != task:
            raise ValueError("Task summary differs from immutable captured drain output")
        events = [e for e in event_rows if e.get("episode") == task["episode"]]
        starts = {e["step"]: e["time_s"] for e in events if e["event"] == "actor_started"}
        ends = {e["step"]: e["time_s"] for e in events if e["event"] == "actor_completed"}
        launches = [e for e in events if e["event"] == "prefetch_launched"]
        used = [e for e in events if e["event"] in ("cache_joined", "cache_reused")]
        if len(launches) != task["prefetches"] or len(used) != task["cache_hits"]:
            raise ValueError("Recorded prefetch/cache counts disagree with episode summary")
        for launch in launches:
            if launch["time_s"] > answer + 1e-6:
                raise ValueError("Speculation admitted after the answer")
            if launch.get("actor_thinking"):
                step = launch["actor_step"]
                if (
                    step not in starts
                    or step not in ends
                    or not starts[step] <= launch["time_s"] <= ends[step]
                ):
                    raise ValueError("Prefetch thinking flag does not match actor span")
                thinking_launches += 1
        timing_checks += 1
    episodes_per_question = 1 if config.get("capture_protocol") == "multi_agent" else 2
    if len(steps) != len(tasks) or len(tasks) != episodes_per_question * len(config["indices"]):
        raise ValueError("Incomplete episode capture")
    if Counter(t["question_index"] for t in tasks.values()) != Counter(
        {i: episodes_per_question for i in config["indices"]}
    ):
        raise ValueError("Captured question inventory mismatch")
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network forbidden")),
    ):
        for episode in steps:
            task = next(t for t in tasks.values() if t["episode"] == episode["episode"])
            if task["failure"]:
                raise ValueError("Failed authoritative episode")
            if len(task["trajectory"]) != len(episode["steps"]):
                raise ValueError("Missing authoritative step capture")
            next_prefix, last_state = None, None
            for step, trajectory in zip(episode["steps"], task["trajectory"], strict=True):
                boundary = nodes[step["boundary"]]
                before = store.blob(boundary["output"])
                boundary_input = store.blob(boundary["input"])
                generation = nodes[step["actor"]]
                generated = store.blob(generation["output"])
                gen_input = store.blob(generation["input"])
                if (
                    boundary_input["action"] != trajectory["action"]
                    or generated["actions"][0] != trajectory["action"]
                ):
                    raise ValueError("Actor/action mismatch")
                if next_prefix is not None and gen_input["prefix"] != next_prefix:
                    raise ValueError("Authoritative actor prompt contains wrong history")
                if last_state is not None and before != last_state:
                    raise ValueError("State discontinuity before authoritative action")
                for attempt, model_id in enumerate(gen_input["attempts"]):
                    model = nodes[model_id]
                    prompt = store.blob(model["input"])["prompt"]
                    if not prompt.startswith(gen_input["prefix"]):
                        raise ValueError("Model input does not match exact authoritative prefix")
                    content = store.blob(model["output"])["content"]
                    actions = (
                        parser.separate_thought_and_actions(step["step"], content)[1]
                        if attempt == 0
                        else parser.extract_actions(content)
                    )
                    if (
                        attempt == len(gen_input["attempts"]) - 1
                        and actions[:1] != generated["actions"]
                    ):
                        raise ValueError("Pinned parser does not reproduce action")
                    checked_prompts += 1
                env = restore(module.environment.WikiEnv("unused"), before)
                tool, value = split_action(trajectory["action"])
                if tool == "search":
                    tool_node = nodes[step["search"]]
                    if (
                        tool_node["status"] != "completed"
                        or store.blob(tool_node["input"])["query"] != value
                    ):
                        raise ValueError("Selected Search result identity mismatch")
                    Runtime.apply_search(env, store.blob(tool_node["output"]))
                else:
                    env.step(tool + "[" + value + "]")
                application = nodes[step["application"]]
                applied = store.blob(application["output"])
                if snapshot(env) != applied["state_after"]:
                    raise ValueError("Restored WikiEnv does not reproduce state transition")
                if env.obs.replace("\\n", "") != trajectory["observation"]:
                    raise ValueError("Restored observation differs from trajectory")
                last_state = applied["state_after"]
                next_prefix = gen_input["prefix"] + module.PromptTemplates.NEXT_STEP_PROMPT.format(
                    i=step["step"],
                    thought=trajectory["thought"],
                    action=trajectory["action"],
                    obs=trajectory["observation"],
                )
                checked_states += 1
            expected_answer = "" if task["forced_finish"] else last_state["answer"]
            if expected_answer != task["answer"]:
                raise ValueError("Answer does not match final captured state")
    skipped_nodes = [n for n in store.nodes if n["kind"] == "model" and n["status"] == "skipped"]
    if any(
        n["branch"] == "actor" or n["error"] != "OptionalExpired" or "request_id" in n
        for n in skipped_nodes
    ):
        raise ValueError("Invalid skipped model stage")
    model_nodes = [n for n in store.nodes if n["kind"] == "model" and n["status"] != "skipped"]
    if config["backend"] == "http":
        records = [json.loads(line) for line in (root / "inference.jsonl").read_text().splitlines()]
        raw = [json.loads(line) for line in (root / "requests.jsonl").read_text().splitlines()]
        if len(raw) != len(records) or len(model_nodes) != len(records):
            raise ValueError("Paid request inventory differs from captured model stages")
        if {n.get("request_id") for n in model_nodes} != {r["request_id"] for r in records}:
            raise ValueError("Paid request IDs differ from capture")
        if len({r["request_id"] for r in records}) != len(records) or len(
            {r["request_id"] for r in raw}
        ) != len(raw):
            raise ValueError("Duplicate paid request ID")
        records_by_id = {r["request_id"]: r for r in records}
        raw_by_id = {r["request_id"]: r for r in raw}
        for node in model_nodes:
            request_id = node["request_id"]
            if (
                node["usage"] != records_by_id[request_id]
                or store.blob(node["response"]) != raw_by_id[request_id]
            ):
                raise ValueError("Paid request evidence differs from immutable capture")
        conservative = config.get("transport", {}).get("unknown_cost") == "conservative_reservation"
        for node in model_nodes:
            usage = node["usage"]
            if not conservative and (node["status"] != "completed" or usage["cost_usd"] is None):
                raise ValueError("Failed model stage or unknown paid cost")
            if conservative:
                charge = usage.get("budget_charge_usd")
                if not isinstance(charge, (int, float)) or not math.isfinite(charge) or charge < 0:
                    raise ValueError("Attempt lacks conservative budget accounting")
                if usage["cost_usd"] is not None and charge != usage["cost_usd"]:
                    raise ValueError("Known cost differs from budget charge")
    result = {
        "capture_version": 2,
        "passed": True,
        "episodes": len(tasks),
        "nodes": len(nodes),
        "by_kind": dict(Counter(n["kind"] for n in store.nodes)),
        "state_transitions_reexecuted": checked_states,
        "authoritative_prompts_checked": checked_prompts,
        "recorded_schedule_max_residual_s": max(replay_error, default=0),
        "schedule_tolerance_s": 1e-6,
        "prefetch_hits": sum(t["cache_hits"] for t in tasks.values()),
        "skipped_unsent_model_stages": len(skipped_nodes),
        "failed_model_attempts": sum(n["status"] == "failed" for n in model_nodes),
        "unused_prefetches": sum(t["unused_prefetches"] for t in tasks.values()),
        "bank_complete": False,
        "scope": "Observed schedule DAG with measured lags and pinned state transitions; alternatives require completed tapes",
        "episode_endpoint_checks": timing_checks,
        "prefetches_during_actor_thinking_verified": thinking_launches,
    }
    if result["recorded_schedule_max_residual_s"] > result["schedule_tolerance_s"]:
        raise ValueError("Recorded schedule replay exceeds tolerance")
    write_json(root / "capture-audit.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.source, args.upstream), indent=2))


if __name__ == "__main__":
    main()
