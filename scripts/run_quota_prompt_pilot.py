"""Bounded, randomized live pilot; policies share questions, not model outputs."""

import argparse
import asyncio
import random
from pathlib import Path

from quota_spec.artifacts import source_hashes, write_json
from quota_spec.live_context_audit import audit
from quota_spec.multi_agent import parser, run


async def pilot(output, max_usd, *, offset=258, cooldown_s=45):
    if output.exists():
        raise ValueError("Choose a fresh pilot directory")
    rng = random.Random(5851511)
    experiments = []
    for capacity, window in [(12, 3), (8, 5), (24, 1)]:
        for block in range(2):
            policies = ["no_speculation", "allow_all", "jev", "blind", "quota"]
            rng.shuffle(policies)
            for policy in policies:
                experiments.append(
                    {
                        "capacity": capacity,
                        "window_s": window,
                        "block": block,
                        "offset": offset + 8 * block,
                        "policy": policy,
                    }
                )
    output.mkdir(parents=True)
    write_json(
        output / "protocol.json",
        {
            "design": "Exploratory live pilot; same 16 new questions in three quota regimes",
            "policies": "Quota vs blind isolates supplied context; all vs none vs frozen Jev are controls",
            "actor": "google/gemini-2.5-flash",
            "speculative_actor": "google/gemini-2.5-flash",
            "observation_speculator": "openai/gpt-4.1-nano",
            "speculation_generation_budget": 4,
            "allow_all_generation_budget": None,
            "max_total_usd": max_usd,
            "order_seed": 5851511,
            "cooldown_between_runs_s": cooldown_s,
            "cooldown_in_batch_timing": False,
            "schema_enforced_planners": True,
            "experiments": experiments,
            "source_sha256": source_hashes(),
            "limitations": "Autonomous stochastic trajectories and provider timings differ; no same-path causal speedup claim",
        },
    )
    spent, rows = 0.0, []
    for number, experiment in enumerate(experiments):
        if (output / "STOP").exists():
            raise RuntimeError("Stopped between complete runs by explicit STOP file")
        name = f"{number:02d}-{experiment['capacity']}-{experiment['window_s']}-b{experiment['block']}-{experiment['policy']}"
        destination = output / name
        if max_usd - spent < 0.15:
            raise RuntimeError("Pilot budget cannot reserve the next bounded run")
        policy = experiment["policy"]
        cli = [
            "--backend",
            "http",
            "--policy",
            "jev_full"
            if policy == "jev"
            else "no_speculation"
            if policy == "no_speculation"
            else "current_capacity",
            "--agents",
            "4",
            "--count",
            "8",
            "--offset",
            str(experiment["offset"]),
            "--capacity",
            str(experiment["capacity"]),
            "--window-s",
            str(experiment["window_s"]),
            "--max-usd",
            "0.15",
            "--forecast-max-usd",
            "0.025",
            "--output",
            str(destination),
            "--samples",
            "32",
        ]
        if policy == "jev":
            cli += [
                "--pooled-jev",
                "--calibration",
                "results/quota-win-2026-11-15-replication-calibration.json",
                "--history-dataset",
                "results/quota-win-2026-11-15-replication-cohort",
            ]
        if policy in {"blind", "quota"}:
            cli += ["--speculation-planner", policy]
        if policy in {"jev", "blind", "quota"}:
            cli += ["--generation-step-budget", "4"]
        print("START", name, "spent", round(spent, 6), flush=True)
        summary = await run(parser().parse_args(cli))
        charge = summary["inference_budget_charge_usd"] + summary["forecast_budget_charge_usd"]
        spent += charge
        rows.append({**experiment, "directory": str(destination), "summary": summary})
        write_json(output / "progress.json", {"runs": rows, "budget_charge_usd": spent})
        if summary["failures"] or summary["unstarted_questions"]:
            raise RuntimeError("Live failure retained; stopping further paid runs")
        audit(destination)
        if policy in {"blind", "quota"} and summary["optional_failures"]:
            raise RuntimeError(
                "Direct planner failed; retain the run and stop before more spending"
            )
        print("DONE", name, "mean", summary["mean_completion_s"], "total_usd", spent, flush=True)
        if number + 1 < len(experiments):
            print("COOLDOWN outside batch timing", cooldown_s, flush=True)
            await asyncio.sleep(cooldown_s)
    write_json(output / "complete.json", {"runs": len(rows), "budget_charge_usd": spent})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-usd", type=float, default=1.5)
    p.add_argument("--offset", type=int, default=258)
    p.add_argument("--cooldown-s", type=float, default=45)
    args = p.parse_args()
    asyncio.run(pilot(args.output, args.max_usd, offset=args.offset, cooldown_s=args.cooldown_s))
