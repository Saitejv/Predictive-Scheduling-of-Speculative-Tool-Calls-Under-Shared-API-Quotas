"""Freeze HotpotQA data and collect actual local scripted retrieval trajectories.

The agent sees questions and search outputs; gold answers/support facts remain
in a separate evaluation file. This is a retrieval harness, not an LLM agent.
"""

import argparse
import json
import time
import urllib.request
from dataclasses import replace
from pathlib import Path

from .models import Call, Step, Task, nonnegative, positive_int
from .search import SearchCorpus, candidate_query, required_query, sha256_json
from .workload import dump_tasks

SOURCE = "https://datasets-server.huggingface.co/rows?dataset=hotpotqa%2Fhotpot_qa&config=distractor&split=validation&offset={offset}&length=100"


def prepare(output=Path("data"), count=200, think_s=0.015, service_s=0.01):
    positive_int(count, "count")
    nonnegative(think_s, "think_s")
    nonnegative(service_s, "service_s")
    if not 20 <= count <= 200:
        raise ValueError("Use 20..200 tasks and nonnegative delays")
    if (output / "manifest.json").exists():
        raise ValueError("Collection output already contains a dataset; choose a new directory")
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    rows = []
    sources = []
    for offset in range(0, count, 100):
        path = raw / f"hotpot-page-{offset}.json"
        url = SOURCE.format(offset=offset)
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                path.write_bytes(response.read())
        page = json.loads(path.read_text())
        rows.extend(x["row"] for x in page["rows"])
        sources.append({"url": url, "sha256": sha256_json(page)})
    rows = rows[:count]
    if len(rows) != count or len({r["id"] for r in rows}) != count:
        raise ValueError("Dataset source returned too few rows or duplicate task IDs")
    documents = {}
    for row in rows:
        for title, sentences in zip(row["context"]["title"], row["context"]["sentences"]):
            # Keep the first paragraph for duplicate titles, in source order.
            documents.setdefault(title, {"title": title, "text": "".join(sentences)})
    corpus = SearchCorpus(list(documents.values()))
    corpus.save(output / "corpus.json")
    tasks, observations, labels = [], [], []
    for row in rows:
        question = row["question"]
        previous, results, steps = [], [], []
        started = time.perf_counter()
        seen_titles = set()
        for step in range(3):
            candidate_started = time.perf_counter()
            candidate = candidate_query(question, results, step)
            candidate_wall = time.perf_counter() - candidate_started
            before = time.perf_counter()
            query = required_query(question, results, previous, step)
            time.sleep(think_s)
            think = time.perf_counter() - before
            observed_at = time.perf_counter() - started
            observations.append(
                {
                    "task_id": row["id"],
                    "step": step,
                    "observed_at_s": observed_at,
                    "question": question,
                    "previous_queries": list(previous),
                    "result_excerpt": json.dumps(results)[:1024],
                    "candidate_query": candidate,
                    "candidate_generation_wall_s": candidate_wall,
                }
            )
            before = time.perf_counter()
            time.sleep(service_s)
            results = corpus.search(query)
            duration = time.perf_counter() - before
            previous.append(query)
            seen_titles.update(r["title"] for r in results)
            steps.append(
                Step(
                    think + candidate_wall,
                    Call.search(query),
                    duration,
                    Call.search(candidate) if candidate else None,
                    duration,
                    json.dumps(results, ensure_ascii=False)[:1024],
                    candidate_delay_s=candidate_wall,
                )
            )
        # Measure incorrect candidates separately after the observed trajectory,
        # so neither their results nor their benchmark latency enter agent state.
        for index, recorded in enumerate(steps):
            if recorded.candidate is not None and recorded.candidate != recorded.required:
                before = time.perf_counter()
                time.sleep(service_s)
                corpus.search(json.loads(recorded.candidate.arguments_json)["query"])
                steps[index] = replace(recorded, candidate_duration_s=time.perf_counter() - before)
        tasks.append(Task(row["id"], 0, tuple(steps), task_context=question))
        labels.append(
            {
                "task_id": row["id"],
                "answer": row["answer"],
                "supporting_titles": sorted(set(row["supporting_facts"]["title"])),
                "retrieved_support_count": len(seen_titles & set(row["supporting_facts"]["title"])),
            }
        )
    # Stable hash split, disjoint by original dataset ID, before fitting/tuning.
    ordered = sorted(tasks, key=lambda t: sha256_json(t.task_id))
    split = len(ordered) // 2
    for name, group in (
        ("development", ordered[:split]),
        ("evaluation", ordered[split:]),
        ("pilot", ordered[: min(20, split)]),
    ):
        (output / f"{name}.json").write_text(json.dumps(dump_tasks(tuple(group)), indent=2) + "\n")
    (output / "observations.jsonl").write_text("".join(json.dumps(x) + "\n" for x in observations))
    (output / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    manifest = {
        "version": 1,
        "dataset": "hotpotqa/hotpot_qa",
        "config": "distractor",
        "source_split": "validation",
        "sources": sources,
        "task_count": count,
        "corpus_sha256": corpus.digest,
        "documents": len(corpus.documents),
        "license": "CC BY-SA 4.0",
        "attribution": "Yang et al., EMNLP 2018, https://hotpotqa.github.io/",
        "agent": "scripted-retrieval-v2; no LLM; three searches per question",
        "candidate_timing": "Incorrect candidates benchmarked separately after each trajectory",
        "candidate_generator": "observed-top-title-v1",
        "think_delay_s": think_s,
        "service_delay_s": service_s,
        "split_method": "sha256(original task ID), equal halves",
        "development_ids": [t.task_id for t in ordered[:split]],
        "evaluation_ids": [t.task_id for t in ordered[split:]],
        "artifacts": {
            p.name: sha256_json(json.loads(p.read_text()))
            for p in (
                output / "development.json",
                output / "evaluation.json",
                output / "pilot.json",
            )
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Recorded {count} scripted tasks; {len(corpus.documents)} documents; corpus {corpus.digest}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()
    prepare(args.output, args.count)


if __name__ == "__main__":
    main()
