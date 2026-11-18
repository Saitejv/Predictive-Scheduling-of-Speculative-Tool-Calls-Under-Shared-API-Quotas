"""Paired fixed-path experiments: peer information and Search service latency.

Paid language gates decide on saved candidates, never on hidden future actions.
Latency sweeps are explicitly counterfactual simulations, not native benchmarks.
"""

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import random
import socket
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.artifacts import append_json, source_hashes, write_json
from quota_spec.forecast_study import TimedHistory, validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset, scheduling_options
from quota_spec.hotpot_runtime import Events
from quota_spec.matched_context_study import CalibratedBank
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.probability_calibration import ProbabilityCalibration
from quota_spec.team_context import LanguageAdmission
from quota_spec.transport import LiveChat

DATA = Path("results/quota-win-2026-11-15-replication-cohort")
BANK = Path("results/quota-win-2026-11-15-replication-forecasts/bank.json")
CAL = Path("results/quota-win-2026-11-15-replication-calibration.json")


class ServiceAwareBank(CalibratedBank):
    def __init__(self, history, duration):
        super().__init__(history, BANK, ProbabilityCalibration(json.loads(CAL.read_text())))
        self.duration = duration

    def predict(self, state, agent):
        value = super().predict(state, agent)
        return value if self.duration is None else replace(value, durations_s=(self.duration,))


def execute(tapes, case, policy):
    ordered = list(tapes)
    random.Random(case["seed"]).shuffle(ordered)
    run = FrozenReplay(
        ordered,
        case["capacity"],
        case["window_s"],
        max_active_agents=case["agents"],
        tool_duration_s=case["search_s"],
        max_candidate_age=7,
        suppress_known_calls=True,
        revalidate_reset=True,
        max_generation_step=None if case["policy"] == "all" else 4,
        **scheduling_options("overlap"),
    ).run(policy)
    validate(run, ordered, case["capacity"], case["window_s"], case["agents"])
    return run


def persist(output, case, run):
    # Keep sufficient schedules for independent quota/answer checks, no duplicated tool blobs.
    name = f"{case['agents']}-{case['capacity']}-{case['window_s']}-{case['search_s']}-{case['seed']}-{case['policy']}"
    with gzip.open(output / "schedules" / (name + ".json.gz"), "wt") as handle:
        json.dump(run, handle, separators=(",", ":"))
    row = {
        **case,
        **{k: v for k, v in run["metrics"].items() if not isinstance(v, (list, dict))},
        "schedule": "schedules/" + name + ".json.gz",
    }
    append_json(output / "rows.jsonl", row)
    return row


def initialize(output, mode, tapes, cases, max_usd=None):
    output.mkdir(parents=True, exist_ok=False)
    (output / "schedules").mkdir()
    hashes = source_hashes()
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    for name, expected in hashes.items():
        content = (Path(__file__).resolve().parents[1] / "src" / "quota_spec" / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Source changed while freezing experiment")
        (snapshot / name).write_bytes(content)
    write_json(
        output / "protocol.json",
        {
            "mode": mode,
            "source_sha256": hashes,
            "cases": cases,
            "dataset": str(DATA),
            "bank": str(BANK),
            "calibration": str(CAL),
            "evaluation_ids": [t["task_id"] for t in tapes],
            "max_usd": max_usd,
            "answers_and_authoritative_paths_fixed": True,
            "service_override": "Search only, both required and optional; local Lookup unchanged",
            "provider_model": "Unlimited concurrent provider service in replay",
            "forecast_latency": "Actual saved pooled Jev RTT, or actual new LLM gate wall time",
            "candidate_generation": "Same saved candidates and recorded observation/hypothetical generation times",
            "step_budget": "4 except unrestricted full speculation; all_budget4 isolates this difference",
            "limitations": "Exploratory reuse of earlier evaluation questions, not a fresh confirmatory test. LLM admission is a new gate on saved queries, distinct from the live quota-aware query generator.",
        },
    )
    (output / "controller-source.py").write_bytes(Path(__file__).read_bytes())


def sweep(output):
    tapes = load_dataset(DATA)["tapes"]
    history, evaluation = TimedHistory(tapes[:20]), tapes[20:]
    cases = [
        dict(agents=a, capacity=c, window_s=w, search_s=d, seed=s, policy=p)
        for a in (1, 2, 4, 6, 8)
        for c, w in ((1000000, 3), (12, 3), (8, 5))
        for d in (None, 0.1, 1.0, 3.0)
        for s in (248, 249, 250)
        for p in ("none", "all", "all_budget4", "jev_own", "jev_full")
    ]
    initialize(output, "offline_latency_sweep", evaluation, cases)
    rows = []
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network during sweep")),
        patch.object(
            socket.socket, "connect_ex", side_effect=AssertionError("Network during sweep")
        ),
    ):
        for i, case in enumerate(cases):
            if case["policy"] == "none":
                policy = NoSpeculation()
            elif case["policy"].startswith("all"):
                policy = CurrentCapacity()
            else:
                policy = PredictiveAdmission(
                    ServiceAwareBank(history, case["search_s"]),
                    AdmissionConfig(samples=32, seed=case["seed"], nonblocking=True),
                    own_only=case["policy"] == "jev_own",
                )
            rows.append(persist(output, case, execute(evaluation, case, policy)))
            if (i + 1) % 15 == 0:
                print("SWEEP", i + 1, "/", len(cases), flush=True)
    write_json(output / "rows.json", rows)
    write_json(
        output / "validation.json",
        dict(
            passed=True,
            runs=len(rows),
            network_blocked=True,
            answers_preserved=True,
            forecast_fallbacks=0,
        ),
    )


async def paid(output, max_usd, count, details=("quota", "team"), seed=248):
    tapes = load_dataset(DATA)["tapes"][20 : 20 + count]
    cases = [
        dict(agents=a, capacity=c, window_s=w, search_s=d, seed=seed, policy=p)
        for a in (4, 8)
        for c, w in ((12, 3), (8, 5))
        for d in (0.1, 3.0)
        for p in details
    ]
    random.Random(5851717 + seed - 248).shuffle(cases)
    initialize(output, "paid_language_admission_ablation", tapes, cases, max_usd)
    prices = json.loads(
        Path("results/quota-win-2026-11-15-native-capture/pricing.json").read_text()
    )
    rows, seen = [], set()
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(timeout=45) as client:
        chat = LiveChat(
            client,
            os.environ["OPENROUTER_API_KEY"],
            prices,
            output,
            Events(),
            max_usd,
            1000,
            "google/gemini-2.5-flash",
            "openai/gpt-4.1-nano",
            reserve_unknown_cost=True,
        )
        for i, case in enumerate(cases):
            if (output / "STOP").exists():
                raise RuntimeError("Stopped between cases")

            def callback(prompt, state):
                started = time.perf_counter()
                content = asyncio.run_coroutine_threadsafe(
                    chat.call(prompt, "speculative_actor", state.task_id, state.completed_calls),
                    loop,
                ).result()
                return content, time.perf_counter() - started, chat.requests

            policy = LanguageAdmission(
                callback, detail=case["policy"], search_duration_s=case["search_s"]
            )
            run = await asyncio.to_thread(execute, tapes, case, policy)
            rows.append(persist(output, case, run))
            write_json(
                output / "progress.json",
                dict(runs=i + 1, cost_usd=chat.spent, requests=chat.requests),
            )
            print(
                "PAID",
                i + 1,
                "/",
                len(cases),
                case,
                "mean",
                run["metrics"]["mean_completion_s"],
                "cost",
                chat.spent,
                flush=True,
            )
            # Matching baselines on precisely the same small task subset.
            for name, rule in [
                ("none", NoSpeculation()),
                ("all", CurrentCapacity()),
                ("all_budget4", CurrentCapacity()),
            ]:
                base = {**case, "policy": name}
                namekey = (
                    base["agents"],
                    base["capacity"],
                    base["window_s"],
                    base["search_s"],
                    name,
                )
                if namekey not in seen:
                    rows.append(persist(output, base, execute(tapes, base, rule)))
                    seen.add(namekey)
        write_json(output / "rows.json", rows)
        write_json(
            output / "validation.json",
            dict(
                passed=True,
                runs=len(rows),
                answers_preserved=True,
                cost_usd=chat.spent,
                requests=chat.requests,
                unknown_cost=chat.unknown,
            ),
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["sweep", "paid"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-usd", type=float, default=1.0)
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--seed", type=int, default=248)
    p.add_argument(
        "--details", choices=["quota", "phases", "team"], nargs="+", default=["quota", "team"]
    )
    args = p.parse_args()
    if args.mode == "sweep":
        sweep(args.output)
    else:
        asyncio.run(paid(args.output, args.max_usd, args.count, args.details, args.seed))
