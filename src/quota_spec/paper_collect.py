"""Collect the pinned ReAct/Wikipedia workload for paired shared-quota replay.

Authoritative and hypothetical branches are measured separately. Replay places
them on their dependency graph; serial collection wall time is never a speedup.
Only Search consumes shared quota. Lookup and Finish remain stateful local steps.
"""

import copy
import json
import os
import re
import time
from contextlib import nullcontext
from unittest.mock import patch

from .collect_qa import write_json
from .experiments import source_hashes
from .models import Call, Step, Task
from .paper import (
    INFERENCE_CONTEXT,
    compatibility_fixes,
    load_upstream,
    paper_indices,
    prepare,
    text_client,
    working_directory,
)
from .search import sha256_json
from .workload import dump_tasks

TOOL_FIELDS = ("page", "obs", "lookup_keyword", "lookup_list", "lookup_cnt", "steps", "answer")


def parse_paper_action(action):
    match = re.fullmatch(r"(Search|Lookup|Finish)\[([^\]\n]*)\]", action, flags=re.IGNORECASE)
    if match is None:
        raise ValueError("Invalid paper action")
    tool, value = match.groups()
    tool = tool.lower()
    if tool == "search":
        return Call.search(value)
    return Call(tool, json.dumps({"keyword" if tool == "lookup" else "answer": value}))


def normalize(
    task_id, question, normal, simulated, timings, candidate_durations, terminal_duration=0.0
):
    """Retain every ReAct action and release proposals from the previous tool.

    A top-one Search suggestion is a candidate; Lookup/Finish suggestions remain
    in the raw branch log but do not request shared search quota. No future real
    response is used to construct a speculative model input.
    """
    steps = []
    for index, action in enumerate(normal["actions"]):
        required = parse_paper_action(action)
        guesses = simulated["actions"][index]
        candidate = parse_paper_action(guesses[0]) if index and guesses else None
        if candidate is not None and candidate.tool != "search":
            candidate = None
        duration = normal["time_taken"][index]
        candidate_duration = 0.0
        if candidate is not None:
            query = json.loads(candidate.arguments_json)["query"]
            candidate_duration = duration if candidate == required else candidate_durations[query]
        delay = (
            simulated["time_taken"][index - 1] + timings[index]["speculative_actor"]
            if index and candidate
            else 0.0
        )
        steps.append(
            Step(
                think_s=timings[index]["actor"],
                required=required,
                duration_s=duration,
                candidate=candidate,
                candidate_duration_s=candidate_duration,
                result_excerpt=normal["observations"][index][:1024],
                candidate_delay_s=delay,
                quota_required=required.tool == "search",
                candidate_trigger="previous_tool_start" if candidate else "phase_entry",
            )
        )
    return Task(task_id, 0, tuple(steps), task_context=question, final_think_s=terminal_duration)


def mock_transports():
    """Synthetic transports with the genuine upstream prompt/parser/tool code."""
    import httpx
    import requests

    def chat(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][-1]["content"]
        if prompt.startswith("Give me information about"):
            content = "Mock entity is an article. It contains the mock keyword."
        else:
            matches = re.findall(r"about the (\d+)th action", prompt)
            step = int(matches[-1])
            action = {1: "Search[Mock entity]", 2: "Lookup[mock]", 3: "Search[Mock second]"}.get(
                step, "Finish[mock answer]"
            )
            widths = re.findall(r"return (\d+) candidates for the next action", prompt)
            width = int(widths[-1]) if widths else 1
            tool = action.split("[", 1)[0]
            actions = [action] + [f"{tool}[Mock alternative {i}]" for i in range(1, width)]
            content = f"Thought {step}: Use the observed evidence.\nAction {step}: " + ", ".join(
                actions
            )
        time.sleep(0.001)
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0},
            },
        )

    def wiki(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = (
            b"<html><p>Mock entity is an article. It contains the mock keyword.</p></html>"
        )
        time.sleep(0.001)
        return response

    return httpx.MockTransport(chat), wiki


def collect(
    data_root,
    output,
    *,
    count=20,
    actor="google/gemini-2.5-flash",
    speculator="google/gemini-2.5-flash",
    backend="http",
    max_requests=512,
    resume=False,
    width=1,
    enforce_width=True,
):
    if backend not in ("http", "mock"):
        raise ValueError("Choose http or mock")
    if count < 1 or max_requests <= 0 or width not in (1, 3):
        raise ValueError("Use at least one task, width 1/3 and a positive request budget")
    if backend == "http" and not os.environ.get("OPENROUTER_API_KEY"):
        raise ValueError("Set OPENROUTER_API_KEY")
    indices = paper_indices(count)
    root = prepare(data_root)
    output = output.resolve()
    config = {
        "version": 1,
        "backend": backend,
        "actor": actor,
        "speculator": speculator,
        "indices": indices,
        "width": width,
        "enforce_width": enforce_width,
        "max_steps": 7,
        "source_sha256": source_hashes(),
        "upstream": json.loads((root / "upstream.json").read_text()),
        "protocol": "Observation speculation; original ReAct actions; normalized replay retains first Search candidate",
    }
    config_path = output / "collection_config.json"
    if resume:
        if not config_path.exists() or json.loads(config_path.read_text()) != config:
            raise ValueError("Resume requires unchanged source, models and workload")
    elif output.exists() and any(output.iterdir()):
        raise ValueError("Choose a fresh collection directory")
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks").mkdir(exist_ok=True)
    write_json(config_path, config)
    inference_path = output / "inference.jsonl"
    records = (
        [json.loads(line) for line in inference_path.read_text().splitlines()]
        if inference_path.exists()
        else []
    )
    transport, wiki = mock_transports() if backend == "mock" else (None, None)
    if wiki is None:
        import requests

        original_get = requests.get

        def wiki(*args, **kwargs):
            kwargs.setdefault("timeout", 30)
            response = original_get(*args, **kwargs)
            response.raise_for_status()
            return response

    module = load_upstream(
        root,
        text_client(
            records,
            max_requests,
            inference_path,
            transport=transport,
            api_key="synthetic" if transport else None,
        ),
    )
    compatibility_fixes(module)
    module.constants.guess_num_actions = width
    module.wrappers.DATA_DIR = str(root / "hotpotqa/data")
    examples = json.loads((root / "hotpotqa/prompts/prompts_naive.json").read_text())[
        "webthink_simple6"
    ]
    prompt = module.Utils.join_prompt(
        module.PromptTemplates.REACT_INSTRUCTION,
        examples,
        module.PromptTemplates.PROMPT_INSTRUCTION,
    )
    completed = []
    with (
        working_directory(output),
        patch("requests.get", side_effect=wiki) if wiki else nullcontext(),
    ):
        for position, index in enumerate(indices):
            path = output / "tasks" / f"{index}.json"
            prior = json.loads(path.read_text()) if path.exists() else None
            if prior and prior.get("failure") is None:
                if prior.get("sha256") != sha256_json(
                    {k: v for k, v in prior.items() if k != "sha256"}
                ):
                    raise ValueError("Saved paper task checksum mismatch")
                completed.append(prior)
                continue
            runner = module.HotPotQARun(actor, speculator, to_print_output=False)
            runner.current_index = index
            runner.base_traj_path = str(output / "logs")
            timing = {}
            calls = {}
            generate = runner.generate_thought_actions
            step = runner.step
            pre_tool = {}
            terminal = {}

            def measured_generate(i, running_prompt, counters, num_actions=1, max_retries=1):
                role = "actor" if calls.get(i, 0) == 0 else "speculative_actor"
                calls[i] = calls.get(i, 0) + 1
                token = INFERENCE_CONTEXT.set({"task_id": str(index), "step": i, "role": role})
                before = time.perf_counter()
                try:
                    thought, actions = generate(
                        i, running_prompt, counters, num_actions, max_retries
                    )
                    return thought, actions[:num_actions] if enforce_width else actions
                except ValueError as exc:
                    # Upstream catches ValueError and skips this numbered iteration.
                    # Such gaps lose authoritative delay and misalign branch indices;
                    # retain the failed episode rather than normalize it as success.
                    raise RuntimeError("Canonical action generation failed") from exc
                finally:
                    timing.setdefault(i, {})[role] = time.perf_counter() - before
                    INFERENCE_CONTEXT.reset(token)

            def measured_step(env, action, simulate=False):
                real_env = env.unwrapped
                i = len(env.normal_trajectory_dict["actions"]) + int(not simulate)
                token = INFERENCE_CONTEXT.set(
                    {
                        "task_id": str(index),
                        "step": i,
                        "role": "observation_speculator" if simulate else "tool",
                    }
                )
                current = None
                try:
                    if not simulate:
                        pre_tool[i] = {k: copy.deepcopy(getattr(real_env, k)) for k in TOOL_FIELDS}
                    else:
                        current = {k: copy.deepcopy(getattr(real_env, k)) for k in TOOL_FIELDS}
                        for key, value in pre_tool[i].items():
                            setattr(real_env, key, copy.deepcopy(value))
                    before_step = time.perf_counter()
                    result = step(env, action, simulate)
                    # Upstream times only the last successful HTTP attempt. Keep
                    # all real tool retry time in the measured dependency instead.
                    result = (*result[:-1], time.perf_counter() - before_step)
                    if not simulate and action.startswith("finish[") and i not in timing:
                        terminal.update(action=action, duration_s=result[-1])
                    return result
                finally:
                    if current is not None:
                        for key, value in current.items():
                            setattr(real_env, key, value)
                    INFERENCE_CONTEXT.reset(token)

            runner.generate_thought_actions = measured_generate
            runner.step = measured_step
            before_records = len(records)
            try:
                info = runner.webthink(idx=index, prompt=prompt, to_print=False, n=8, simulate=True)
                normal, simulated = (
                    runner.env.normal_trajectory_dict,
                    runner.env.sim_trajectory_dict,
                )
                durations = {}
                for i, candidates in enumerate(simulated["actions"]):
                    if not i or not candidates:
                        continue
                    candidate = parse_paper_action(candidates[0])
                    if candidate.tool != "search":
                        continue
                    query = json.loads(candidate.arguments_json)["query"]
                    if candidate == parse_paper_action(normal["actions"][i]):
                        durations[query] = normal["time_taken"][i]
                    elif query not in durations:
                        isolated = module.environment.WikiEnv(speculator)
                        before = time.perf_counter()
                        isolated.step("search[" + query + "]")
                        durations[query] = time.perf_counter() - before
                question = runner.env.data[index][0]
                ordered_timings = [timing[i] for i in range(1, len(normal["actions"]) + 1)]
                task = normalize(
                    str(index),
                    question,
                    normal,
                    simulated,
                    ordered_timings,
                    durations,
                    terminal_duration=terminal.get("duration_s", 0),
                )
                result = {
                    "task_id": str(index),
                    "question_index": runner.env.data_idx,
                    "split": "development" if position < count // 2 else "evaluation",
                    "trace": dump_tasks((task,))[0],
                    "normal": normal,
                    "simulated": simulated,
                    "timings": ordered_timings,
                    "candidate_durations": durations,
                    "forced_finalization": terminal or None,
                    "inference": records[before_records:],
                    "failure": None,
                    "answer": info.get("answer"),
                    "em": info.get("em") if backend == "http" else None,
                    "f1": info.get("f1") if backend == "http" else None,
                }
                result["sha256"] = sha256_json(result)
                write_json(path, result)
                completed.append(result)
                print(f"Collected upstream task {index} ({len(completed)}/{count})", flush=True)
            except Exception as exc:
                write_json(
                    path,
                    {
                        "task_id": str(index),
                        "failure": type(exc).__name__,
                        "inference": records[before_records:],
                        "normal": runner.env.normal_trajectory_dict,
                        "simulated": runner.env.sim_trajectory_dict,
                        "timings": timing,
                    },
                )
                raise ValueError(
                    f"Paper collection failed on task {index}; partial inference retained"
                ) from exc
    artifacts = {}
    for split in ("development", "evaluation"):
        rows = [r["trace"] for r in completed if r["split"] == split]
        write_json(output / f"{split}.json", rows)
        artifacts[f"{split}.json"] = sha256_json(rows)
    environment = {
        "upstream": config["upstream"],
        "actor": actor,
        "speculator": speculator,
        "backend": backend,
        "width": width,
        "enforce_width": enforce_width,
        "quota_tool": "Search",
        "observation_checksums": {r["task_id"]: sha256_json(r["normal"]) for r in completed},
        "candidate_generator": f"paper-observation-then-actor-top{width}",
    }
    write_json(output / "environment.json", environment)
    write_json(
        output / "manifest.json",
        {
            "environment": "paper_wikipedia",
            "environment_sha256": sha256_json(environment),
            "artifacts": artifacts,
            "agent": "mock upstream ReAct (synthetic)"
            if backend == "mock"
            else "upstream ReAct/Wikipedia",
            "candidate_generator": environment["candidate_generator"],
        },
    )
    return {"tasks": count, "output": str(output), "mock": backend == "mock"}
