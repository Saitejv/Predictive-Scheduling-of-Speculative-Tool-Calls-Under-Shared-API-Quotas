"""Live paper-aligned HotpotQA workers with shared quota and Jev context engine."""

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from contextlib import AsyncExitStack
from pathlib import Path

from .adapters import JevPredictor, MockSystemOnePredictor
from .artifacts import source_hashes, write_json
from .capture import Capture
from .context_engine import ContextCoordinator, ForecastCache, SharedSearch
from .frozen_replay import load_dataset
from .hotpot_runtime import Events, LiveChat, MockChat, MockSearch, Runtime, WikiSearch
from .prediction import Forecast
from .probability_calibration import ProbabilityCalibration
from .tape_forecasts import TapeHistory, digest
from .telemetry import summarize_inference
from .upstream import REVISION, load_upstream, prepare, workload_indices


class ObservedEvents(Events):
    coordinator = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.answers = {}

    def emit(self, event, **fields):
        row = super().emit(event, **fields)
        if self.coordinator:
            self.coordinator.on_event(row)
        if event == "answer_ready" and fields["episode"] in self.answers:
            self.answers[fields["episode"]].set_result(row)
        return row


class MockHistory:
    training_ids = ()

    def predict(self, state, agent):
        return Forecast(0.75, 1, (0.01,), (0.03,), 0.5)


def account_data(body):
    """Retain accounting fields without key metadata or credentials."""
    data = body["data"]
    return {
        k: data.get(k) for k in ("usage", "usage_daily", "limit", "limit_remaining", "is_free_tier")
    }


def validate(rows, events, agents, capacity):
    claims = [e for e in events if e["event"] == "quota_claimed"]
    by_window = {}
    for row in claims:
        by_window[row["window_index"]] = by_window.get(row["window_index"], 0) + 1
    if any(n > capacity for n in by_window.values()):
        raise ValueError("Shared quota exceeded")
    active, maximum = set(), 0
    for row in events:
        if row["event"] == "episode_started":
            active.add(row["episode"])
            maximum = max(maximum, len(active))
        elif row["event"] == "answer_ready":
            active.remove(row["episode"])
    if active or maximum > agents:
        raise ValueError("Active worker invariant failed")
    if any(r["resource_s"] < r["completion_s"] for r in rows):
        raise ValueError("Episode accounting is inconsistent")
    starts = [e for e in events if e["event"] == "search_started"]
    if len(starts) != len(claims):
        raise ValueError("Dispatch/claim inventory mismatch")
    return {
        "quota_valid": True,
        "worker_limit_valid": True,
        "max_active_agents": maximum,
        "quota_claims": len(claims),
        "windows": by_window,
    }


async def run(args):
    if args.output.exists():
        raise ValueError("Choose a fresh output directory")
    if (
        args.agents < 1
        or args.count < 1
        or args.capacity < 1
        or not math.isfinite(args.window_s)
        or args.window_s <= 0
    ):
        raise ValueError("Use positive worker, task and quota settings")
    if not math.isfinite(args.max_usd) or not 0 < args.forecast_max_usd < args.max_usd:
        raise ValueError("Use a positive forecast budget smaller than total max-usd")
    if not 0 <= args.reserve <= args.capacity or args.max_forecast_requests < 1:
        raise ValueError("Invalid reserve or forecast request limit")
    if args.optional_slots is not None and args.optional_slots < 1:
        raise ValueError("Use at least one optional inference slot")
    if not 1 <= args.forecast_workers <= 64:
        raise ValueError("Use 1..64 forecast workers")
    if not math.isfinite(args.wiki_min_interval_s) or args.wiki_min_interval_s < 0:
        raise ValueError("Use a finite nonnegative Wikipedia pacing interval")
    if args.wiki_min_interval_s and args.purpose != "capture":
        raise ValueError("Artificial Wikipedia pacing requires --purpose capture")
    if (
        args.backend == "http"
        and args.policy.startswith("jev")
        and not os.environ.get("TYPESAFE_API_KEY")
    ):
        raise ValueError("Set TYPESAFE_API_KEY before starting a paid Jev run")
    root = prepare(args.source)

    class NoSync:
        def __init__(self, **kw):
            pass

        def call(self, *a, **kw):
            raise AssertionError("Unexpected upstream synchronous inference")

    module = load_upstream(root, NoSync)
    examples = json.loads((root / "hotpotqa/prompts/prompts_naive.json").read_text())[
        "webthink_simple6"
    ]
    base = module.Utils.join_prompt(
        module.PromptTemplates.REACT_INSTRUCTION,
        examples,
        module.PromptTemplates.PROMPT_INSTRUCTION,
    )
    data = json.loads((root / "hotpotqa/data/hotpot_dev_v1_simplified.json").read_text())
    indices = workload_indices(args.count, args.offset)
    history = None
    development_sha256 = None
    if args.policy in {"jev_full", "jev_own", "history_full"}:
        if args.backend == "mock":
            history = MockHistory()
        else:
            tapes = load_dataset(args.history_dataset)["tapes"][: args.development_count]
            if set(str(i) for i in indices) & {str(t["task_id"]) for t in tapes}:
                raise ValueError("Live questions must be disjoint from history development tasks")
            history = TapeHistory(tapes)
            development_sha256 = digest(tapes)
    key = os.environ.get("OPENROUTER_API_KEY")
    if args.backend == "http" and not key:
        raise ValueError("Set OPENROUTER_API_KEY")
    output = args.output.resolve()
    output.mkdir(parents=True)
    (output / "tasks").mkdir()
    (output / "source-snapshot").mkdir()
    for name in source_hashes():
        (output / "source-snapshot" / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    events = ObservedEvents(output / "events.jsonl")
    capture = Capture(output / "capture", events.start)
    import httpx

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(httpx.AsyncClient(timeout=args.request_timeout_s))
        prices = {}
        if args.backend == "http":
            response = await client.get("https://openrouter.ai/api/v1/models")
            response.raise_for_status()
            prices = {m["id"]: m["pricing"] for m in response.json()["data"]}
            if args.policy.startswith("jev"):
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    params={"output_modalities": "decisions"},
                )
                response.raise_for_status()
                prices.update({m["id"]: m["pricing"] for m in response.json()["data"]})
            write_json(output / "pricing.json", prices)
            response = await client.get(
                "https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key}
            )
            response.raise_for_status()
            write_json(output / "account-before.json", account_data(response.json()))
            chat = LiveChat(
                client,
                key,
                prices,
                output,
                events,
                args.max_usd - args.forecast_max_usd,
                args.max_requests,
                args.actor,
                args.speculator,
                draft_actor=args.draft_actor,
                reserve_unknown_cost=True,
                optional_allowed=lambda episode: episode in coordinator.agents,
            )
            optional_slots = args.optional_slots or args.agents
            chat.semaphore = asyncio.Semaphore(args.agents + optional_slots)
            chat.optional_semaphore = asyncio.Semaphore(optional_slots)
            search = WikiSearch(module, events, min_interval_s=args.wiki_min_interval_s)
        else:
            chat, search = MockChat(), MockSearch(events)

        pooled = None
        pool_startup_s = 0.0
        if args.pooled_jev and args.backend == "http" and args.policy.startswith("jev"):
            from .pooled_jev import JevHTTPPool, PooledJevPredictor

            pool_started = time.perf_counter()
            pooled = stack.enter_context(JevHTTPPool(connections=args.forecast_workers))
            pool_startup_s = time.perf_counter() - pool_started

        def factory():
            if args.backend == "mock":
                return MockSystemOnePredictor(
                    history, context=args.context, input_usd_per_million=0, output_usd_per_million=0
                )
            if pooled is not None:
                return PooledJevPredictor(
                    history, pool=pooled, context=args.context, timeout_s=args.forecast_timeout_s
                )
            return JevPredictor(history, context=args.context, timeout_s=args.forecast_timeout_s)

        # The bounded adapter caps both request and response at 64 KiB. Reserve
        # 65536 tokens in each direction at current catalog prices, plus any
        # per-request charge; provider costs remain the reported measurement.
        jev_model = os.environ.get("JEV_MODEL", "jev-latest")
        calibrated = None
        if args.calibration:
            if not args.policy.startswith("jev"):
                raise ValueError("Calibration requires a Jev policy")
            calibrated = ProbabilityCalibration(json.loads(args.calibration.read_text()))
            if (
                calibrated.artifact["model"] != jev_model
                or calibrated.artifact["context"] != args.context
                or set(calibrated.artifact["development_ids"]) != set(history.training_ids)
            ):
                raise ValueError("Calibration model, context or development split mismatch")
            write_json(output / "calibration.json", calibrated.artifact)
        price = prices.get(jev_model)
        if args.backend == "http" and args.policy.startswith("jev") and not price:
            raise ValueError("Jev model price unavailable; configure a catalogued OpenRouter model")
        forecast_reserve = (
            max(
                0.001,
                65536 * (float(price["prompt"]) + float(price["completion"]))
                + float(price.get("request", 0)),
            )
            if price
            else 0
        )
        forecasts = ForecastCache(
            factory,
            output=output / "forecasts.jsonl",
            max_requests=args.max_forecast_requests,
            max_usd=args.forecast_max_usd,
            request_reserve_usd=forecast_reserve,
            ttl_s=args.context_ttl_s,
            calibration=calibrated,
            mode=args.context,
            workers=args.forecast_workers,
        )
        coordinator = ContextCoordinator(
            events,
            capacity=args.capacity,
            window_s=args.window_s,
            policy=args.policy,
            reserve=args.reserve,
            history=history,
            forecasts=forecasts,
            samples=args.samples,
            horizon_s=args.horizon_s,
        )
        events.coordinator = coordinator
        search = SharedSearch(search, coordinator)
        write_json(
            output / "config.json",
            {
                **{k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "indices": indices,
                "development_ids": history.training_ids if history else [],
                "development_sha256": development_sha256,
                "capture_protocol": "multi_agent",
                "upstream": json.loads((root / "upstream.json").read_text()),
                "source_sha256": source_hashes(),
                "jev_model": jev_model,
                "forecast_request_reserve_usd": forecast_reserve,
                "context_cache": "bounded observed state; phase cache TTL, real elapsed at cache miss",
                "worker_release": "answer; all started background work drains and counts",
                "comparison": "Independent live trajectories; no causal speedup inferred",
                "required_result_cache": False,
                "context_history_argument_key": "value",
                "max_steps": 7,
                "width": args.width,
                "calibration_sha256": calibrated.artifact["sha256"] if calibrated else None,
                "jev_pool_startup_s": pool_startup_s,
                "transport": {
                    "retries": args.model_retries,
                    "unknown_cost": "conservative_reservation",
                    "drop_expired_unsent": True,
                    "actor_slots": args.agents,
                    "optional_slots": args.optional_slots or args.agents,
                },
            },
        )
        queue = asyncio.Queue()
        for index in indices:
            queue.put_nowait(index)
        tasks, rows = [], []
        aborted = asyncio.Event()

        async def execute(index, worker):
            runtime = Runtime(
                module,
                chat,
                search,
                events,
                base,
                capture=capture,
                coordinator=coordinator,
                speculative_width=args.width,
                model_retries=args.model_retries,
                max_generation_step=args.generation_step_budget,
            )
            mode = "sequential" if args.policy == "no_speculation" else "speculative"
            row = await runtime.episode(
                index, data[index]["question"], data[index]["answer"], mode, args.backend
            )
            rows.append(row)
            write_json(output / "tasks" / f"{index}.json", row)
            print(
                f"{args.policy} worker={worker} question={index}: {row['completion_s']:.3f}s hits={row['cache_hits']} failure={row['failure']}",
                flush=True,
            )
            return row

        async def worker(number):
            while not queue.empty() and not aborted.is_set():
                index = queue.get_nowait()
                mode = "sequential" if args.policy == "no_speculation" else "speculative"
                episode = f"{index}:{mode}"
                ready = asyncio.get_running_loop().create_future()
                events.answers[episode] = ready
                task = asyncio.create_task(execute(index, number))
                tasks.append(task)
                # Runtime emits answer even for model/tool failures. Preserve a
                # programming failure too, rather than hanging a worker forever.
                await asyncio.wait((ready, task), return_when=asyncio.FIRST_COMPLETED)
                if ready.done() and ready.result().get("failure"):
                    aborted.set()
                if task.done() and task.exception():
                    raise task.exception()

        await asyncio.gather(*(worker(i) for i in range(min(args.agents, args.count))))
        await asyncio.gather(*tasks)
        capture.seal()
        checks = validate(rows, events.rows, args.agents, args.capacity)
        answer_end = max(r["answer_at_s"] for r in rows)
        resource_end = max(r["drained_at_s"] for r in rows)
        batch_start = min(r["started_at_s"] for r in rows)
        summary = {
            "policy": args.policy,
            "backend": args.backend,
            "tasks": len(rows),
            "failures": sum(bool(r["failure"]) for r in rows),
            "unstarted_questions": queue.qsize(),
            **checks,
            "mean_completion_s": statistics.mean(r["completion_s"] for r in rows),
            "p95_completion_s": sorted(r["completion_s"] for r in rows)[
                math.ceil(0.95 * len(rows)) - 1
            ],
            "batch_started_at_s": batch_start,
            "answer_makespan_s": answer_end - batch_start,
            "resource_makespan_s": resource_end - batch_start,
            "questions_per_s": len(rows) / (resource_end - batch_start),
            "mean_required_wait_s": statistics.mean(
                [
                    e["wait_s"]
                    for e in events.rows
                    if e["event"] == "quota_claimed" and not e["speculative"]
                ]
                or [0]
            ),
            "cache_hits": sum(r["cache_hits"] for r in rows),
            "prefetches": sum(r["prefetches"] for r in rows),
            "unused_prefetches": sum(r["unused_prefetches"] for r in rows),
            "optional_failures": sum(r["optional_failures"] for r in rows),
            "inference_budget_charge_usd": chat.spent if isinstance(chat, LiveChat) else 0,
            "forecast_budget_charge_usd": forecasts.spent,
            "unknown_cost_upper_bound_usd": sum(
                r.get("budget_charge_usd", 0) for r in chat.records if r.get("cost_usd") is None
            ),
            "em": statistics.mean(r["em"] or 0 for r in rows) if args.backend == "http" else None,
            "f1": statistics.mean(r["f1"] or 0 for r in rows) if args.backend == "http" else None,
            "inference": summarize_inference(chat.records),
            "forecasts": summarize_inference(forecasts.records),
            "context_cache_hits": forecasts.hits,
            "decision_reasons": {
                reason: sum(d["reason"] == reason for d in coordinator.decisions)
                for reason in sorted({d["reason"] for d in coordinator.decisions})
            },
        }
        write_json(output / "summary.json", summary)
        if args.backend == "http":
            response = await client.get(
                "https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key}
            )
            response.raise_for_status()
            write_json(output / "account-after.json", account_data(response.json()))
        return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("mock", "http"), default="mock")
    p.add_argument("--purpose", choices=("benchmark", "capture"), default="benchmark")
    p.add_argument("--wiki-min-interval-s", type=float, default=0)
    p.add_argument(
        "--policy",
        choices=(
            "no_speculation",
            "current_capacity",
            "fixed_reserve",
            "history_full",
            "jev_full",
            "jev_own",
        ),
        default="jev_full",
    )
    p.add_argument("--agents", type=int, default=4)
    p.add_argument("--capacity", type=int, default=12)
    p.add_argument("--window-s", type=float, default=30)
    p.add_argument("--reserve", type=int, default=0)
    p.add_argument("--source", type=Path, default=Path("data/raw/speculative-action") / REVISION)
    p.add_argument("--history-dataset", type=Path, default=Path("results/hotpot-dataset-50"))
    p.add_argument("--development-count", type=int, default=20)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--offset", type=int, default=50)
    p.add_argument("--actor", default="google/gemini-2.5-flash")
    p.add_argument("--speculator", default="openai/gpt-4.1-nano")
    p.add_argument(
        "--draft-actor",
        default=None,
        help="Optional speculative actor ablation; default uses the authoritative actor",
    )
    p.add_argument("--width", type=int, choices=(1, 3), default=3)
    p.add_argument("--calibration", type=Path, default=None)
    p.add_argument(
        "--context",
        choices=("task", "history", "progress", "no_history", "no_progress", "progress_intent"),
        default="progress",
    )
    p.add_argument("--max-usd", type=float, default=1)
    p.add_argument("--forecast-max-usd", type=float, default=0.1)
    p.add_argument("--max-requests", type=int, default=600)
    p.add_argument("--max-forecast-requests", type=int, default=400)
    p.add_argument("--forecast-workers", type=int, default=4)
    p.add_argument("--pooled-jev", action="store_true")
    p.add_argument("--generation-step-budget", type=int, default=None)
    p.add_argument(
        "--optional-slots",
        type=int,
        default=None,
        help="Optional inference slots; default one per worker, with separate actor reservation",
    )
    p.add_argument("--model-retries", type=int, choices=(0, 1, 2, 3), default=2)
    p.add_argument("--request-timeout-s", type=float, default=90)
    p.add_argument("--forecast-timeout-s", type=float, default=3)
    p.add_argument("--context-ttl-s", type=float, default=0.5)
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--horizon-s", type=float, default=30)
    return p


def main():
    summary = asyncio.run(run(parser().parse_args()))
    print(json.dumps(summary, indent=2))
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
