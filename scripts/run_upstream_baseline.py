"""Run the authors' actual HotPotQARun.webthink, without quota/replay machinery.

The Git checkout stays pristine. Optional state fixes are applied only in memory.
Use --backend mock first; HTTP runs require an explicit incremental dollar cap.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
import warnings
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import requests

from quota_spec.collect_qa import write_json
from quota_spec.paper import (
    REVISION,
    compatibility_fixes,
    load_upstream,
    paper_indices,
    text_client,
    working_directory,
)
from quota_spec.paper_collect import TOOL_FIELDS, mock_transports
from quota_spec.paper_reproduction import FIGURE4, agreement_summary
from quota_spec.telemetry import summarize_inference


class StopRun(BaseException):
    """Escape upstream's retry-and-continue handlers without further paid calls."""


class BoundedTransport:
    def __init__(self, key, budget, output):
        self.key, self.budget, self.output = key, budget, output
        self.spent = 0.0
        self.known_costs = True
        with httpx.Client(timeout=30) as client:
            response = client.get("https://openrouter.ai/api/v1/models")
            response.raise_for_status()
        self.prices = {m["id"]: m["pricing"] for m in response.json()["data"]}
        write_json(output / "pricing.json", self.prices)

    def __call__(self, request):
        payload = json.loads(request.content)
        price = self.prices[payload["model"]]
        # A UTF-8 byte bound plus message overhead, with no tools/images enabled.
        reserve = (len(request.content) + 4096) * float(price["prompt"]) + payload[
            "max_tokens"
        ] * max(float(price["completion"]), float(price.get("internal_reasoning", 0)))
        if not math.isfinite(reserve) or not self.known_costs or self.spent + reserve > self.budget:
            raise StopRun("Incremental dollar budget exhausted or previous cost unknown")
        record = {"request": payload, "reserved_usd": reserve, "cost_usd": None}
        # Unknown network outcomes must prevent retries, even if the caller catches errors.
        self.known_costs = False
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": "Bearer " + self.key},
                    json=payload,
                )
            body = response.json()
            record.update(http_status=response.status_code, response=body)
            cost = body.get("usage", {}).get("cost")
            if isinstance(cost, (int, float)) and math.isfinite(cost) and cost >= 0:
                self.spent += cost
                record["cost_usd"] = cost
                self.known_costs = True
            if not self.known_costs:
                raise StopRun("Missing billed cost; stop instead of making another request")
            return httpx.Response(response.status_code, json=body)
        finally:
            with (self.output / "requests.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")


def isolate_tool_steps(runner):
    """Run hypothetical local tools from pre-tool state; restore real state afterward."""
    original_step = runner.step
    before = {}

    def step(env, action, simulate=False):
        real = env.unwrapped
        state = {k: copy.deepcopy(getattr(real, k)) for k in TOOL_FIELDS}
        if not simulate:
            before.clear()
            before.update(state)
            return original_step(env, action, simulate)
        for key, value in before.items():
            setattr(real, key, copy.deepcopy(value))
        try:
            return original_step(env, action, simulate)
        finally:
            for key, value in state.items():
                setattr(real, key, value)

    runner.step = step


def run(args):
    root, output = args.checkout.resolve(), args.output.resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True
    )
    if revision != REVISION or dirty:
        raise ValueError("Use a pristine checkout at " + REVISION)
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    indices = paper_indices(args.count)
    if args.max_requests <= 0:
        raise ValueError("Use a positive --max-requests")
    if args.backend == "http" and (
        not args.max_usd or not math.isfinite(args.max_usd) or args.max_usd <= 0
    ):
        raise ValueError("HTTP runs require a finite positive --max-usd")
    key = os.environ.get("OPENROUTER_API_KEY")
    if args.backend == "http" and not key:
        raise ValueError("Set OPENROUTER_API_KEY")
    output.mkdir(parents=True)
    (output / "tasks").mkdir()
    records, rows, failure = [], [], None
    bounded = None
    if args.backend == "mock":
        transport, wiki = mock_transports()
    else:
        bounded = BoundedTransport(key, args.max_usd, output)
        transport = httpx.MockTransport(bounded)
        original_get = requests.get

        def wiki(*a, **kw):
            kw.setdefault("timeout", 30)
            response = original_get(*a, **kw)
            response.raise_for_status()
            return response

    client = text_client(
        records,
        args.max_requests,
        output / "inference.jsonl",
        transport=transport,
        api_key=key or "mock",
    )

    class FailFastClient(client):
        def call(self, *a, **kw):
            try:
                return super().call(*a, **kw)
            except Exception as exc:
                raise StopRun("Inference failed: " + str(exc)) from None

    module = load_upstream(root, FailFastClient)
    if args.state_fixes:
        compatibility_fixes(module)
    module.wrappers.DATA_DIR = str(root / "hotpotqa/data")
    module.constants.guess_num_actions = 3
    prompt = module.Utils.join_prompt(
        module.PromptTemplates.REACT_INSTRUCTION,
        json.loads((root / "hotpotqa/prompts/prompts_naive.json").read_text())["webthink_simple6"],
        module.PromptTemplates.PROMPT_INSTRUCTION,
    )
    write_json(
        output / "config.json",
        {
            "revision": revision,
            "checkout": str(root),
            "backend": args.backend,
            "actor": args.actor,
            "speculator": args.speculator,
            "indices": indices,
            "numpy_seed": 248,
            "state_fixes": args.state_fixes,
            "max_usd": args.max_usd,
            "max_requests": args.max_requests,
            "driver": "Original HotPotQARun.webthink; no collector, normalization, replay, quota or Jev",
            "source_sha256": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / "hotpotqa/src").glob("*.py")
            },
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    )
    np.random.seed(248)  # Makes the original reset defect reproducible in diagnostic mode.
    with (
        warnings.catch_warnings(),
        working_directory(output),
        patch("requests.get", side_effect=wiki),
    ):
        warnings.simplefilter("ignore", UserWarning)
        for index in indices:
            runner = module.HotPotQARun(args.actor, args.speculator, False)
            runner.current_index = index
            runner.base_traj_path = str(output / "logs")
            if args.state_fixes:
                isolate_tool_steps(runner)
            started = time.perf_counter()
            try:
                info = runner.webthink(idx=index, prompt=prompt, to_print=False, n=8, simulate=True)
                row = {
                    "requested_index": index,
                    "actual_index": runner.env.data_idx,
                    "normal": runner.env.normal_trajectory_dict,
                    "simulated": runner.env.sim_trajectory_dict,
                    "em": info.get("em") if args.backend == "http" else None,
                    "f1": info.get("f1") if args.backend == "http" else None,
                    "wall_s": time.perf_counter() - started,
                }
                write_json(output / "tasks" / f"{index}.json", row)
                rows.append(row)
                print(
                    f"Completed {len(rows)}/{args.count}; requested={index}, actual={row['actual_index']}",
                    flush=True,
                )
            except (StopRun, Exception) as exc:
                failure = str(exc)
                write_json(
                    output / "failed-task.json",
                    {
                        "requested_index": index,
                        "failure": failure,
                        "normal": runner.env.normal_trajectory_dict,
                        "simulated": runner.env.sim_trajectory_dict,
                    },
                )
                break
    agreement = agreement_summary(rows)
    # Independently execute the original scorer on the exact same saved lists.
    upstream = {
        f"top{k}": statistics.mean(
            module.Metrics.get_action_metrics(r["normal"], r["simulated"], k=k)["general"]
            for r in rows
        )
        if rows
        else None
        for k in (1, 3)
    }
    summary = {
        "tasks": len(rows),
        "requested_tasks": args.count,
        "failure": failure,
        "actual_indices_match": all(r["requested_index"] == r["actual_index"] for r in rows),
        "agreement": agreement,
        "original_scorer": upstream,
        "paper_target": FIGURE4.get(args.speculator),
        "usage": summarize_inference(records),
        "qa_em": statistics.mean(r["em"] for r in rows)
        if rows and args.backend == "http"
        else None,
        "qa_f1": statistics.mean(r["f1"] for r in rows)
        if rows and args.backend == "http"
        else None,
        "live_speedup_measured": False,
        "full_paper_reproduction_established": False,
        "state_fixes": args.state_fixes,
    }
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkout", type=Path, default=Path("tmp/speculative-action-upstream"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--backend", choices=("mock", "http"), default="mock")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--actor", default="google/gemini-2.5-flash")
    p.add_argument("--speculator", default="google/gemini-2.5-flash")
    p.add_argument("--max-requests", type=int, default=448)
    p.add_argument("--max-usd", type=float)
    p.add_argument("--state-fixes", action="store_true")
    return p


if __name__ == "__main__":
    result = run(parser().parse_args())
    raise SystemExit(1 if result["failure"] else 0)
