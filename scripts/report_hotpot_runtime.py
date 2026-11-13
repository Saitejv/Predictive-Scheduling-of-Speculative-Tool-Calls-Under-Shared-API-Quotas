"""Offline audit and report for the live paired HotpotQA experiment."""

import argparse
import hashlib
import importlib.util
import json
import statistics
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.hotpot_runtime import measurement_protocol, paired_summary, split_action
from quota_spec.upstream import REVISION


def report(root, upstream, output, source_snapshot=None):
    """Read frozen inputs and write derived reports to a fresh, separate directory."""
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Reports must be outside the frozen evidence directory")
    if output.exists():
        raise ValueError("Choose a fresh report output directory")
    config = json.loads((root / "config.json").read_text())
    prompts_file = upstream / "hotpotqa/src/prompts.py"
    expected = config["upstream"]["files"]["hotpotqa/src/prompts.py"]["sha256"]
    assert hashlib.sha256(prompts_file.read_bytes()).hexdigest() == expected
    module_spec = importlib.util.spec_from_file_location("audited_prompts", prompts_file)
    prompts = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(prompts)
    rows = []
    for position, index in enumerate(config["indices"]):
        modes = (
            ("sequential", "speculative") if position % 2 == 0 else ("speculative", "sequential")
        )
        for mode in modes:
            rows.append(json.loads((root / "tasks" / f"{index}-{mode}.json").read_text()))
    records = [json.loads(line) for line in (root / "inference.jsonl").read_text().splitlines()]
    raw = {
        r["request_id"]: r
        for r in map(json.loads, (root / "requests.jsonl").read_text().splitlines())
    }
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    summary = paired_summary(rows, records, protocol=config.get("measurement_protocol"))
    if summary != json.loads((root / "summary.json").read_text()):
        raise ValueError("Frozen evidence does not reproduce the runtime summary")
    assert len(raw) == len(records)
    assert len(rows) == 2 * len(config["indices"])
    assert all(r["cost_usd"] is not None for r in records)
    active = peak = 0
    for event in events:
        if event["event"] == "inference_started":
            active += 1
            peak = max(peak, active)
        elif event["event"] == "inference_finished":
            active -= 1
    assert active == 0
    overlap = []
    for row in rows:
        for step in row["trajectory"]:
            if not step["prefetch_hit"]:
                continue
            query = split_action(step["action"])[1]
            started = next(
                e
                for e in events
                if e["episode"] == row["episode"]
                and e["event"] == "search_started"
                and e.get("speculative")
                and e["query"] == query
            )
            finished = next(
                e
                for e in events
                if e["episode"] == row["episode"]
                and e["event"] == "search_finished"
                and e.get("speculative")
                and e["query"] == query
            )
            required = next(
                e
                for e in events
                if e["episode"] == row["episode"]
                and e["event"] == "required_action"
                and e["step"] == step["step"]
            )
            overlap.append(
                {
                    "episode": row["episode"],
                    "step": step["step"],
                    "query": query,
                    "prefetch_lead_s": required["time_s"] - started["time_s"],
                    "search_duration_s": finished["time_s"] - started["time_s"],
                    "already_finished_at_request": finished["time_s"] <= required["time_s"],
                    "actual_tool_wait_s": step["tool_wait_s"],
                }
            )
    # Verify actual authoritative prompts contain the exact observed trajectory
    # prefix, including after cache reuse; no provisional page enters the actor.
    checked_prompts = 0
    for row in rows:
        actor = [r for r in records if r["episode"] == row["episode"] and r["role"] == "actor"]
        first_prompt = raw[actor[0]["request_id"]]["request"]["messages"][-1]["content"]
        prefix = first_prompt[
            : first_prompt.rindex("Reason very very succinctly about the 1th action")
        ]
        for step in row["trajectory"]:
            for record in actor:
                if record["step"] == step["step"]:
                    actual = raw[record["request_id"]]["request"]["messages"][-1]["content"]
                    assert actual.startswith(prefix)
                    checked_prompts += 1
            prefix += prompts.PromptTemplates.NEXT_STEP_PROMPT.format(
                i=step["step"],
                thought=step["thought"],
                action=step["action"],
                obs=step["observation"],
            )
    source_root = Path(__file__).resolve().parents[1] / "src/quota_spec"

    def source_matches(directory):
        return all(
            (directory / p).is_file()
            and hashlib.sha256((directory / p).read_bytes()).hexdigest() == digest
            for p, digest in config["source_sha256"].items()
        )

    source_ok = source_matches(source_root)
    snapshot_ok = source_matches(source_snapshot) if source_snapshot is not None else None
    if source_snapshot is not None and not snapshot_ok:
        raise ValueError("Paid source snapshot does not match the recorded configuration")
    audit = {
        "measurement_protocol": config.get("measurement_protocol")
        or measurement_protocol(config["backend"], config.get("min_request_interval_s", 0.0)),
        "summary_reproduced": True,
        "source_hashes_still_match": source_ok,
        "paid_source_snapshot_matches": snapshot_ok,
        "peak_paid_request_concurrency": peak,
        "all_started_inference_drained": active == 0,
        "authoritative_prompt_prefixes_checked": checked_prompts,
        "prefetch_hits": overlap,
        "prefetch_overlap_s": sum(
            min(r["prefetch_lead_s"], r["search_duration_s"]) for r in overlap
        ),
        "overlap_interpretation": "Measured execution completed before its result was required; not a separate causal end-to-end speedup estimate",
        "by_mode": {},
    }
    for mode in ("sequential", "speculative"):
        selected = [r for r in rows if r["mode"] == mode]
        calls = [r for r in records if r["episode"].endswith(":" + mode)]
        durations = [
            e["duration_s"]
            for e in events
            if e["event"] == "search_finished"
            and e["episode"].endswith(":" + mode)
            and not e["speculative"]
        ]
        audit["by_mode"][mode] = {
            "forced_finishes": sum(r["forced_finish"] for r in selected),
            "actor_median_s": statistics.median(
                r["latency_s"] for r in calls if r["role"] == "actor"
            ),
            "required_search_median_s": statistics.median(durations) if durations else None,
            "roles": {
                role: {
                    "requests": sum(r["role"] == role for r in calls),
                    "cost_usd": sum(r["cost_usd"] for r in calls if r["role"] == role),
                }
                for role in ("actor", "observation_speculator", "speculative_actor")
            },
        }
    output.mkdir(parents=True)
    write_json(output / "audit.json", audit)
    write_json(output / "summary.json", summary)
    seq, spec = summary["by_mode"]["sequential"], summary["by_mode"]["speculative"]
    pair = summary["paired"]
    interval = pair["bootstrap_95_mean_saving_s"]
    lines = [
        "# Live end-to-end HotpotQA comparison",
        "",
        f"{pair['questions']} paired questions; {len(rows)} real-model episodes; original Gemini prompts and settings; no Jev, shared quotas or artificial tool delays.",
        "",
        "| Metric | Sequential | Speculative |",
        "| --- | ---: | ---: |",
        *[
            f"| {label} | {seq[key]:.{precision}f} | {spec[key]:.{precision}f} |"
            for label, key, precision in [
                ("Mean answer latency (s)", "mean_s", 3),
                ("Median answer latency (s)", "median_s", 3),
                ("p95 answer latency (s)", "p95_s", 3),
                ("Total answer time (s)", "answer_time_total_s", 3),
                ("Total resource time incl. drain (s)", "resource_time_total_s", 3),
                ("Mean actions", "mean_actions", 2),
                ("Answer EM", "em", 3),
                ("Answer F1", "f1", 3),
            ]
        ],
        f"| Inference requests | {seq['usage']['requests']} | {spec['usage']['requests']} |",
        f"| Billed USD | {seq['usage']['cost_usd']:.8f} | {spec['usage']['cost_usd']:.8f} |",
        f"| Forced finishes at seven-action cap | {audit['by_mode']['sequential']['forced_finishes']} | {audit['by_mode']['speculative']['forced_finishes']} |",
        "",
        f"Observed answer-time saving: **{100 * pair['relative_total_time_saved']:.2f}%**. Mean paired saving: {pair['mean_saving_s']:.3f} s; paired bootstrap 95% interval **[{interval[0]:.3f}, {interval[1]:.3f}] s**. Positive saving favors speculation.",
        "",
        f"Resource-inclusive throughput ratio: {seq['resource_time_total_s'] / spec['resource_time_total_s']:.3f}x speculative/sequential (one agent with each episode fully drained). This is not multi-agent saturation throughput.",
        "",
        f"Speculation launched {spec['prefetches']} searches, obtained {spec['cache_hits']} exact hits ({spec['inflight_hits']} still in flight at request), and left {spec['unused_prefetches']} unused. {spec['late_windows']} prediction windows arrived too late; {spec['optional_failures']} optional operations failed.",
        "",
        f"Successful prefetches overlapped {audit['prefetch_overlap_s']:.3f} s of measured Search execution before their results were needed. This is a local overlap diagnostic, not an independent estimate of campaign speedup.",
        "",
        f"The two modes produced identical action lists on {pair['identical_action_pairs']}/{pair['questions']} questions. They are paired by question, with independent stochastic actor outputs. Different trajectories, answer outcomes and provider timings confound attributing the aggregate runtime difference solely to speculation.",
        "",
        "The confidence interval includes zero; this run does not establish a reliable end-to-end latency benefit."
        if interval[0] <= 0 <= interval[1]
        else "The interval excludes zero for this question-paired sample; trajectory differences and the single-run design still limit causal attribution.",
        "",
        f"Total billed cost: **${summary['usage']['cost_usd']:.8f}**. Inference failures: {summary['usage']['failures']}; unknown billed costs: {summary['usage']['unknown_cost_usd_requests']}. Peak paid-request concurrency: {peak}. All started inference drained before the next episode.",
        "",
        f"Offline audit regenerated the summary exactly, checked {checked_prompts} authoritative prompt prefixes, active source hashes match: {source_ok}; supplied paid source snapshot matches: {snapshot_ok}.",
        "",
        "Artifacts: `config.json`, `summary.json`, `audit.json`, `tasks/`, `events.jsonl`, `requests.jsonl`, `inference.jsonl`.",
    ]
    protocol = audit["measurement_protocol"]
    if protocol["actor_and_optional_requests_share_pacing"]:
        lines[4:4] = [
            f"**Paced model submissions: {protocol['shared_model_submission_interval_s']:.3f} seconds between requests.** "
            "Authoritative and optional requests share this gate. Wall times include its contention "
            "and are not directly comparable with the unpaced live benchmark.",
            "",
        ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return summary, audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--upstream", type=Path, default=Path("data/raw/speculative-action") / REVISION
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path)
    args = parser.parse_args()
    summary, audit = report(args.source, args.upstream, args.output, args.source_snapshot)
    print(
        json.dumps(
            {
                "paired": {k: v for k, v in summary["paired"].items() if k != "pairs"},
                "audit": audit,
            },
            indent=2,
        )
    )
