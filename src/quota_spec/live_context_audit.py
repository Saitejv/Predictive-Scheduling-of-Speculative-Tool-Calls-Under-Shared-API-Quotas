"""Independent offline audit of live multi-agent quota and forecast observations."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from .artifacts import write_json
from .capture_audit import audit as audit_capture
from .hotpot_runtime import split_action
from .models import Call
from .telemetry import summarize_inference


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
