"""Independent offline audit of live multi-agent quota and forecast observations."""

import argparse
import ast
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .artifacts import write_json
from .capture_audit import audit as audit_capture
from .hotpot_runtime import split_action
from .models import Call
from .telemetry import summarize_inference


def frozen_prompt_builder(source):
    """Interpret the archived string template without executing captured code."""
    tree = ast.parse(source)
    marker = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "MARKER" for t in n.targets)
    )
    definition = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "planner_prompt"
    )

    def evaluate(node, values):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Tuple):
            return tuple(evaluate(n, values) for n in node.elts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return evaluate(node.left, values) + evaluate(node.right, values)
        if isinstance(node, ast.JoinedStr):
            return "".join(str(evaluate(n, values)) for n in node.values)
        if isinstance(node, ast.FormattedValue) and node.format_spec is None:
            return str(evaluate(node.value, values))
        if isinstance(node, ast.IfExp):
            return evaluate(node.body if evaluate(node.test, values) else node.orelse, values)
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.IsNot)
        ):
            return evaluate(node.left, values) is not evaluate(node.comparators[0], values)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and node.func.attr == "dumps"
            and len(node.args) == 1
            and all(k.arg in {"sort_keys", "separators"} for k in node.keywords)
        ):
            return json.dumps(
                evaluate(node.args[0], values),
                **{k.arg: evaluate(k.value, values) for k in node.keywords},
            )
        raise ValueError("Unsupported frozen planner expression")

    def build(prefix, step, width, quota):
        values = {"prefix": prefix, "step": step, "width": width, "quota": quota, "MARKER": marker}
        for statement in definition.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                values[statement.targets[0].id] = evaluate(statement.value, values)
            elif isinstance(statement, ast.Return):
                return evaluate(statement.value, values)
            else:
                raise ValueError("Unsupported frozen planner statement")
        raise ValueError("Frozen planner has no return")

    return marker, build


def rows(path):
    return (
        [json.loads(line) for line in path.read_text().splitlines() if line]
        if path.exists()
        else []
    )


def audit(root):
    root = Path(root)
    config = json.loads((root / "config.json").read_text())
    captured = audit_capture(root)
    events = rows(root / "events.jsonl")
    tasks = [json.loads(p.read_text()) for p in (root / "tasks").glob("*.json")]
    claims = [e for e in events if e["event"] == "quota_claimed"]
    starts = [e for e in events if e["event"] == "search_started"]

    def identity(e):
        return (e["episode"], e["query"], e["speculative"])

    if Counter(map(identity, claims)) != Counter(map(identity, starts)):
        raise ValueError("Quota claims differ from actual Search executions")
    windows = Counter(e["window_index"] for e in claims)
    if any(n > config["capacity"] for n in windows.values()):
        raise ValueError("Quota capacity exceeded")
    for e in claims:
        lo = e["window_index"] * config["window_s"]
        if not lo - 1e-5 <= e["time_s"] <= lo + config["window_s"] + 1e-5:
            raise ValueError("Quota claim assigned to wrong reset window")
    required = [e for e in claims if not e["speculative"]]
    ready = [e["time_s"] - e["wait_s"] for e in required]
    if any(a > b + 1e-5 for a, b in zip(ready, ready[1:])):
        raise ValueError("Required FIFO ordering violated")
    for optional in [e for e in claims if e["speculative"]]:
        if any(
            e["time_s"] - e["wait_s"] + 1e-5 < optional["time_s"] < e["time_s"] - 1e-5
            for e in required
        ):
            raise ValueError("Speculation spent quota while required work waited")
    expected_required = Counter(
        (t["episode"], split_action(s["action"])[1])
        for t in tasks
        for s in t["trajectory"]
        if split_action(s["action"])[0] == "search" and not s["prefetch_hit"]
    )
    if expected_required != Counter((e["episode"], e["query"]) for e in required):
        raise ValueError("Required cache misses and quota claims disagree")

    planner_contexts = [e for e in events if e["event"] == "speculation_planner_context"]
    if config.get("speculation_planner", "legacy") != "legacy":
        from .capture import CaptureStore
        from .quota_speculation import parse_queries

        # Prompts evolved during development. Audit the exact recorded version,
        # rather than silently checking old evidence with today's instructions.
        frozen_path = root / "source-snapshot" / "quota_speculation.py"
        frozen_source = frozen_path.read_bytes()
        if hashlib.sha256(frozen_source).hexdigest() != config["source_sha256"].get(
            "quota_speculation.py"
        ):
            raise ValueError("Frozen quota planner source hash mismatch")
        MARKER, planner_prompt = frozen_prompt_builder(frozen_source)

        store = CaptureStore(root / "capture")
        active, counts, peer_registry = set(), Counter(), {}
        demand_times = []
        for event in events:
            kind = event["event"]
            if kind == "episode_started":
                active.add(event["episode"])
                peer_registry[event["episode"]] = {
                    "worker": event["episode"],
                    "task": event["question"][:2048],
                    "completed_calls": 0,
                    "phase": "thinking",
                    "since": event["time_s"],
                    "history": [],
                    "last_result": "",
                    "last_returned_actor_intent": "",
                }
            elif kind == "answer_ready":
                active.remove(event["episode"])
                peer_registry.pop(event["episode"])
            elif kind == "required_action" and event["episode"] in peer_registry:
                peer = peer_registry[event["episode"]]
                tool, value = split_action(event["action"])
                if tool == "search":
                    demand_times.append(event["time_s"])
                call = (
                    Call.search(value)
                    if tool == "search"
                    else Call(tool, json.dumps({"value": value}))
                )
                peer["history"] = [*peer["history"][-7:], asdict(call)]
                peer.update(
                    phase="queued" if tool == "search" else "running",
                    since=event["time_s"],
                    last_returned_actor_intent=event.get("thought", "")[:1024],
                )
            elif (
                kind == "search_started"
                and not event["speculative"]
                and event["episode"] in peer_registry
            ):
                peer_registry[event["episode"]].update(phase="running", since=event["time_s"])
            elif kind == "tool_observed" and event["episode"] in peer_registry:
                peer_registry[event["episode"]].update(
                    phase="thinking",
                    since=event["time_s"],
                    completed_calls=event["step"],
                    last_result=event["observation"][:1024],
                )
            elif kind == "quota_claimed":
                counts[event["window_index"]] += 1
            elif kind == "speculation_planner_context":
                context = event["quota"]
                if event["planner"] == "blind":
                    if context is not None:
                        raise ValueError("Blind planner received quota state")
                    continue
                window = math.floor(context["observed_at_s"] / config["window_s"])
                if (
                    config.get("required_demand_counter")
                    == "offered_search_actions_including_cache_hits"
                ):
                    if context["required_calls_in_current_window"] != sum(
                        t >= window * config["window_s"] for t in demand_times[-4096:]
                    ):
                        raise ValueError("Planner required demand differs from observed actions")
                expected_keys = {
                    "api",
                    "quota_type",
                    "capacity",
                    "remaining_calls",
                    "refill_period_s",
                    "seconds_to_refill",
                    "window_index",
                    "observed_at_s",
                    "active_workers",
                    "other_active_workers",
                    "queued_required_calls",
                    "running_required_workers",
                    "required_calls_in_current_window",
                }
                if event["planner"] in ("team", "quota_team"):
                    expected_keys.add("observed_peers")
                    actual = context["observed_peers"]
                    peers = sorted(active - {event["episode"]})
                    if actual["omitted_workers"] != max(0, len(peers) - 16) or len(
                        actual["workers"]
                    ) != min(16, len(peers)):
                        raise ValueError("Peer registry size differs from observed workers")
                    for tid, supplied in zip(peers[:16], actual["workers"], strict=True):
                        expected = dict(peer_registry[tid])
                        since = expected.pop("since")
                        row = dict(supplied)
                        elapsed = row.pop("elapsed_s")
                        if (
                            row != expected
                            or abs(elapsed - (context["observed_at_s"] - since)) > 0.001
                        ):
                            raise ValueError("Peer context differs from observed event history")
                if set(context) != expected_keys:
                    raise ValueError("Unexpected field in observed quota context")
                if (
                    context["api"] != "Wikipedia Search"
                    or context["quota_type"] != "fixed_window_no_refund"
                    or context["capacity"] != config["capacity"]
                    or context["refill_period_s"] != config["window_s"]
                    or context["window_index"] != window
                    or context["remaining_calls"] != config["capacity"] - counts[window]
                    or context["active_workers"] != len(active)
                    or context["other_active_workers"] != len(active - {event["episode"]})
                    or context["observed_at_s"] > event["time_s"]
                    or abs(
                        context["seconds_to_refill"]
                        - ((window + 1) * config["window_s"] - context["observed_at_s"])
                    )
                    > 1e-6
                ):
                    raise ValueError("Planner quota context differs from observed scheduler state")
        for node in store.nodes:
            if node["kind"] == "model" and node["branch"] == "actor":
                if MARKER in store.blob(node["input"])["prompt"]:
                    raise ValueError("Optional planner instruction leaked to the main actor")
            if node["kind"] != "generation" or node["branch"] != "speculative_actor":
                continue
            data = store.blob(node["input"])
            context = data["quota_context"]
            if not any(
                e["episode"] == node["episode"]
                and e["step"] == node["step"]
                and e["quota"] == context
                for e in planner_contexts
            ):
                raise ValueError("Planner request lacks an observed context event")
            attempt = store.by_id[data["attempts"][-1]]
            expected = planner_prompt(data["prefix"], node["step"], data["width"], context)
            if store.blob(attempt["input"])["prompt"] != expected:
                raise ValueError("Planner prompt differs from captured context")
            if (
                parse_queries(store.blob(attempt["output"])["content"], data["width"])
                != store.blob(node["output"])["actions"]
            ):
                raise ValueError("Planner output does not reproduce candidates")

    # Reconstruct only observations already published at each forecast snapshot.
    # This calculation does not import the context engine or inspect future tapes.
    forecast_rows = sorted(rows(root / "forecasts.jsonl"), key=lambda r: r["observed_at_s"])
    registry, cursor, checked = {}, 0, 0
    for forecast in forecast_rows:
        observed = forecast["observed_at_s"]
        while cursor < len(events) and events[cursor]["time_s"] <= observed:
            event = events[cursor]
            cursor += 1
            kind, episode = event["event"], event.get("episode")
            if kind == "episode_started":
                registry[episode] = {
                    "task": event["question"][:2048],
                    "history": [],
                    "excerpt": "",
                    "completed_calls": 0,
                    "phase": "thinking",
                    "actor_intent": "",
                }
            elif kind == "answer_ready":
                registry.pop(episode, None)
            elif episode in registry:
                agent = registry[episode]
                if kind == "required_action":
                    agent["actor_intent"] = (event.get("thought") or "")[:1024]
                    tool, value = split_action(event["action"])
                    call = (
                        Call.search(value)
                        if tool == "search"
                        else Call(
                            tool,
                            json.dumps(
                                {config.get("context_history_argument_key", "argument"): value}
                            ),
                        )
                    )
                    agent["history"] = (
                        agent["history"]
                        + [{"tool": call.tool, "arguments_json": call.arguments_json}]
                    )[-8:]
                    agent["phase"] = "queued" if tool == "search" else "running"
                elif kind == "search_started" and not event["speculative"]:
                    agent["phase"] = "running"
                elif kind == "tool_observed":
                    agent.update(
                        excerpt=event["observation"][:1024],
                        completed_calls=event["step"],
                        phase="thinking",
                    )
        context = forecast["input"]
        agent = registry.get(forecast["task_id"])
        mode = config.get("context", "progress")
        include_intent = mode == "progress_intent"
        if include_intent:
            mode = "progress"
        fields = {"task"}
        if mode in ("history", "progress", "no_progress"):
            fields.add("history")
        if mode in ("progress", "no_history", "no_progress"):
            fields.add("excerpt")
        if mode in ("progress", "no_history"):
            fields.update(("completed_calls", "phase"))
        # Earlier pilot configs described progress context with a prose string.
        if mode not in ("task", "history", "progress", "no_history", "no_progress"):
            fields = {"task", "history", "excerpt", "completed_calls", "phase"}
            mode = "progress"
        if include_intent:
            fields.add("actor_intent")
        if agent is None or any(context.get(k) != agent[k] for k in fields):
            raise ValueError("Forecast context contains unobserved or mismatched agent state")
        allowed = fields | {"candidate", "candidate_belongs_to_agent"}
        if mode in ("progress", "no_history"):
            allowed.add("elapsed_s")
        if set(context) != allowed:
            raise ValueError("Unexpected field in bounded forecast context")
        if "elapsed_s" in context and (
            not math.isfinite(context["elapsed_s"])
            or not 0 <= context["elapsed_s"] <= observed + 1e-6
        ):
            raise ValueError("Invalid forecast elapsed time")
        candidate = context["candidate"]
        if bool(candidate is not None) != context["candidate_belongs_to_agent"]:
            raise ValueError("Candidate owner isolation failed")
        if candidate is not None:
            query = json.loads(candidate["arguments_json"])["query"]
            if not any(
                e["event"] == "candidates_ready"
                and e["episode"] == forecast["task_id"]
                and e["time_s"] <= observed
                and any(split_action(a) == ("search", query) for a in e["actions"])
                for e in events
            ):
                raise ValueError("Forecast candidate was not observed when requested")
        checked += 1
    inference, forecasts = (
        summarize_inference(rows(root / "inference.jsonl")),
        summarize_inference(forecast_rows),
    )
    result = {
        "passed": True,
        "episodes": len(tasks),
        "state_transitions": captured["state_transitions_reexecuted"],
        "authoritative_prompts": captured["authoritative_prompts_checked"],
        "forecast_observed_contexts_checked": checked,
        "speculation_planner_contexts_checked": len(planner_contexts),
        "quota_claims": len(claims),
        "quota_windows": dict(windows),
        "required_fifo_valid": True,
        "required_priority_valid": True,
        "inference": inference,
        "forecasts": forecasts,
        "total_known_cost_usd": inference["known_cost_usd"] + forecasts["known_cost_usd"],
        "limitations": "Audits observed trajectories and exposed state; does not establish counterfactual speedup or predictor calibration.",
    }
    write_json(root / "context-audit.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    print(json.dumps(audit(p.parse_args().source), indent=2))


if __name__ == "__main__":
    main()
