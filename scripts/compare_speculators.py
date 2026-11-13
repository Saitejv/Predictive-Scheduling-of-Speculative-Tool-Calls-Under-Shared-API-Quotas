"""Legacy local-BM25 diagnostic; not a reproduction of the upstream paper.

Compare proposers on identical saved observed states, without recollecting QA.

All proposals are allowed to finish to separate agreement from latency. On-time
counts compare against frozen main-model timings, not a new simultaneous race.
"""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from quota_spec.collect_qa import write_json
from quota_spec.experiments import source_hashes
from quota_spec.search import sha256_json
from quota_spec.speculation import HTTPSpeculator, model_identity, propose
from quota_spec.telemetry import summarize_inference


def observed_cases(source):
    splits = {
        row["task_id"]: split
        for split in ("development", "evaluation")
        for row in json.loads((source / f"{split}.json").read_text())
    }
    cases = []
    for path in sorted((source / "tasks").glob("*.json")):
        row = json.loads(path.read_text())
        if row.get("failure"):
            raise ValueError("Comparison requires successful saved tasks")
        trace = row["trace"]
        for index, observation in enumerate(row["observations"]):
            if index >= len(row["speculator_inference"]):
                continue  # No proposal at the known search-budget limit.
            cases.append(
                {
                    "task_id": trace["task_id"],
                    "split": splits[trace["task_id"]],
                    "step": index,
                    "question": trace["task_context"],
                    "history": row["history"][:index],
                    "main_latency_s": row["inference"][index]["latency_s"],
                    "required_query": trace["steps"][index]["query"]
                    if index < len(trace["steps"])
                    else None,
                    "original_candidate": observation["candidate_query"],
                    "original_inference": row["speculator_inference"][index],
                }
            )
    return cases


def summarize(rows):
    summaries = {}
    for name in dict.fromkeys(row["model"] for row in rows):
        selected = [r for r in rows if r["model"] == name]
        by_split = {}
        for split in ("development", "evaluation", "all"):
            values = [r for r in selected if split == "all" or r["split"] == split]
            searches = [r for r in values if r["required_query"] is not None]
            by_split[split] = {
                "phases": len(values),
                "required_searches": len(searches),
                "exact_matches": sum(r["exact_match"] for r in searches),
                "on_time_exact_matches": sum(r["exact_match"] and r["on_time"] for r in searches),
                "on_time_proposals": sum(
                    r["candidate"] is not None and r["on_time"] for r in values
                ),
                "median_latency_s": statistics.median(r["inference"]["latency_s"] for r in values),
                "usage": summarize_inference(r["inference"] for r in values),
            }
        summaries[name] = by_split
    return summaries


async def run(args):
    cases = observed_cases(args.source)
    if not cases:
        raise ValueError("No saved observed states")
    if args.output.exists():
        raise ValueError("Choose a fresh output directory")
    probes = [HTTPSpeculator(model=name, timeout_s=args.timeout_s) for name in args.models]
    for model in probes:
        model.max_tokens = 2048
        model.reasoning_effort = "low" if model.model.startswith("openai/gpt-5") else "none"
        if model.model.endswith("gpt-4.1-nano"):
            model.reasoning_effort = None
    args.output.mkdir(parents=True)
    write_json(
        args.output / "config.json",
        {
            "source": str(args.source.resolve()),
            "cases_sha256": sha256_json(cases),
            "source_sha256": source_hashes(),
            "models": [model_identity(m) for m in probes],
            "protocol": "Frozen observed states; direct next-query proposal; late results retained only for diagnostic scoring",
        },
    )
    results = []

    def save(case, name, candidate, inference):
        results.append(
            {
                "task_id": case["task_id"],
                "split": case["split"],
                "step": case["step"],
                "model": name,
                "candidate": candidate,
                "required_query": case["required_query"],
                "exact_match": candidate is not None and candidate == case["required_query"],
                "on_time": inference["latency_s"] < case["main_latency_s"],
                "main_latency_s": case["main_latency_s"],
                "inference": inference,
            }
        )
        write_json(args.output / "responses.json", results)

    for case in cases:
        save(case, "original-gpt-oss-120b", case["original_candidate"], case["original_inference"])
        # Sequential models avoid competing for routing capacity in the latency comparison.
        for model in probes:
            candidate = await propose(model, case["question"], case["history"])
            save(case, model.model, candidate, model.records[-1])
        print(f"Compared {case['task_id']} phase {case['step']}", flush=True)
    result = summarize(results)
    write_json(args.output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--models",
        nargs="+",
        default=[
            "google/gemini-2.5-flash",
            "openai/gpt-5-mini",
            "openai/gpt-5-nano",
            "openai/gpt-4.1-nano",
        ],
    )
    parser.add_argument("--timeout-s", type=float, default=30)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
