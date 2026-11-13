"""Complete finite scheduling alternatives on captured authoritative histories.

Bank completion is separate from live measurement. Only pre-tool history enters
missing prediction calls. Model/Wikipedia access requires --backend http.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import shutil
from pathlib import Path

from .artifacts import write_json
from .capture import Capture, CaptureStore
from .capture_audit import load_module
from .hotpot_runtime import Events, MockChat, MockSearch, Runtime, WikiSearch, split_action
from .transport import LiveChat
from .upstream import REVISION


def generation_span(store, generation):
    data = store.blob(generation["input"])
    attempts = [store.by_id[i] for i in data["attempts"]]
    return sum(n["service_s"] for n in attempts) + max(
        0.0, generation["ready_s"] - attempts[-1]["end_s"]
    )


def model_span(node):
    return node["service_s"]


def needed_windows(source):
    source = Path(source)
    store = CaptureStore(source / "capture")
    config = json.loads((source / "config.json").read_text())
    steps = {
        r["episode"]: r["steps"]
        for r in map(json.loads, (store.root / "steps.jsonl").read_text().splitlines())
    }
    missing = []
    for index in config["indices"]:
        episode = f"{index}:speculative"
        for step in steps[episode]:
            if step["tool"] != "search" or step["step"] >= config["max_steps"]:
                continue
            observation = [
                n
                for n in store.nodes
                if n["episode"] == episode
                and n["step"] == step["step"]
                and n["kind"] == "model"
                and n["branch"] == "observation_speculator"
            ]
            hypothetical = [
                n
                for n in store.nodes
                if n["episode"] == episode
                and n["step"] == step["step"] + 1
                and n["kind"] == "generation"
                and n["branch"] == "speculative_actor"
            ]
            if not observation or not hypothetical:
                missing.append(
                    {
                        "episode": episode,
                        "step": step["step"],
                        "observation_missing": not observation,
                        "hypothetical_missing": not hypothetical,
                    }
                )
    return {
        "windows_needing_models": missing,
        "minimum_new_model_calls": sum(
            int(r["observation_missing"]) + int(r["hypothetical_missing"]) for r in missing
        ),
        "note": "Retries may add requests; candidate Search gaps are enumerated once candidate outputs exist",
    }


async def complete(source, output, *, backend="mock", upstream=None, max_usd=0.5, max_requests=600):
    if (
        not math.isfinite(max_usd)
        or max_usd <= 0
        or type(max_requests) is not int
        or max_requests < 1
    ):
        raise ValueError("Use positive finite completion budgets")
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError("Choose a fresh bank output directory")
    audit = json.loads((source / "capture-audit.json").read_text())
    if not audit["passed"]:
        raise ValueError("Audit live capture before completing alternatives")
    live = CaptureStore(source / "capture")
    config = json.loads((source / "config.json").read_text())
    if backend != config["backend"]:
        raise ValueError("Bank backend must match captured backend")
    upstream = Path(upstream or Path("data/raw/speculative-action") / REVISION)
    # Match precisely the same pinned source. No preparation/download is performed.
    for name, identity in config["upstream"]["files"].items():
        if hashlib.sha256((upstream / name).read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError(f"Upstream changed: {name}")
    module = load_module(upstream)
    output.mkdir(parents=True)
    write_json(
        output / "completion-plan.json",
        {
            **needed_windows(source),
            "max_usd": max_usd,
            "max_requests": max_requests,
            "backend": backend,
        },
    )
    events = Events(output / "events.jsonl")
    capture = Capture(output / "completion", events.start, phase="bank")
    steps_by_episode = {
        r["episode"]: r["steps"]
        for r in map(json.loads, (live.root / "steps.jsonl").read_text().splitlines())
    }
    tasks = {
        r["episode"]: r
        for r in (json.loads(p.read_text()) for p in (source / "tasks").glob("*.json"))
    }
    import httpx

    tapes, forecast_cases, labels = [], [], []
    async with httpx.AsyncClient(timeout=180) as client:
        if backend == "http":
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise ValueError("Set OPENROUTER_API_KEY")
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
                max_usd,
                max_requests,
                config["actor"],
                config["speculator"],
                min_request_interval_s=max(1.1, config.get("min_request_interval_s", 0.0)),
            )
            search = WikiSearch(module, events)
        else:
            chat, search = MockChat(), MockSearch(events)
        runtime = Runtime(module, chat, search, events, "", capture=capture)
        try:
            for position, index in enumerate(config["indices"]):
                episode = f"{index}:speculative"
                task = tasks[episode]
                tape = {
                    "task_id": str(index),
                    "episode": episode,
                    "question": task["question"],
                    "answer": task["answer"],
                    "em": task["em"],
                    "f1": task["f1"],
                    "forced_finish": task["forced_finish"],
                    "candidate_lifetime": task.get("candidate_lifetime", "next_action"),
                    "steps": [],
                }
                episode_nodes = [n for n in live.nodes if n["episode"] == episode]
                # Search uses a fresh isolated WikiEnv. Exact-query results may
                # be shared within a frozen tape, never across different queries.
                search_bank = {}
                for n in episode_nodes:
                    if n["kind"] == "search" and n["status"] == "completed":
                        query = live.blob(n["input"])["query"]
                        search_bank.setdefault(query, (live, n))
                for captured_step in steps_by_episode[episode]:
                    step = captured_step["step"]
                    boundary = live.by_id[captured_step["boundary"]]
                    boundary_input = live.blob(boundary["input"])
                    before = live.blob(boundary["output"])
                    actor = live.by_id[captured_step["actor"]]
                    application = live.by_id[captured_step["application"]]
                    row = {
                        "step": step,
                        "action": boundary_input["action"],
                        "thought": boundary_input["thought"],
                        "actor_duration_s": generation_span(live, actor),
                        "actor_elapsed_s": actor["end_s"]
                        - min(
                            live.by_id[n]["ready_s"] for n in live.blob(actor["input"])["attempts"]
                        ),
                        "observed_excerpt": live.blob(application["output"])["observation"][:4096],
                        "actor_node": actor["id"],
                        "state_before": boundary["output"],
                        "application_node": application["id"],
                        "application_output": application["output"],
                        "window": None,
                        "tool": captured_step["tool"],
                        "query": captured_step["query"],
                    }
                    if row["tool"] == "search":
                        required = live.by_id[captured_step["search"]]
                        row.update(
                            tool_duration_s=required["service_s"],
                            tool_queue_s=required["queue_s"],
                            tool_result={"store": "live", "blob": required["output"]},
                            tool_node=required["id"],
                        )
                    else:
                        row.update(tool_duration_s=application["local_service_s"], tool_queue_s=0.0)
                    if row["tool"] == "search" and step < config["max_steps"]:
                        observations = [
                            n
                            for n in episode_nodes
                            if n["kind"] == "model"
                            and n["branch"] == "observation_speculator"
                            and n["step"] == step
                        ]
                        if observations:
                            observation_store, observation = live, observations[-1]
                        else:
                            _, identity = await runtime.model(
                                module.PromptTemplates.GUESS_STEP_PROMPT.format(row["query"]),
                                "observation_speculator",
                                episode,
                                step,
                                [boundary["id"]],
                            )
                            observation_store, observation = capture, capture.nodes[-1]
                            assert observation["id"] == identity

                        def read(store, identity):
                            return (
                                store.blob(identity)
                                if isinstance(store, CaptureStore)
                                else json.loads((store.blobs / (identity + ".json")).read_text())
                            )

                        prediction = read(observation_store, observation["output"])["content"]
                        obs = module.environment.WikiEnv.get_page_obs(prediction).replace("\n", "")
                        hypothetical_prefix = boundary_input[
                            "prefix"
                        ] + module.PromptTemplates.NEXT_STEP_PROMPT.format(
                            i=step, thought=boundary_input["thought"], action=row["action"], obs=obs
                        )
                        generations = [
                            n
                            for n in episode_nodes
                            if n["kind"] == "generation"
                            and n["branch"] == "speculative_actor"
                            and n["step"] == step + 1
                        ]
                        if generations:
                            gen_store, generation = live, generations[-1]
                            if live.blob(generation["input"])["prefix"] != hypothetical_prefix:
                                raise ValueError(
                                    "Existing hypothetical input differs from frozen boundary"
                                )
                            actions = live.blob(generation["output"])["actions"]
                            hypothetical_duration = generation_span(live, generation)
                        else:
                            _, actions = await runtime.generate(
                                hypothetical_prefix,
                                step + 1,
                                3,
                                "speculative_actor",
                                episode,
                                [observation["id"]],
                            )
                            gen_store, generation = capture, capture.nodes[-1]
                            inputs = read(capture, generation["input"])
                            children = {n["id"]: n for n in capture.nodes}
                            hypothetical_duration = sum(
                                children[n]["service_s"] for n in inputs["attempts"]
                            ) + max(
                                0.0,
                                generation["ready_s"] - children[inputs["attempts"][-1]]["end_s"],
                            )
                        candidates = []
                        for rank, action in enumerate(actions, 1):
                            tool, query = split_action(action)
                            candidate = {
                                "rank": rank,
                                "action": action,
                                "tool": tool,
                                "query": query,
                                "eligible": tool == "search" and query != row["query"],
                            }
                            if candidate["eligible"]:
                                if query not in search_bank:
                                    result = await runtime.search_call(
                                        query, episode, step + 1, True, [generation["id"]]
                                    )
                                    tool_node = next(
                                        n
                                        for n in capture.nodes
                                        if n["id"] == result["capture_node"]
                                    )
                                    search_bank[query] = (capture, tool_node)
                                tool_store, tool_node = search_bank[query]
                                candidate.update(
                                    duration_s=tool_node["service_s"],
                                    queue_s=tool_node["queue_s"],
                                    result={
                                        "store": "live" if tool_store is live else "bank",
                                        "blob": tool_node["output"],
                                    },
                                    node=tool_node["id"],
                                )
                                case = {
                                    "id": f"{index}:{step}:{rank}",
                                    "task_id": str(index),
                                    "question": task["question"],
                                    "completed_steps": step - 1,
                                    "phase": "running",
                                    "elapsed_s": 0.0,
                                    "history": [s["action"] for s in tape["steps"]]
                                    + [row["action"]],
                                    "previous_result_excerpt": before.get("obs"),
                                    "candidate": action,
                                    "candidate_rank": rank,
                                }
                                forecast_cases.append(case)
                                future = task["trajectory"][step:]
                                next_search = next(
                                    (s for s in future if split_action(s["action"])[0] == "search"),
                                    None,
                                )
                                labels.append(
                                    {
                                        "id": case["id"],
                                        "next_search": next_search["action"]
                                        if next_search
                                        else None,
                                        "reuse": bool(
                                            next_search
                                            and split_action(next_search["action"])[1] == query
                                        ),
                                    }
                                )
                            candidates.append(candidate)
                        row["window"] = {
                            "observation_duration_s": model_span(observation),
                            "hypothetical_duration_s": hypothetical_duration,
                            "observation_node": observation["id"],
                            "hypothetical_node": generation["id"],
                            "observation_store": "live" if observation_store is live else "bank",
                            "hypothetical_store": "live" if gen_store is live else "bank",
                            "candidates": candidates,
                        }
                    tape["steps"].append(row)
                tapes.append(tape)
                write_json(output / "tapes-checkpoint.json", tapes)
                print(
                    f"Bank {position + 1}/{len(config['indices'])}: {index}, completed {len(tape['steps'])} steps",
                    flush=True,
                )
        finally:
            if not (capture.output / "nodes.jsonl").exists():
                (capture.output / "nodes.jsonl").write_text("")
            capture.seal()
            write_json(
                output / "completion-usage.json",
                {
                    "requests": len(chat.records),
                    "cost_usd": sum(r["cost_usd"] or 0 for r in chat.records),
                    "failures": sum(bool(r["failure"]) for r in chat.records),
                    "unknown_costs": sum(r["cost_usd"] is None for r in chat.records),
                },
            )
    shutil.copytree(live.root, output / "live-capture")
    write_json(
        output / "tapes.json",
        {
            "version": 1,
            "complete": True,
            "tapes": tapes,
            "capture_version": 2,
            "source_config": config,
            "assumptions": [
                "Authoritative trajectories, outputs and answer scores held fixed",
                "Exact-query Wikipedia results frozen per episode; measured service time reused",
                "Measured model service and parsing times reused; collection pacing/queue is excluded but retained in capture",
                "Provider serving capacity is not measured under contention",
                "Skipped/late alternatives completed outside live benchmark",
                "Forecast cases are label-blind phase-entry contexts with elapsed=0",
            ],
        },
    )
    write_json(output / "forecast-cases.json", forecast_cases)
    write_json(output / "forecast-labels.json", labels)
    inventory = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file() and p.name != "dataset-manifest.json"
    }
    write_json(
        output / "dataset-manifest.json",
        {
            "version": 1,
            "files": inventory,
            "questions": len(tapes),
            "forecast_cases": len(forecast_cases),
        },
    )
    return {
        "questions": len(tapes),
        "forecast_cases": len(forecast_cases),
        "completion": json.loads((output / "completion-usage.json").read_text()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--backend", choices=("mock", "http"), default="mock")
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--max-usd", type=float, default=0.5)
    parser.add_argument("--max-requests", type=int, default=600)
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(needed_windows(args.source), indent=2))
    else:
        if args.output is None:
            parser.error("--output is required for completion")
        print(
            json.dumps(
                asyncio.run(
                    complete(
                        args.source,
                        args.output,
                        backend=args.backend,
                        upstream=args.upstream,
                        max_usd=args.max_usd,
                        max_requests=args.max_requests,
                    )
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
