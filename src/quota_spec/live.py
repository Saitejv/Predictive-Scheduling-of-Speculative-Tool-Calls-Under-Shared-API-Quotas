"""Measured live scripted-agent validation against replay and exact result reuse.

This checks tool-result fidelity and evidence coverage. It does not claim LLM
answer exact match; use quota_spec.qa with a configured main model for that.
"""

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from .gateway import Gateway
from .models import AgentState, Call, load_tasks, positive_int
from .policies import CurrentCapacity, FixedReserve, NoSpeculation
from .replay import Replay
from .search import SearchCorpus, candidate_query, required_query


async def validate(data: Path, output: Path, count=12, agents=4):
    positive_int(count, "count")
    positive_int(agents, "agents")
    corpus = SearchCorpus.load(data / "corpus.json")
    tasks = load_tasks(json.loads((data / "pilot.json").read_text()))[:count]
    labels = {r["task_id"]: r for r in json.loads((data / "labels.json").read_text())}
    if not tasks:
        raise ValueError("Pilot trace is empty")
    output.mkdir(parents=True, exist_ok=True)
    all_outputs, summary = {}, {}
    for name, policy in (
        ("no_speculation", NoSpeculation()),
        ("current_capacity", CurrentCapacity()),
        ("fixed_reserve", FixedReserve(1)),
    ):

        async def tool(call):
            await asyncio.sleep(0.01)
            return await asyncio.to_thread(corpus.search, json.loads(call.arguments_json)["query"])

        gateway = Gateway(tool, capacity=3, window_s=0.1, policy=policy, expected_duration_s=0.015)
        semaphore = asyncio.Semaphore(agents)
        outputs, arrivals, finishes = {}, {}, {}

        async def agent(task):
            async with semaphore:
                arrivals[task.task_id] = gateway.now()
                results, previous, evidence = [], [], []
                for index, step in enumerate(task.steps):
                    now = gateway.now()
                    await gateway.observe(
                        AgentState(
                            task.task_id,
                            now,
                            index,
                            "thinking",
                            now,
                            task_context=task.task_context,
                            history=tuple(Call.search(q) for q in previous),
                            result_excerpt=json.dumps(results)[:1024],
                        )
                    )
                    candidate = candidate_query(task.task_context, results, index)
                    if candidate:
                        await gateway.speculate(task.task_id, Call.search(candidate))
                    query = required_query(task.task_context, results, previous, index)
                    await asyncio.sleep(step.think_s)
                    results = await gateway.required(task.task_id, Call.search(query))
                    previous.append(query)
                    evidence.append(results)
                finishes[task.task_id] = gateway.now()
                outputs[task.task_id] = {"queries": previous, "evidence": evidence}
                await gateway.finish_task(task.task_id)

        try:
            await asyncio.gather(*(agent(task) for task in tasks))
            # Drain optional work before closing, so every dispatch gets an outcome.
            await asyncio.gather(
                *(e.worker for e in gateway.registry.values() if e.worker), return_exceptions=True
            )
            counts = Counter(
                e["window_index"] for e in gateway.events if e["event"] == "call_started"
            )
            if any(n > 3 for n in counts.values()):
                raise AssertionError("Live gateway exceeded fixed-window quota")
            all_outputs[name] = outputs
            live_mean = sum(finishes[t.task_id] - arrivals[t.task_id] for t in tasks) / len(tasks)
            replay_tasks = tuple(
                replace(
                    t,
                    arrival_s=arrivals[t.task_id],
                    deadline_s=None
                    if t.deadline_s is None
                    else arrivals[t.task_id] + t.deadline_s - t.arrival_s,
                )
                for t in tasks
            )
            replay = Replay(replay_tasks, 3, 0.1).run(policy)
            replay_mean = replay.metrics["mean_completion_s"]
            matches = True if name == "no_speculation" else outputs == all_outputs["no_speculation"]
            if not matches:
                raise AssertionError("Speculation changed required queries or result contents")
            support_recall = []
            for tid, result in outputs.items():
                titles = {d["title"] for step in result["evidence"] for d in step}
                gold = set(labels[tid]["supporting_titles"])
                support_recall.append(len(titles & gold) / max(1, len(gold)))
            summary[name] = {
                "tasks": len(tasks),
                "concurrency_limit": agents,
                "live_mean_completion_s": live_mean,
                "replay_mean_completion_s": replay_mean,
                "live_minus_replay_s": live_mean - replay_mean,
                "exact_evidence_equal_to_baseline": matches,
                "mean_supporting_title_recall": sum(support_recall) / len(support_recall),
                "answer_exact_match": None,
                "quota_valid": True,
                "calls_started": sum(counts.values()),
                "corpus_sha256": corpus.digest,
                "limitation": "Scripted retrieval agent; replay uses recorded timing estimates. No LLM QA answer generated.",
            }
            (output / f"{name}.jsonl").write_text(
                "".join(json.dumps(e) + "\n" for e in gateway.events)
            )
        finally:
            await gateway.close()
    (output / "outputs.json").write_text(json.dumps(all_outputs, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("results/live"))
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--agents", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(validate(args.data, args.output, args.count, args.agents))


if __name__ == "__main__":
    main()
