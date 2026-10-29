"""Collect resumable, label-blind QA trajectories for frozen paired replay."""

import argparse
import asyncio
import json
import shutil
import time
from pathlib import Path

from .models import Call, Step, Task, positive_int
from .provenance import git_state
from .qa import HTTPQA, MockQA, answer_scores, parse_action
from .search import SearchCorpus, candidate_query, sha256_json
from .workload import dump_tasks


def write_json(path, value):
    """Atomic checkpoint replacement; a killed process cannot truncate the prior file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


async def trajectory(task, corpus, model, max_calls):
    history, steps, observations = [], [], []
    started = time.perf_counter()
    for index in range(max_calls + 1):
        before = time.perf_counter()
        candidate = candidate_query(
            task["task_context"], history[-1]["results"] if history else [], index
        )
        if index == max_calls:
            candidate = None  # The shared, observed search budget is exhausted.
        generation = time.perf_counter() - before
        observations.append(
            {
                "task_id": task["task_id"],
                "step": index,
                "observed_at_s": time.perf_counter() - started,
                "task_context": task["task_context"],
                "history": [h["query"] for h in history[-8:]],
                "result_excerpt": json.dumps(history[-1]["results"])[:1024] if history else "",
                "candidate_query": candidate,
                "candidate_generation_s": generation,
            }
        )
        action = parse_action(
            await model.decide(task["task_context"], history, index == max_calls),
            final=index == max_calls,
        )
        think = time.perf_counter() - before
        if action["action"] == "answer":
            final_think, final_candidate, final_delay = think, candidate, generation
            break
        query = action["query"]
        before_search = time.perf_counter()
        results = await asyncio.to_thread(corpus.search, query)
        duration = time.perf_counter() - before_search
        steps.append(
            Step(
                think,
                Call.search(query),
                duration,
                Call.search(candidate) if candidate else None,
                duration,
                json.dumps(results, ensure_ascii=False)[:1024],
                generation,
            )
        )
        history.append({"query": query, "results": results})
    completion = time.perf_counter() - started
    # Benchmark unused concrete candidates only after the agent has finished.
    # Neither benchmark results nor their timings are fed to the model/predictor.
    from dataclasses import replace

    async def benchmark(query):
        before = time.perf_counter()
        await asyncio.to_thread(corpus.search, query)
        return time.perf_counter() - before

    for index, step in enumerate(steps):
        if step.candidate is not None and step.candidate != step.required:
            duration = await benchmark(json.loads(step.candidate.arguments_json)["query"])
            steps[index] = replace(step, candidate_duration_s=duration)
    final_duration = await benchmark(final_candidate) if final_candidate else 0
    trace = Task(
        task["task_id"],
        0,
        tuple(steps),
        task_context=task["task_context"],
        final_think_s=final_think,
        final_candidate=Call.search(final_candidate) if final_candidate else None,
        final_candidate_duration_s=final_duration,
        final_candidate_delay_s=final_delay,
    )
    return {
        "trace": dump_tasks((trace,))[0],
        "answer": action["answer"],
        "history": history,
        "completion_s": completion,
        "observations": observations,
        "inference": list(model.records),
        "failure": None,
    }


async def collect(
    data,
    output,
    *,
    backend="mock",
    count=200,
    max_calls=3,
    resume=False,
    model_options=None,
    model_factory=None,
):
    positive_int(count, "count", 2)
    positive_int(max_calls, "max_calls")
    if max_calls > 16 or backend not in ("mock", "http"):
        raise ValueError("Use mock/http and at most 16 searches per task")
    options = model_options or {}
    from .experiments import source_hashes

    factory = model_factory or (lambda: MockQA() if backend == "mock" else HTTPQA(**options))
    probe = factory()  # Validate configuration before writing anything or issuing requests.
    corpus = SearchCorpus.load(data / "corpus.json")
    splits = {
        name: json.loads((data / f"{name}.json").read_text())
        for name in ("development", "evaluation")
    }
    if count > sum(map(len, splits.values())):
        raise ValueError("count exceeds the available frozen tasks")
    selected = {
        name: rows[: count // 2 + (count % 2 if name == "evaluation" else 0)]
        for name, rows in splits.items()
    }
    if sum(map(len, selected.values())) != count or any(not rows for rows in selected.values()):
        raise ValueError("Requested balanced split is unavailable")
    ids = [row["task_id"] for rows in selected.values() for row in rows]
    if len(set(ids)) != count:
        raise ValueError("Task IDs must be unique and development/evaluation disjoint")
    # Validate all files before any paid request. Labels remain outside trajectory/model inputs.
    source_manifest = json.loads((data / "manifest.json").read_text())
    if source_manifest.get("corpus_sha256") != corpus.digest:
        raise ValueError("Manifest does not match corpus")
    for name, rows in splits.items():
        expected = source_manifest.get("artifacts", {}).get(f"{name}.json")
        if expected and expected != sha256_json(rows):
            raise ValueError(f"Manifest does not match {name} trace")
    labels = json.loads((data / "labels.json").read_text())
    gold = {row["task_id"]: row for row in labels}
    if len(gold) != len(labels) or any(
        tid not in gold or not isinstance(gold[tid].get("answer"), str) for tid in ids
    ):
        raise ValueError(
            "Labels must contain unique task IDs and an answer for every selected task"
        )
    config = {
        "version": 2,
        "backend": backend,
        "max_calls": max_calls,
        "corpus_sha256": corpus.digest,
        "selected_tasks_sha256": sha256_json(selected),
        "labels_sha256": sha256_json(labels),
        "source_manifest_sha256": sha256_json(source_manifest),
        "model": getattr(probe, "model", "mock"),
        "url": getattr(probe, "url", None),
        "timeout_s": getattr(probe, "timeout_s", None),
        "input_price": getattr(probe, "input_price", None),
        "output_price": getattr(probe, "output_price", None),
        "token_parameter": getattr(probe, "token_parameter", None),
        "max_output_tokens": getattr(probe, "max_tokens", None),
        "source_sha256": source_hashes(),
    }
    # Credentials and injected transports are deliberately absent from artifacts.
    checkpoint = output / "collection_config.json"
    if resume:
        if not checkpoint.exists() or json.loads(checkpoint.read_text()) != config:
            raise ValueError(
                "Resume requires the same source tasks, corpus and model configuration"
            )
    elif output.exists() and any(output.iterdir()):
        raise ValueError("Output is not empty; choose a new directory or use --resume")
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks").mkdir(exist_ok=True)
    write_json(checkpoint, config)
    completed = {}
    for name, rows in selected.items():
        for task in rows:
            # Hash untrusted dataset IDs rather than interpreting them as paths.
            path = output / "tasks" / (sha256_json(task["task_id"]) + ".json")
            prior = json.loads(path.read_text()) if resume and path.exists() else None
            if prior and prior.get("failure") is None:
                if prior.get("sha256") != sha256_json(
                    {key: value for key, value in prior.items() if key != "sha256"}
                ):
                    raise ValueError("Saved collection task checksum mismatch")
                completed[task["task_id"]] = prior
                continue
            model = factory()
            if prior:
                # Retain earlier paid failures, even when a retry subsequently succeeds.
                attempts = output / "failed_attempts"
                attempts.mkdir(exist_ok=True)
                index = 1
                saved = attempts / f"{path.stem}-{index}.json"
                while saved.exists():
                    index += 1
                    saved = attempts / f"{path.stem}-{index}.json"
                write_json(saved, prior)
            try:
                result = await trajectory(task, corpus, model, max_calls)
            except Exception as exc:
                write_json(
                    path,
                    {
                        "task_id": task["task_id"],
                        "failure": type(exc).__name__,
                        "inference": list(model.records),
                    },
                )
                raise ValueError(
                    f"Collection stopped on {task['task_id']} ({type(exc).__name__}); "
                    "successful tasks are saved. Fix configuration and resume."
                ) from exc
            result["sha256"] = sha256_json(result)
            write_json(path, result)
            completed[task["task_id"]] = result
            print(f"Collected {len(completed)}/{count} ({name})", flush=True)
    # Scoring occurs only after all model decisions. Preserve the original split.
    outcomes = []
    for tid, result in completed.items():
        quality = (
            answer_scores(result["answer"], gold[tid]["answer"])
            if backend == "http"
            else {"exact_match": None, "f1": None}
        )
        outcomes.append(
            {
                "task_id": tid,
                "answer": result["answer"],
                "completion_s": result["completion_s"],
                **quality,
            }
        )
    for name, rows in selected.items():
        write_json(output / f"{name}.json", [completed[r["task_id"]]["trace"] for r in rows])
    write_json(
        output / "pilot.json",
        [completed[r["task_id"]]["trace"] for r in selected["development"][:20]],
    )
    write_json(output / "labels.json", [gold[tid] for tid in ids])
    write_json(output / "qa_outcomes.json", outcomes)
    for filename, field in (
        ("observations.jsonl", "observations"),
        ("inference.jsonl", "inference"),
    ):
        with (output / filename).open("w") as stream:
            for tid, result in completed.items():
                for row in result[field]:
                    stream.write(json.dumps({"task_id": tid, **row}) + "\n")
    shutil.copyfile(data / "corpus.json", output / "corpus.json")
    write_json(
        output / "manifest.json",
        {
            **source_manifest,
            "version": 2,
            "task_count": count,
            "agent": "mock-qa-v1 (synthetic)" if backend == "mock" else "http-qa-v1",
            "mock": backend == "mock",
            "candidate_generator": "observed-top-title-v1",
            "candidate_timing": "Measured after trajectory; exact matches share required timing",
            "split_method": "Preserved source development/evaluation assignments before collection",
            "development_ids": [r["task_id"] for r in selected["development"]],
            "evaluation_ids": [r["task_id"] for r in selected["evaluation"]],
            "source_manifest_sha256": sha256_json(source_manifest),
            "collection": config,
            "provenance": git_state(),
            "artifacts": {
                f"{name}.json": sha256_json(json.loads((output / f"{name}.json").read_text()))
                for name in ("development", "evaluation", "pilot")
            },
        },
    )
    return {
        "tasks": count,
        "mock": backend == "mock",
        "output": str(output),
        "exact_match": sum(r["exact_match"] for r in outcomes) / count
        if backend == "http"
        else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("results/qa-traces"))
    parser.add_argument("--backend", choices=("mock", "http"), default="mock")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--max-calls", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--timeout-s", type=float, default=30)
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    args = parser.parse_args()
    try:
        summary = asyncio.run(
            collect(
                args.data,
                args.output,
                backend=args.backend,
                count=args.count,
                max_calls=args.max_calls,
                resume=args.resume,
                model_options={
                    "timeout_s": args.timeout_s,
                    "input_price": args.input_usd_per_million,
                    "output_price": args.output_usd_per_million,
                },
            )
        )
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
