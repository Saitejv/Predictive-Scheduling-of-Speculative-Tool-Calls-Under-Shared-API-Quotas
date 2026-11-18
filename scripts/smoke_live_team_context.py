"""Native live functionality check; stochastic paths are not a causal speed trial."""

import argparse
import asyncio
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.live_context_audit import audit
from quota_spec.multi_agent import parser, run


async def check(output, offset=330, styles=("team", "quota")):
    output.mkdir(parents=True, exist_ok=False)
    (output / "controller-source.py").write_bytes(Path(__file__).read_bytes())
    results = []
    for number, style in enumerate(styles):
        root = output / style
        args = parser().parse_args(
            [
                "--backend",
                "http",
                "--agents",
                "4",
                "--count",
                "8",
                "--offset",
                str(offset),
                "--capacity",
                "8",
                "--window-s",
                "5",
                "--policy",
                "current_capacity",
                "--speculation-planner",
                style,
                "--generation-step-budget",
                "4",
                "--actor-seed",
                "5851717",
                "--max-usd",
                ".15",
                "--forecast-max-usd",
                ".01",
                "--output",
                str(root),
            ]
        )
        result = await run(args)
        checked = audit(root)
        results.append(dict(style=style, summary=result, audit=checked))
        write_json(output / "progress.json", results)
        if result["failures"] or result["optional_failures"] or result["unstarted_questions"]:
            raise RuntimeError("Incomplete live smoke retained")
        if number + 1 < len(styles):
            print("COOLDOWN 30 seconds outside measured batch", flush=True)
            await asyncio.sleep(30)
    write_json(output / "complete.json", results)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--offset", type=int, default=330)
    p.add_argument(
        "--styles", nargs="+", choices=["quota", "team", "quota_team"], default=["team", "quota"]
    )
    args = p.parse_args()
    asyncio.run(check(args.output, args.offset, args.styles))
