"""Export existing HotpotQA recordings as an offline dependency/coverage graph.

This inventories recorded work; missing tool state and unexecuted alternatives
remain missing. It does not claim that the graph is an executable replay tape.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from graphlib import TopologicalSorter
from pathlib import Path

from .artifacts import write_json

VERSION = 1


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def unique(rows, key, label):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result:
            raise ValueError(f"Duplicate {label}: {identity}")
        result[identity] = row
    return result


def action_parts(action):
    boundary = action.index("[")
    return action[:boundary].lower(), action[boundary + 1 : -1]


def build_graph(config, episodes, records, requests, events):
    """Strictly join requests by ID and branch; never by question/step alone."""
    raw = unique(requests, "request_id", "raw request")
    billed = unique(records, "request_id", "inference record")
    if raw.keys() != billed.keys():
        raise ValueError("Raw and billed request IDs differ")
    tasks = unique(episodes, "episode", "episode")
    nodes, by_id = [], {}
    event_node, starts, finishes = {}, {}, {}
    groups = defaultdict(list)
    missing = []

    def add(identity, kind, episode, dependencies=(), **fields):
        if identity in by_id:
            raise ValueError(f"Duplicate node: {identity}")
        if episode not in tasks:
            raise ValueError(f"Unknown episode: {episode}")
        node = {
            "id": identity,
            "kind": kind,
            "episode": episode,
            "agent_id": episode,
            "dependencies": list(dependencies),
            **fields,
        }
        nodes.append(node)
        by_id[identity] = node
        return node

    def gap(node, fields, reason):
        missing.append({"node_id": node, "fields": fields, "reason": reason})

    for line, event in enumerate(events, 1):
        kind = event["event"]
        episode = event["episode"]
        if episode not in tasks:
            raise ValueError(f"Event references unknown episode: {episode}")
        if kind in ("inference_started", "inference_finished"):
            target = starts if kind == "inference_started" else finishes
            request_id = event["request_id"]
            if request_id in target:
                raise ValueError(f"Duplicate {kind}: {request_id}")
            target[request_id] = event
            event_node[line] = f"request:{request_id}"
        elif kind not in ("search_started", "search_finished", "search_failed"):
            identity = f"event:{line}"
            add(
                identity,
                kind,
                episode,
                start_s=event["time_s"],
                end_s=event["time_s"],
                event=event,
                step=event.get("step"),
                source={"path": "evidence/events.jsonl", "line": line},
            )
            event_node[line] = identity
            groups[(episode, kind, event.get("step"))].append(identity)
    if starts.keys() != raw.keys() or finishes.keys() != raw.keys():
        raise ValueError("Inference start/finish events do not account for every request")

    model_groups = defaultdict(list)
    for request_id in sorted(raw):
        record, request = billed[request_id], raw[request_id]
        start, finish = starts[request_id], finishes[request_id]
        context = tuple(record[k] for k in ("episode", "role", "step"))
        if any(
            tuple(e[k] for k in ("episode", "role", "step")) != context for e in (start, finish)
        ):
            raise ValueError(f"Request context mismatch: {request_id}")
        episode, role, step = context
        node = add(
            f"request:{request_id}",
            "model",
            episode,
            role=role,
            step=step,
            branch="authoritative"
            if role == "actor"
            else f"prediction:{step if role == 'observation_speculator' else step - 1}",
            request_id=request_id,
            start_s=start["time_s"],
            end_s=finish["time_s"],
            ready_s=None,
            queue_s=None,
            service_s=record["latency_s"],
            request_sha256=digest(request["request"]),
            request=request["request"],
            response=request.get("response"),
            http_status=request.get("http_status"),
            usage=record,
            status="failed" if record.get("failure") else "completed",
        )
        model_groups[(episode, role, step)].append(node["id"])
        gap(node["id"], ["ready_s", "queue_s"], "Only submission and service timing were recorded")

    def one(episode, kind, step=None):
        values = groups[(episode, kind, step)]
        if len(values) != 1:
            raise ValueError(f"Expected one {kind} for {episode} step {step}, got {len(values)}")
        return values[0]

    def last_model(episode, role, step):
        values = model_groups[(episode, role, step)]
        if not values:
            raise ValueError(f"Missing {role} for {episode} step {step}")
        return values[-1]

    # Pair tool events by the full exact execution identity, including branch.
    pending, tools = {}, defaultdict(list)
    for line, event in enumerate(events, 1):
        kind = event["event"]
        if kind not in ("search_started", "search_finished", "search_failed"):
            continue
        key = tuple(event[k] for k in ("episode", "step", "query", "speculative"))
        episode, step, query, speculative = key
        if kind == "search_started":
            if key in pending:
                raise ValueError(f"Ambiguous concurrent tool identity: {key}")
            identity = f"search:{line}"
            if speculative:
                launches = [
                    n
                    for n in groups[(episode, "prefetch_launched", step)]
                    if by_id[n]["event"]["query"] == query
                ]
                if len(launches) != 1:
                    raise ValueError(f"Missing/ambiguous prefetch launch: {key}")
                parent = launches[0]
            else:
                parent = one(episode, "required_action", step)
            node = add(
                identity,
                "search",
                episode,
                [parent],
                step=step,
                query=query,
                branch="prefetch" if speculative else "required",
                speculative=speculative,
                start_s=event["time_s"],
                end_s=None,
                ready_s=None,
                queue_s=None,
                service_s=None,
                status="started",
                result=None,
                state_before=None,
                state_after=None,
                used_by=[],
            )
            pending[key] = node
            tools[episode].append(node)
            event_node[line] = identity
        else:
            if key not in pending:
                raise ValueError(f"Unmatched tool completion: {key}")
            node = pending.pop(key)
            node.update(
                end_s=event["time_s"],
                service_s=event.get("duration_s"),
                status="failed" if kind == "search_failed" else "completed",
                failure=event.get("failure"),
            )
            event_node[line] = node["id"]
    if pending:
        raise ValueError("Undrained tool starts in evidence")

    windows, candidate_coverage = [], []
    for episode, task in tasks.items():
        start = one(episode, "episode_started")
        previous = start
        for entry in task["trajectory"]:
            step = entry["step"]
            actor = model_groups[(episode, "actor", step)]
            if not actor:
                raise ValueError(f"No authoritative model output for {episode} step {step}")
            parent = previous
            for attempt, identity in enumerate(actor, 1):
                by_id[identity]["dependencies"] = [parent]
                by_id[identity]["attempt"] = attempt
                parent = identity
            required = one(episode, "required_action", step)
            by_id[required]["dependencies"] = [parent]
            if by_id[required]["event"]["action"] != entry["action"]:
                raise ValueError("Required action differs from saved trajectory")
            tool, query = action_parts(entry["action"])
            dependencies = [required]
            selected = None
            if tool == "search":
                candidates = [
                    n
                    for n in tools[episode]
                    if n["query"] == query
                    and n["status"] == "completed"
                    and (
                        n["speculative"]
                        if entry["prefetch_hit"]
                        else not n["speculative"] and n["step"] == step
                    )
                ]
                if len(candidates) != 1:
                    raise ValueError(f"Missing/ambiguous selected Search for {episode} step {step}")
                selected = candidates[0]
                dependencies.append(selected["id"])
            applied = add(
                f"apply:{episode}:{step}",
                "tool_application",
                episode,
                dependencies,
                step=step,
                branch="authoritative",
                action=entry["action"],
                thought=entry["thought"],
                observation=entry["observation"],
                tool_wait_s=entry["tool_wait_s"],
                prefetch_hit=entry["prefetch_hit"],
                start_s=None,
                end_s=None,
                state_before=None,
                state_after=None,
            )
            if selected is not None:
                selected["used_by"].append(applied["id"])
            gap(
                applied["id"],
                ["state_before", "state_after", "end_s"],
                "Trajectory has displayed observation/wait, but no complete WikiEnv state or application timestamp",
            )
            previous = applied["id"]
            if task["mode"] == "speculative" and tool == "search" and step < config["max_steps"]:
                observations = model_groups[(episode, "observation_speculator", step)]
                hypothetical = model_groups[(episode, "speculative_actor", step + 1)]
                candidates = groups[(episode, "candidates_ready", step + 1)]
                window = {
                    "episode": episode,
                    "step": step,
                    "boundary": required,
                    "observation_nodes": observations,
                    "hypothetical_nodes": hypothetical,
                    "candidate_nodes": candidates,
                    "missing": [],
                }
                if not observations:
                    window["missing"].append("observation_prediction")
                if not hypothetical:
                    window["missing"].append("hypothetical_actor")
                if not candidates:
                    window["missing"].append("ranked_candidate_list")
                window["reason"] = (
                    "cache_hit_skipped_window"
                    if entry["prefetch_hit"]
                    else "late_observation_or_missing_branch"
                    if not hypothetical
                    else "recorded"
                )
                windows.append(window)

        for (ep, role, step), identities in list(model_groups.items()):
            if ep != episode or role == "actor" or not identities:
                continue
            parent = (
                one(episode, "required_action", step)
                if role == "observation_speculator"
                else last_model(episode, "observation_speculator", step - 1)
            )
            for attempt, identity in enumerate(identities, 1):
                by_id[identity]["dependencies"] = [parent]
                by_id[identity]["attempt"] = attempt
                parent = identity
        for (ep, kind, step), identities in list(groups.items()):
            if ep != episode:
                continue
            if kind == "candidates_ready":
                for identity in identities:
                    by_id[identity]["dependencies"] = [
                        last_model(episode, "speculative_actor", step)
                    ]
                    by_id[identity]["ranked_candidates"] = [
                        {"rank": rank, "action": action}
                        for rank, action in enumerate(by_id[identity]["event"]["actions"], 1)
                    ]
                    boundary = by_id[one(episode, "required_action", step - 1)]["event"]
                    _, current_query = action_parts(boundary["action"])
                    for candidate in by_id[identity]["ranked_candidates"]:
                        tool, query = action_parts(candidate["action"])
                        executions = (
                            [
                                n["id"]
                                for n in tools[episode]
                                if n["speculative"] and n["query"] == query and n["step"] <= step
                            ]
                            if tool == "search"
                            else []
                        )
                        coverage_entry = {
                            "candidate_node": identity,
                            "episode": episode,
                            **candidate,
                            "eligible_search": tool == "search" and query != current_query,
                            "on_time": by_id[identity]["event"]["on_time"],
                            "execution_nodes": executions,
                            "full_result_available": False
                            if tool == "search" and query != current_query
                            else None,
                            "missing": (
                                ["full_tool_result", "full_tool_state"]
                                if tool == "search" and query != current_query
                                else []
                            ),
                        }
                        if coverage_entry["eligible_search"] and not executions:
                            coverage_entry["missing"].append("recorded_tool_execution")
                        candidate_coverage.append(coverage_entry)
            elif kind == "prefetch_launched":
                for identity in identities:
                    by_id[identity]["dependencies"] = [one(episode, "candidates_ready", step)]
        answer, drained = one(episode, "answer_ready"), one(episode, "episode_drained")
        by_id[answer]["dependencies"] = [previous]
        by_id[answer]["answer"] = task["answer"]
        by_id[drained]["dependencies"] = [answer] + [
            n["id"] for n in nodes if n["episode"] == episode and n["kind"] in ("model", "search")
        ]

    for node in nodes:
        if node["kind"] == "search":
            gap(
                node["id"],
                ["result", "state_before", "state_after", "ready_s", "queue_s"],
                "Only Search timing/query recorded; a used displayed observation is not a full tool result",
            )
        if node.get("end_s") is not None and node.get("start_s") is not None:
            if node["end_s"] < node["start_s"]:
                raise ValueError(f"Negative stage interval: {node['id']}")
        for parent in node["dependencies"]:
            if parent not in by_id or by_id[parent]["episode"] != node["episode"]:
                raise ValueError(f"Invalid or cross-episode dependency: {parent}")
            end, start = by_id[parent].get("end_s"), node.get("start_s")
            if end is not None and start is not None and end > start:
                raise ValueError(
                    f"Dependency completes after dependent starts: {parent} -> {node['id']}"
                )
    order = TopologicalSorter({n["id"]: n["dependencies"] for n in nodes}).static_order()
    completed_after = {}
    for identity in order:
        node = by_id[identity]
        lower_bound = max((completed_after[p] for p in node["dependencies"]), default=0)
        if node.get("start_s") is not None and node["start_s"] < lower_bound:
            raise ValueError(f"Dependency completes after dependent starts: {identity}")
        completed_after[identity] = max(lower_bound, node.get("end_s") or 0)
    if len(event_node) != len(events):
        raise ValueError("Not every source event is accounted for")
    canonical = [e for e, t in tasks.items() if t["mode"] == "speculative"]
    coverage = {
        "version": VERSION,
        "replay_ready": False,
        "requests_accounted_for": len(raw),
        "events_accounted_for": len(event_node),
        "episodes": len(tasks),
        "canonical_speculative_tapes": canonical,
        "independent_sequential_episodes": [e for e in tasks if e not in canonical],
        "nodes_by_kind": dict(Counter(n["kind"] for n in nodes)),
        "searches": sum(n["kind"] == "search" for n in nodes),
        "full_tool_results_available": 0,
        "full_state_transitions_available": 0,
        "prefetch_hits": sum(t["cache_hits"] for t in tasks.values()),
        "windows": windows,
        "candidate_coverage": candidate_coverage,
        "missing_window_fields": dict(Counter(f for w in windows for f in w["missing"])),
        "missing": missing,
        "limitations": [
            "Graph describes observed dependencies, not a complete counterfactual bank",
            "Only speculative histories are canonical; sequential model outputs are independent",
            "Exact payload hashes identify inputs; stochastic attempts remain distinct nodes",
            "Queue/readiness and local processing timestamps were not captured",
            "Used Search observations omit full page/result titles/lookup state; unused results are absent",
            "Unlaunched candidate results and skipped windows require separate declared bank completion",
            "Original absolute timestamps are evidence, not readiness rules for changed schedules",
        ],
    }
    return {
        "version": VERSION,
        "nodes": nodes,
        "event_nodes": {str(k): v for k, v in event_node.items()},
    }, coverage


def export(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Choose a fresh export directory outside the source evidence")
    config_bytes = (source / "config.json").read_bytes()
    config = json.loads(config_bytes)
    paths = [
        Path(name)
        for name in (
            "config.json",
            "summary.json",
            "requests.jsonl",
            "inference.jsonl",
            "events.jsonl",
        )
    ]
    task_paths = [
        Path("tasks") / f"{index}-{mode}.json"
        for index in config["indices"]
        for mode in ("sequential", "speculative")
    ]
    paths += task_paths
    captured = {p: (source / p).read_bytes() for p in paths}
    if captured[Path("config.json")] != config_bytes:
        raise ValueError("Configuration changed during export")
    episodes = [json.loads(captured[p]) for p in task_paths]

    def rows(name):
        return [json.loads(line) for line in captured[Path(name)].splitlines() if line.strip()]

    graph, coverage = build_graph(
        config,
        episodes,
        rows("inference.jsonl"),
        rows("requests.jsonl"),
        rows("events.jsonl"),
    )
    manifest = {
        "version": VERSION,
        "source_config_sha256": digest(config),
        "upstream": config["upstream"],
        "source_sha256": config["source_sha256"],
        "files": {
            str(p): {"sha256": hashlib.sha256(captured[p]).hexdigest(), "bytes": len(captured[p])}
            for p in paths
        },
    }
    output.mkdir(parents=True)
    for path in paths:
        target = output / "evidence" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(captured[path])
        if (
            hashlib.sha256(target.read_bytes()).hexdigest()
            != manifest["files"][str(path)]["sha256"]
        ):
            raise ValueError(f"Evidence changed during export: {path}")
    write_json(output / "graph.json", graph)
    write_json(output / "coverage.json", coverage)
    for name in ("graph.json", "coverage.json"):
        manifest.setdefault("derived_sha256", {})[name] = hashlib.sha256(
            (output / name).read_bytes()
        ).hexdigest()
    write_json(output / "manifest.json", manifest)
    lines = [
        "# Existing-recording coverage",
        "",
        f"Accounted for {coverage['requests_accounted_for']} model requests, "
        f"{coverage['events_accounted_for']} events and {coverage['episodes']} episodes.",
        "",
        f"Canonical tapes: {len(coverage['canonical_speculative_tapes'])} speculative episodes. "
        "Independent sequential episodes remain separate.",
        "",
        f"Recorded exact prefetch hits: {coverage['prefetch_hits']}. "
        f"Search executions: {coverage['searches']}; complete tool results: 0; complete state transitions: 0.",
        "",
        "Missing window fields: " + json.dumps(coverage["missing_window_fields"], sort_keys=True),
        "",
        "**Replay ready: no.** Full Search payloads, WikiEnv snapshots and skipped alternatives "
        "must be captured or explicitly completed before faithful scheduling replay.",
        "",
        "`graph.json` retains exact model payloads/responses, request attempts, all recorded "
        "ranked candidates, observed timing and dependency edges. `coverage.json` lists gaps "
        "per node/window. `evidence/` contains byte-identical input files; `manifest.json` hashes them.",
    ]
    (output / "COVERAGE.md").write_text("\n".join(lines) + "\n")
    return coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    coverage = export(args.source, args.output)
    print(
        json.dumps(
            {
                k: v
                for k, v in coverage.items()
                if k not in ("missing", "windows", "candidate_coverage")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
