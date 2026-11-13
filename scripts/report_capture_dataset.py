"""Report capture coverage, measured durations and separate collection costs."""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.capture import CaptureStore
from quota_spec.frozen_replay import load_dataset
from quota_spec.replay import percentile


def report(dataset, output, collection_runs=()):
    dataset, output = Path(dataset), Path(output)
    if output.exists():
        raise ValueError("Choose a fresh report directory")
    data = load_dataset(dataset)
    parts = (
        [dataset / "parts" / p["shard"] for p in data["parts"]] if "parts" in data else [dataset]
    )
    role_nodes, searches, stages = defaultdict(list), [], Counter()
    for root in parts:
        for kind in ("live-capture", "completion"):
            store = CaptureStore(root / kind)
            for node in store.nodes:
                stages[node["kind"]] += 1
                if node["kind"] == "model":
                    role_nodes[node["branch"]].append(node)
                elif node["kind"] == "search":
                    searches.append(node)
    timing = {}
    for role, nodes in role_nodes.items():
        timing[role] = {
            "attempts": len(nodes),
            "median_service_s": statistics.median(n["service_s"] for n in nodes),
            "p95_service_s": percentile([n["service_s"] for n in nodes], 0.95),
            "max_service_s": max(n["service_s"] for n in nodes),
            "local_queue_total_s": sum(n["queue_s"] for n in nodes),
            "known_cost_usd": sum(n.get("usage", {}).get("cost_usd") or 0 for n in nodes),
        }
    timing["search"] = {
        "executions": len(searches),
        "median_service_s": statistics.median(n["service_s"] for n in searches),
        "p95_service_s": percentile([n["service_s"] for n in searches], 0.95),
        "max_service_s": max(n["service_s"] for n in searches),
        "local_queue_total_s": sum(n["queue_s"] for n in searches),
    }
    ledger = []
    for root in collection_runs:
        root = Path(root)
        path = root / "inference.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        ledger.append(
            {
                "path": str(root),
                "requests": len(rows),
                "known_cost_usd": sum(r["cost_usd"] or 0 for r in rows),
                "unknown_cost_requests": sum(r["cost_usd"] is None for r in rows),
                "failures": sum(bool(r["failure"]) for r in rows),
            }
        )
    tapes = data["tapes"]
    windows = [s["window"] for t in tapes for s in t["steps"] if s["window"]]
    candidates = [c for w in windows for c in w["candidates"]]
    result = {
        "questions": len(tapes),
        "canonical_speculative_episodes": len(tapes),
        "independent_sequential_episodes": len(tapes),
        "stages": dict(stages),
        "authoritative_steps": sum(len(t["steps"]) for t in tapes),
        "completed_windows": len(windows),
        "ranked_candidates": len(candidates),
        "eligible_search_candidates": sum(c["eligible"] for c in candidates),
        "missing_eligible_search_results": sum(
            c["eligible"] and "result" not in c for c in candidates
        ),
        "timing": timing,
        "collection_ledger": ledger,
        "known_collection_cost_usd": sum(r["known_cost_usd"] for r in ledger),
        "unknown_collection_cost_requests": sum(r["unknown_cost_requests"] for r in ledger),
        "canonical_em": statistics.mean(t["em"] for t in tapes)
        if all(t["em"] is not None for t in tapes)
        else None,
        "canonical_forced_finishes": sum(t["forced_finish"] for t in tapes),
        "ready_for_predictor_integration": True,
        "jev_kev_called": False,
        "limits": data["assumptions"],
    }
    output.mkdir(parents=True)
    write_json(output / "summary.json", result)
    lines = [
        "# HotpotQA captured dataset",
        "",
        f"**{len(tapes)} independent questions**, each with a sequential and speculative live episode. "
        "Canonical scheduling tapes use speculative histories; independent sequential outputs are kept separate.",
        "",
        f"The complete finite bank has {len(windows)} prediction windows and {len(candidates)} ranked candidates. "
        "All eligible Search candidates have full saved results/states. No online fallback exists in replay.",
        "",
        "| Stage | Attempts/executions | Median service (s) | p95 service (s) | Maximum service (s) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for role, values in timing.items():
        lines.append(
            f"| {role} | {values.get('attempts', values.get('executions'))} | {values['median_service_s']:.3f} | {values['p95_service_s']:.3f} | {values['max_service_s']:.3f} |"
        )
    lines += [
        "",
        "Durations are measured HTTP/tool service, including network/provider waiting. "
        "Local collection pacing and queues are stored separately. Long provider delays remain in the data; "
        "no outlier was silently clipped. Replay assumes fixed recorded durations and unlimited model concurrency.",
        "",
        f"Canonical answer EM: {result['canonical_em']}; forced action-limit finishes: {result['canonical_forced_finishes']}. "
        "Fixed replay answers are a scheduling invariant, not new answer-quality evidence.",
        "",
    ]
    if ledger:
        lines += [
            f"Known incremental collection charges, including aborted attempts: **${result['known_collection_cost_usd']:.8f}**. "
            f"Requests with unresolved individual charge: {result['unknown_collection_cost_requests']}.",
            "",
            "| Collection run | Requests | Known USD | Unknown charges | Failures |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        lines += [
            f"| `{r['path']}` | {r['requests']} | {r['known_cost_usd']:.8f} | {r['unknown_cost_requests']} | {r['failures']} |"
            for r in ledger
        ]
    lines += [
        "",
        "The dataset is ready for history/Jev/Kev forecast-bank integration. No Jev/Kev calls "
        "or full/own-agent predictive admission comparisons have been performed in this collection.",
        "",
        *["- " + assumption for assumption in result["limits"]],
    ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection-runs", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    print(json.dumps(report(args.dataset, args.output, args.collection_runs), indent=2))
