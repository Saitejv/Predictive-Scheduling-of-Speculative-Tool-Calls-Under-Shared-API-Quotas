"""Test the actual query generator on fixed authoritative paths.

Fresh queries have explicit constant counterfactual Search service. Required
observations/answers come from verified tapes. Unknown unused queries never
supply observations to an actor. This is not a native Search benchmark.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import shutil
import time
from pathlib import Path

import httpx
from study_team_context import DATA, initialize, persist

from quota_spec.artifacts import write_json
from quota_spec.capture import CaptureStore
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset, scheduling_options
from quota_spec.hotpot_runtime import Events
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.quota_speculation import parse_queries, planner_prompt
from quota_spec.team_context import query_planner_context
from quota_spec.transport import InvalidProviderResponse, LiveChat


def prefixes_for(tapes):
    stores, prefixes = {}, {}
    for tape in tapes:
        for step in tape["steps"]:
            window = step["window"]
            if not window or step["step"] > 4:
                continue
            key = (tape["shard"], window["hypothetical_store"])
            if key not in stores:
                directory = "live-capture" if key[1] == "live" else "completion"
                stores[key] = CaptureStore(DATA / "parts" / key[0] / directory)
            store = stores[key]
            node = store.by_id[window["hypothetical_node"]]
            assert node["kind"] == "generation" and node["branch"] == "speculative_actor"
            prefixes[tape["task_id"], step["step"]] = store.blob(node["input"])["prefix"]
    return prefixes


async def experiment(output, max_usd, count, seeds):
    all_tapes = load_dataset(DATA)["tapes"]
    tapes = all_tapes[20 : 20 + count]
    if len(tapes) != count or count < 1:
        raise ValueError("Choose 1..80 evaluation questions")
    prefixes = prefixes_for(tapes)
    cases = []
    settings = [(4, 8, 5), (8, 12, 3)]
    for seed in seeds:
        cells = [(a, c, w, d) for a, c, w in settings for d in [0.1, 3.0]]
        random.Random(5851800 + seed).shuffle(cells)
        for a, c, w, d in cells:
            modes = ["all", "quota", "quota_team"]
            random.Random(5851900 + seed + a + int(d * 10)).shuffle(modes)
            cases.extend(
                dict(agents=a, capacity=c, window_s=w, search_s=d, seed=seed, policy=p)
                for p in modes
            )
    initialize(output, "actual_query_planner_fixed_path_test", tapes, cases, max_usd)
    protocol = json.loads((output / "protocol.json").read_text())
    protocol.update(
        actual_query_generator=True,
        generation_step_budget=4,
        main_actor_replayed=True,
        speculation_calls_live=True,
        settings=settings,
        order_seeds=seeds,
        queries_restricted_to_saved_candidates=False,
        full_speculation="Quota-blind planner; dispatch every valid generated Search under FIFO/hard cap",
        correctness="All authoritative actions, observations, answers fixed. Fresh unused queries need no materialized observation. Exact hits use verified captured required-query observations.",
        source_observation="Saved observation-prediction prefix and latency; replace hypothetical query-generation inference with actual current planner calls",
        service="Explicit constant Search time for every required/fresh optional Search, not measured native latency",
        assumptions="Unlimited simultaneous model/tool provider capacity in simulated timeline; actual collected planner RTT charged, including retry/backoff",
        collection_pacing="At least 0.75s between completed model collection and next submit; excluded from simulated service and logged separately",
        prefix_sha256={
            f"{tid}:{step}": hashlib.sha256(prefix.encode()).hexdigest()
            for (tid, step), prefix in prefixes.items()
        },
        limitations="Exploratory reuse of historical eval cohort. Two order/model samples, not a new held-out confirmation. Full uses same step-4 generation budget.",
    )
    write_json(output / "protocol.json", protocol)
    (output / "controller-source.py").write_bytes(Path(__file__).read_bytes())
    prices = json.loads(
        Path("results/quota-win-2026-11-15-native-capture/pricing.json").read_text()
    )
    rows, seen = [], set()
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(timeout=45) as client:
        chat = LiveChat(
            client,
            os.environ["OPENROUTER_API_KEY"],
            prices,
            output,
            Events(),
            max_usd,
            2000,
            "google/gemini-2.5-flash",
            "openai/gpt-4.1-nano",
            reserve_unknown_cost=True,
        )

        next_collect = 0.0

        async def generate(prompt, tid, step):
            nonlocal next_collect
            pacing = max(0.0, next_collect - time.perf_counter())
            if pacing:
                await asyncio.sleep(pacing)
            started = time.perf_counter()
            for attempt in range(6):
                if shutil.disk_usage(output).free < 150 * 1024**2:
                    raise RuntimeError("Low disk space; stopping before another paid call")
                try:
                    content = await chat.call(prompt, "speculative_actor", tid, step)
                    parse_queries(content, 3)
                    elapsed = time.perf_counter() - started
                    next_collect = time.perf_counter() + 0.75
                    return content, elapsed, pacing
                except (httpx.HTTPError, InvalidProviderResponse, ValueError) as exc:
                    if attempt == 5:
                        raise
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (
                        429,
                        500,
                        502,
                        503,
                        504,
                    ):
                        raise
                    delay = (5, 15, 30, 60, 60)[attempt]
                    if isinstance(exc, httpx.HTTPStatusError):
                        try:
                            delay = max(delay, float(exc.response.headers.get("retry-after", "0")))
                        except ValueError:
                            pass
                    print("RETRY", type(exc).__name__, "backoff_s", delay, flush=True)
                    await asyncio.sleep(delay)

        try:
            for number, case in enumerate(cases):
                if (output / "STOP").exists():
                    raise RuntimeError("Stopped between completed cases")
                ordered = list(tapes)
                random.Random(case["seed"]).shuffle(ordered)

                def provider(state, step):
                    quota = (
                        None
                        if case["policy"] == "all"
                        else query_planner_context(
                            state, include_peers=case["policy"] == "quota_team"
                        )
                    )
                    prefix = prefixes[state.task_id, step]
                    prompt = planner_prompt(prefix, step + 1, 3, quota)
                    before = chat.requests
                    content, elapsed, pacing = asyncio.run_coroutine_threadsafe(
                        generate(prompt, state.task_id, step + 1), loop
                    ).result()
                    actions = parse_queries(content, 3)
                    return dict(
                        queries=[a[7:-1] for a in actions],
                        latency_s=elapsed,
                        provenance=dict(
                            collection_pacing_s=pacing,
                            planner=case["policy"],
                            quota=quota,
                            receipts=list(range(before + 1, chat.requests + 1)),
                            prefix_sha256=hashlib.sha256(prefix.encode()).hexdigest(),
                            hypothetical_step=step + 1,
                        ),
                    )

                def run(rule, hook=None):
                    result = FrozenReplay(
                        ordered,
                        case["capacity"],
                        case["window_s"],
                        tool_duration_s=case["search_s"],
                        max_active_agents=case["agents"],
                        max_candidate_age=7,
                        suppress_known_calls=True,
                        revalidate_reset=True,
                        max_generation_step=4,
                        generation_provider=hook,
                        **scheduling_options("overlap"),
                    ).run(rule)
                    validate(result, ordered, case["capacity"], case["window_s"], case["agents"])
                    return result

                result = await asyncio.to_thread(run, CurrentCapacity(), provider)
                rows.append(persist(output, case, result))
                key = (
                    case["agents"],
                    case["capacity"],
                    case["window_s"],
                    case["search_s"],
                    case["seed"],
                )
                if key not in seen:
                    rows.append(persist(output, {**case, "policy": "none"}, run(NoSpeculation())))
                    seen.add(key)
                write_json(
                    output / "progress.json",
                    dict(
                        completed_cases=number + 1,
                        total_cases=len(cases),
                        budget_charge_usd=chat.spent,
                        requests=chat.requests,
                    ),
                )
                print(
                    "COMPLETE",
                    number + 1,
                    "/",
                    len(cases),
                    case,
                    "mean",
                    result["metrics"]["mean_completion_s"],
                    "batch",
                    result["metrics"]["resource_makespan_s"],
                    "budget",
                    chat.spent,
                    flush=True,
                )
            write_json(output / "rows.json", rows)
            write_json(
                output / "validation.json",
                dict(
                    passed=True,
                    cases=len(cases),
                    schedules=len(rows),
                    authoritative_paths_and_answers_preserved=True,
                    provider_requests=chat.requests,
                ),
            )
        finally:
            write_json(
                output / "accounting.json",
                dict(
                    requests=chat.requests,
                    budget_charge_usd=chat.spent,
                    known_cost_usd=sum(r.get("cost_usd") or 0 for r in chat.records),
                    unknown_cost_attempts=sum(r.get("cost_usd") is None for r in chat.records),
                ),
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-usd", type=float, default=2)
    p.add_argument("--count", type=int, default=16)
    p.add_argument("--seeds", type=int, nargs="+", default=[248, 249])
    args = p.parse_args()
    asyncio.run(experiment(args.output, args.max_usd, args.count, args.seeds))
