"""Paired development-only test: does the planner respond to quota context?"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from statistics import mean

import httpx

from quota_spec.artifacts import source_hashes, write_json
from quota_spec.capture import CaptureStore
from quota_spec.hotpot_runtime import Events
from quota_spec.quota_speculation import parse_queries, planner_prompt
from quota_spec.transport import LiveChat


async def probe(output, pilot_log=None):
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    source = Path("results/quota-win-2026-11-15-native-capture")
    store = CaptureStore(source / "capture")
    protocol = json.loads(
        Path("results/quota-win-2026-11-15-replication-protocol.json").read_text()
    )
    ids = set(map(str, protocol["development_indices"]))
    cases = {}
    for node in store.nodes:
        if node["kind"] == "generation" and node["branch"] == "speculative_actor":
            tid = node["episode"].split(":")[0]
            if tid in ids:
                cases.setdefault(tid, node)
    selected = sorted(cases.items())[:16]
    output.mkdir(parents=True)
    states = {
        "wide": {
            "capacity": 24,
            "remaining_calls": 24,
            "refill_period_s": 1,
            "seconds_to_refill": 0.5,
            "active_workers": 4,
            "other_active_workers": 3,
            "queued_required_calls": 0,
            "api": "Wikipedia Search",
        },
        "scarce": {
            "capacity": 8,
            "remaining_calls": 1,
            "refill_period_s": 5,
            "seconds_to_refill": 4.5,
            "active_workers": 4,
            "other_active_workers": 3,
            "queued_required_calls": 1,
            "api": "Wikipedia Search",
        },
    }
    write_json(
        output / "config.json",
        {
            "development_only": True,
            "states": states,
            "source_sha256": source_hashes(),
            "source": str(source),
            "pairs": [{"task_id": tid, "node": node["id"]} for tid, node in selected],
            "order": "Alternate wide/scarce order within each identical-prefix pair",
        },
    )
    prices = json.loads((source / "pricing.json").read_text())
    results = []
    async with httpx.AsyncClient(timeout=45) as client:
        chat = LiveChat(
            client,
            os.environ["OPENROUTER_API_KEY"],
            prices,
            output,
            Events(),
            0.1,
            40,
            "google/gemini-2.5-flash",
            "openai/gpt-4.1-nano",
            reserve_unknown_cost=True,
        )
        for i, (tid, node) in enumerate(selected):
            prefix = store.blob(node["input"])["prefix"]
            for name in ["wide", "scarce"] if i % 2 == 0 else ["scarce", "wide"]:
                if pilot_log:
                    while True:
                        lines = pilot_log.read_text().splitlines()
                        if (
                            lines
                            and lines[-1].startswith("COOLDOWN")
                            and time.time() - pilot_log.stat().st_mtime < 30
                        ):
                            break
                        await asyncio.sleep(1)
                content = await chat.call(
                    planner_prompt(prefix, node["step"], 3, states[name]),
                    "speculative_actor",
                    tid,
                    node["step"],
                )
                try:
                    actions = parse_queries(content, 3)
                    failure = None
                except ValueError as exc:
                    actions, failure = [], str(exc)
                results.append(
                    {"task_id": tid, "context": name, "actions": actions, "failure": failure}
                )
                write_json(output / "responses.json", results)
            print("PAIR", i + 1, tid, flush=True)
    write_json(
        output / "summary.json",
        {
            "pairs": len(selected),
            "requests": len(results),
            "invalid_outputs": sum(bool(r["failure"]) for r in results),
            "cost_usd": chat.spent,
            "mean_queries": {
                name: mean(len(r["actions"]) for r in results if r["context"] == name)
                for name in states
            },
            "skips": {
                name: sum(not r["actions"] for r in results if r["context"] == name)
                for name in states
            },
            "limitations": "Development sensitivity probe with artificial scheduler states; not an end-to-end speed comparison",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--pilot-log", type=Path)
    args = p.parse_args()
    asyncio.run(probe(args.output, args.pilot_log))
