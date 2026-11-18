"""Frozen-policy live comparison of agent counts with common actor seeds."""

import argparse
import asyncio
import hashlib
import random
import shutil
from pathlib import Path

from quota_spec.artifacts import source_hashes, write_json
from quota_spec.live_context_audit import audit
from quota_spec.multi_agent import parser, run


async def experiment(
    output, max_usd, *, seed=5851516, cooldown_s=60, settings=None, per_run_max_usd=0.2
):
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    rng = random.Random(seed)
    settings = list(settings or [(a, c, w) for a in [2, 4, 8] for c, w in [(12, 3), (8, 5)]])
    rng.shuffle(settings)
    cases = []
    for agents, capacity, window in settings:
        policies = ["no_speculation", "allow_all", "jev", "quota"]
        rng.shuffle(policies)
        cases += [
            {"agents": agents, "capacity": capacity, "window_s": window, "policy": p}
            for p in policies
        ]
    output.mkdir(parents=True)
    write_json(
        output / "protocol.json",
        {
            "purpose": "Multi-agent comparison: Jev vs direct quota context and both baselines",
            "offset": 322,
            "tasks_per_run": 8,
            "unique_questions": 8,
            "actor_seed": seed,
            "actor_seed_guarantee": "Best effort; verify actual path agreement",
            "quota_epoch": "batch dispatch after setup",
            "max_budget_charge_usd": max_usd,
            "cooldown_s": cooldown_s,
            "cooldown_inside_batch_timing": False,
            "policies_frozen": True,
            "cases": cases,
            "source_sha256": source_hashes(),
            "limitations": "One live batch per cell; paths and provider timing may vary despite common seeds",
        },
    )
    controller = Path(__file__).read_bytes()
    (output / "controller-source.py").write_bytes(controller)
    write_json(
        output / "controller-source-sha256.json", {"sha256": hashlib.sha256(controller).hexdigest()}
    )
    rows, spent = [], 0.0
    for number, case in enumerate(cases):
        if (output / "STOP").exists():
            raise RuntimeError("Stopped between completed runs")
        if shutil.disk_usage(output).free < 512 * 1024**2:
            raise RuntimeError("Low disk space: stopped before sending further paid requests")
        available = max_usd - spent
        if available < 0.15:
            raise RuntimeError("Cannot reserve the next run within the campaign budget")
        policy = case["policy"]
        directory = (
            output
            / f"{number:02d}-a{case['agents']}-c{case['capacity']}-w{case['window_s']}-{policy}"
        )
        cli = [
            "--backend",
            "http",
            "--agents",
            str(case["agents"]),
            "--count",
            "8",
            "--offset",
            "322",
            "--capacity",
            str(case["capacity"]),
            "--window-s",
            str(case["window_s"]),
            "--policy",
            "jev_full"
            if policy == "jev"
            else "no_speculation"
            if policy == "no_speculation"
            else "current_capacity",
            "--actor-seed",
            str(seed),
            "--max-usd",
            str(min(per_run_max_usd, available)),
            "--forecast-max-usd",
            ".025",
            "--samples",
            "32",
            "--output",
            str(directory),
        ]
        if policy == "jev":
            cli += [
                "--pooled-jev",
                "--history-dataset",
                "results/quota-win-2026-11-15-replication-cohort",
                "--calibration",
                "results/quota-win-2026-11-15-replication-calibration.json",
            ]
        if policy == "quota":
            cli += ["--speculation-planner", "quota"]
        if policy in {"jev", "quota"}:
            cli += ["--generation-step-budget", "4"]
        print("START", directory.name, "spent", spent, flush=True)
        summary = await run(parser().parse_args(cli))
        spent += summary["inference_budget_charge_usd"] + summary["forecast_budget_charge_usd"]
        rows.append({**case, "directory": str(directory), "summary": summary})
        write_json(output / "progress.json", {"runs": rows, "budget_charge_usd": spent})
        if summary["failures"] or summary["unstarted_questions"] or summary["optional_failures"]:
            raise RuntimeError("Failure retained; stopping new paid runs")
        audit(directory)
        print(
            "DONE", directory.name, "mean", summary["mean_completion_s"], "spent", spent, flush=True
        )
        if number + 1 < len(cases):
            print(f"COOLDOWN {cooldown_s} seconds outside batch timing", flush=True)
            await asyncio.sleep(cooldown_s)
    write_json(
        output / "complete.json",
        {
            "runs": len(rows),
            "episodes": sum(r["summary"]["tasks"] for r in rows),
            "budget_charge_usd": spent,
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-usd", type=float, default=1.2)
    p.add_argument("--seed", type=int, default=5851516)
    p.add_argument("--cooldown-s", type=float, default=60)
    args = p.parse_args()
    asyncio.run(experiment(args.output, args.max_usd, seed=args.seed, cooldown_s=args.cooldown_s))
