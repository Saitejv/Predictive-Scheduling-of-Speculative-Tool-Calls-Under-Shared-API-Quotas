"""Single-agent HotpotQA agreement checks, separate from shared-quota studies.

Figure 4 reports per-question mean next-action agreement, not QA accuracy or
HotpotQA throughput. Its plotting code computes top-one and top-three from the
same candidate lists. Preserve the upstream any-match metric alongside a strict
prefix metric because upstream's k=3 scorer does not truncate over-width lists.
"""

import argparse
import json
import math
import statistics
from pathlib import Path

from .collect_qa import write_json
from .paper_collect import parse_paper_action
from .search import sha256_json
from .telemetry import summarize_inference

PAPER_URL = "https://arxiv.org/html/2510.04371v2#S3.F4"
FIGURE4 = {
    "openai/gpt-5-nano": {"top1": 0.1508, "top3": 0.3167},
    "openai/gpt-4.1-nano": {"top1": 0.1875, "top3": 0.4625},
    "google/gemini-2.5-flash": {"top1": 0.1958, "top3": 0.3833},
}


def candidates(value):
    # Older public top-one fixtures use a string, newer trajectories use lists.
    return [value] if isinstance(value, str) else list(value)


def action_scores(normal, simulated, k):
    if k not in (1, 3):
        raise ValueError("Use k=1 or k=3")
    if len(normal["actions"]) != len(simulated["actions"]):
        raise ValueError("Authoritative/hypothetical action counts differ")
    scored = list(zip(normal["actions"], simulated["actions"]))[1:]
    hits = sum(
        any(actual.lower() == guess.lower() for guess in candidates(predicted)[:k])
        for actual, predicted in scored
    )
    upstream_hits = sum(
        any(
            actual.lower() == guess.lower()
            for guess in (candidates(predicted)[:1] if k == 1 else candidates(predicted))
        )
        for actual, predicted in scored
    )
    return {
        "scored_actions": len(scored),
        "matches": hits,
        "accuracy": hits / len(scored) if scored else 0.0,
        "upstream_accuracy": upstream_hits / len(scored) if scored else 0.0,
        "over_width_scored_actions": sum(len(candidates(p)) > k for _, p in scored),
    }


def agreement_summary(rows):
    result = {}
    for k in (1, 3):
        scores = [action_scores(r["normal"], r["simulated"], k) for r in rows]
        values = [s["accuracy"] for s in scores]
        n = sum(s["scored_actions"] for s in scores)
        result[f"top{k}"] = {
            "tasks": len(rows),
            "macro_accuracy": statistics.mean(values) if values else None,
            "task_sem": statistics.stdev(values) / math.sqrt(len(values))
            if len(values) > 1
            else None,
            "micro_accuracy": sum(s["matches"] for s in scores) / n if n else None,
            "scored_actions": n,
            "matches": sum(s["matches"] for s in scores),
            "upstream_macro_accuracy": statistics.mean(s["upstream_accuracy"] for s in scores)
            if scores
            else None,
            "over_width_scored_actions": sum(s["over_width_scored_actions"] for s in scores),
        }
    return result


def single_agent_timing(row, k):
    """No-quota counterfactual, not a measured live execution or paper result.

    Only exact Search prefetch is modeled; stateful Lookup/Finish always execute
    authoritatively. Required actor inference always runs on the true response.
    As in Algorithm 1, a cache hit does not launch another speculative window.
    Wrong branches have no effect under the unlimited-resource assumption.
    """
    steps = row["trace"]["steps"]
    sequential = sum(s["think_s"] + s["duration_s"] for s in steps)
    terminal = row["trace"].get("final_think_s", 0)
    finished = 0.0
    previous_dispatch = None
    on_time = hits = proposed_searches = 0
    for i, step in enumerate(steps):
        ready = finished + step["think_s"]
        required = parse_paper_action(row["normal"]["actions"][i])
        matching = False
        proposal_ready = None
        if i and previous_dispatch is not None:
            guesses = [
                parse_paper_action(g) for g in candidates(row["simulated"]["actions"][i])[:k]
            ]
            proposal_ready = (
                previous_dispatch
                + row["simulated"]["time_taken"][i - 1]
                + row["timings"][i]["speculative_actor"]
            )
            if proposal_ready < ready:
                searches = {g for g in guesses if g.tool == "search"}
                proposed_searches += len(searches)
                on_time += bool(searches)
                matching = required.tool == "search" and required in searches
        if matching:
            hits += 1
            finished = max(ready, proposal_ready + step["duration_s"])
            previous_dispatch = None
        else:
            previous_dispatch = ready
            finished = ready + step["duration_s"]
    return {
        "sequential_s": sequential + terminal,
        "speculative_s": finished + terminal,
        "on_time_proposal_steps": on_time,
        "prefetched_searches": proposed_searches,
        "exact_prefetch_hits": hits,
        "kind": "no-quota Search-only counterfactual; not live throughput",
    }


def report_collection(collection, output):
    config = json.loads((collection / "collection_config.json").read_text())
    rows = [json.loads(p.read_text()) for p in (collection / "tasks").glob("*.json")]
    failed = [r["task_id"] for r in rows if r.get("failure")]
    rows = [r for r in rows if not r.get("failure")]
    for row in rows:
        if row.get("sha256") != sha256_json({k: v for k, v in row.items() if k != "sha256"}):
            raise ValueError("Saved paper task checksum mismatch")
    expected = {str(i) for i in config["indices"]}
    actual = {r["task_id"] for r in rows}
    complete = expected == actual and not failed
    index_ok = all(r.get("question_index") == int(r["task_id"]) for r in rows)
    scores = agreement_summary(rows)
    widths = [len(candidates(p)) for r in rows for p in r["simulated"]["actions"][1:]]
    published = FIGURE4.get(config["speculator"])
    records = [json.loads(s) for s in (collection / "inference.jsonl").read_text().splitlines()]
    timing = {}
    for k in (1, 3):
        measured = [single_agent_timing(r, k) for r in rows]
        normal = sum(r["sequential_s"] for r in measured)
        speculative = sum(r["speculative_s"] for r in measured)
        timing[f"top{k}"] = {
            "sequential_total_s": normal,
            "speculative_total_s": speculative,
            "relative_time_saved": (normal - speculative) / normal if normal else None,
            "exact_prefetch_hits": sum(r["exact_prefetch_hits"] for r in measured),
            "on_time_proposal_steps": sum(r["on_time_proposal_steps"] for r in measured),
            "per_task": [{"task_id": r["task_id"], **t} for r, t in zip(rows, measured)],
            "kind": "no-quota Search-only counterfactual; not live throughput",
        }
    summary = {
        "collection_source_sha256": config["source_sha256"],
        "actor": config["actor"],
        "speculator": config["speculator"],
        "requested_width": config["width"],
        "tasks": len(rows),
        "complete": complete,
        "actual_reset_indices_match": index_ok,
        "failed_tasks": failed,
        "agreement": scores,
        "candidate_count_audit": {
            "requested": config["width"],
            "scored_lists": len(widths),
            "under_width": sum(n < config["width"] for n in widths),
            "over_width": sum(n > config["width"] for n in widths),
            "maximum": max(widths, default=0),
        },
        "published_figure4": published,
        "figure4_url": PAPER_URL,
        "figure4_protocol": "Macro per-question agreement; top1/top3 from the same top3 lists",
        "comparable_to_figure4": complete
        and index_ok
        and config["width"] == 3
        and len(rows) == 20
        and config["backend"] == "http"
        and config["actor"] == "google/gemini-2.5-flash"
        and published is not None,
        "paper_hotpotqa_latency_target": None,
        "latency_target_reason": "Paper reports HotpotQA agreement, not throughput or latency gain",
        "qa": {
            name: statistics.mean(r[name] for r in rows)
            if rows and all(r.get(name) is not None for r in rows)
            else None
            for name in ("em", "f1")
        },
        "usage": summarize_inference(records),
        "finish_reasons": {
            role: {
                reason: sum(
                    r.get("finish_reason") == reason and r.get("role") == role for r in records
                )
                for reason in ("stop", "length", None)
            }
            for role in ("actor", "speculative_actor", "observation_speculator")
        },
        "timing_diagnostic": timing,
        "reproduction_established": False,
        "limitations": [
            "One model cell does not reproduce all three Figure 4 model pairings",
            "Historical model routes and live Wikipedia responses cannot be frozen retroactively",
            "Published sample identities cannot be inferred from buggy upstream folder names",
            "Comparable configuration is not a claim of numerical equivalence",
            "Timing diagnostic omits model/tool contention and does not measure live speedup",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", summary)
    write_json(
        output / "outcomes.json",
        [
            {
                "task_id": r["task_id"],
                "em": r["em"],
                "f1": r["f1"],
                "agreement": {
                    f"top{k}": action_scores(r["normal"], r["simulated"], k) for k in (1, 3)
                },
            }
            for r in rows
        ],
    )
    lines = [
        "Single-agent HotpotQA reproduction check. No Jev, shared quotas or admission policies.",
        "",
        f"Actor `{config['actor']}`; observation model `{config['speculator']}`; "
        f"requested width {config['width']}; {len(rows)} tasks. Complete: {complete}.",
        "",
        "| Metric | Current macro agreement | Paper Figure 4 | Current task SEM |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, score in scores.items():
        target = f"{published[name]:.2%}" if published else "not available"
        value = f"{score['macro_accuracy']:.2%}" if rows else "not available"
        sem = f"{score['task_sem']:.2%}" if score["task_sem"] is not None else "not available"
        lines.append(f"| {name} | {value} | {target} | {sem} |")
    lines += [
        "",
        "Figure 4 compares top-one/top-three prefixes from the same candidate lists. "
        "Top-three from a width-one run cannot reproduce its top-three result. Scores exclude "
        "the first action and use upstream case folding. `summary.json` also records the "
        "unbounded upstream any-match metric and candidate-count violations.",
        "",
        "QA EM/F1, next-action agreement and timing are separate. The paper gives no "
        "HotpotQA throughput target. Any timing values here are explicitly Search-only "
        "no-quota counterfactuals, not live speedups or a reproduced paper measurement.",
        "",
        "Numerical reproduction is not established by this run alone. Current and historical "
        "model outputs/Wikipedia pages can differ. Do not proceed to Jev/shared-quota claims "
        "on the assumption that the published baseline has already been reproduced.",
        "",
        f"Reference: [paper Figure 4]({PAPER_URL}). Raw measurements are in `traces/`.",
    ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return summary


def audit_reference(reference, source, output):
    """Recompute public saved outputs without API inference or trusting folder IDs."""
    import hashlib

    from .paper import REVISION

    manifest = json.loads((reference.parent / "upstream-artifact-manifest.json").read_text())
    if manifest["revision"] != REVISION:
        raise ValueError("Unexpected reference revision")
    for identity in manifest["files"]:
        data = (reference / identity["path"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != identity["git_blob"] or hashlib.sha256(data).hexdigest() != identity["sha256"]:
            raise ValueError("Reference artifact checksum mismatch")
    dataset = json.loads((source / "hotpotqa/data/hotpot_dev_v1_simplified.json").read_text())
    question_indices = {row["question"]: i for i, row in enumerate(dataset)}
    cells = []
    for folder in sorted((reference / "hotpotqa/run_metrics").glob("agent_*/trajs_*")):
        actor_width = folder.parent.name.removeprefix("agent_")
        actor, width = actor_width.rsplit("_top", 1)
        width = int(width)
        speculator = folder.name.removeprefix("trajs_")
        rows = []
        identities = []
        incomplete = []
        for task in sorted(folder.iterdir()):
            if not all((task / name).exists() for name in ("normalobs.json", "simobs.json")):
                incomplete.append(task.name)
                continue
            normal = json.loads((task / "normalobs.json").read_text())
            simulated = json.loads((task / "simobs.json").read_text())
            rows.append({"normal": normal, "simulated": simulated})
            question = normal["prompt"].rsplit("Question: ", 1)[-1].strip()
            actual_index = question_indices.get(question)
            saved_score = None
            if (task / "metrics.json").exists():
                saved_score = json.loads((task / "metrics.json").read_text())["general"]
            recomputed = action_scores(normal, simulated, width)["upstream_accuracy"]
            identities.append(
                {
                    "folder_index": int(task.name),
                    "actual_question_index": actual_index,
                    "folder_matches_question": actual_index == int(task.name),
                    "stored_agreement": saved_score,
                    "recomputed_agreement": recomputed,
                    "stored_score_reproduced": saved_score is None
                    or abs(saved_score - recomputed) < 1e-12,
                }
            )
        cells.append(
            {
                "actor": actor,
                "speculator": speculator,
                "requested_width": width,
                "available_tasks": len(rows),
                "incomplete_folders": incomplete,
                "agreement": agreement_summary(rows),
                "task_identity_audit": identities,
            }
        )
    result = {
        "revision": REVISION,
        "verified_files": len(manifest["files"]),
        "cells": cells,
        "figure4": FIGURE4,
        "source": PAPER_URL,
        "model_requests": 0,
        "cost_usd": 0,
        "paper_reproduction_established": False,
        "reason": "Public artifacts are small subsets with mismatched question IDs; not the complete Figure 4 experiment",
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "reference-audit.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collection", type=Path)
    mode.add_argument("--reference-root", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh report directory")
    if args.reference_root:
        if args.source is None:
            parser.error("Reference audit requires --source")
        summary = audit_reference(args.reference_root, args.source, args.output)
    else:
        summary = report_collection(args.collection, args.output)
    print(json.dumps({k: v for k, v in summary.items() if k != "timing_diagnostic"}, indent=2))


if __name__ == "__main__":
    main()
