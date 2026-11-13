"""Exact-context forecasts and development-only history for multi-candidate tapes.

Own candidates can be judged while their parent tool runs OR during the next
actor's thinking phase. Both finite contexts are enumerated, with elapsed=0.
Labels are produced separately and never passed to a model or replay predictor.
"""

import argparse
import concurrent.futures
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

from .adapters import JevPredictor, KevPredictor, KevSpacePredictor, MockSystemOnePredictor
from .artifacts import write_json
from .frozen_forecasts import as_call
from .frozen_replay import load_dataset
from .models import AgentState, Call, Observation, Snapshot, nonnegative, positive_int
from .prediction import Forecast, bounded_context, calibration
from .telemetry import summarize_inference


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def cases(tapes, mode="progress", *, max_candidate_age=0):
    """Yield exact observed inputs, then separate evaluation labels."""
    for tape in tapes:
        steps, tid = tape["steps"], tape["task_id"]
        for index in range(len(steps) + 1):
            for phase in ("thinking", "queued", "running") if index < len(steps) else ("thinking",):
                boundary = index + int(phase != "thinking")
                history = tuple(as_call(s["action"]) for s in steps[:boundary])[-8:]
                agent = AgentState(
                    tid,
                    0,
                    index,
                    phase,
                    0,
                    task_context=tape["question"],
                    history=history,
                    result_excerpt=steps[index - 1].get("observed_excerpt", "") if index else "",
                )
                candidates = [None]
                latest = index if phase == "running" else index - 1
                parents = range(max(0, latest - max_candidate_age), latest + 1)
                if phase == "queued":
                    parents = range(max(0, index - max_candidate_age), index)
                for parent in parents:
                    if 0 <= parent < len(steps) and steps[parent]["window"]:
                        candidates += [
                            c for c in steps[parent]["window"]["candidates"] if c["eligible"]
                        ]
                future = [s for s in steps[boundary:] if s["tool"] == "search"]
                for candidate in candidates:
                    state = Observation(
                        0,
                        tid if candidate else "__other_agent__",
                        index,
                        Call.search(candidate["query"] if candidate else "[omitted]"),
                        3,
                        0,
                        Snapshot(3, 10, (agent,)),
                    )
                    context = bounded_context(state, agent, mode)
                    labels = {
                        "next": bool(future),
                        "continues": len(future) > 1,
                        "reuse": future[0]["query"] == candidate["query"]
                        if candidate and future
                        else False
                        if candidate
                        else None,
                    }
                    yield (
                        {
                            "task_id": tid,
                            "context": context,
                            "key": digest(context),
                            "index": index,
                            "phase": phase,
                            "own": candidate is not None,
                        },
                        state,
                        agent,
                        labels,
                    )


class TapeHistory:
    """Phase-conditioned empirical future Search timing, trained on development tapes only."""

    def __init__(self, tapes):
        self.training_ids = tuple(t["task_id"] for t in tapes)
        self.rows = {}
        for case, _, _, labels in cases(tapes):
            index, phase = case["index"], case["phase"]
            steps = next(t["steps"] for t in tapes if t["task_id"] == case["task_id"])
            boundary = index + int(phase != "thinking")
            future = [j for j in range(boundary, len(steps)) if steps[j]["tool"] == "search"]
            delay = (
                sum(
                    s["actor_duration_s"] + s["tool_duration_s"]
                    for s in steps[boundary : future[0]]
                )
                + steps[future[0]]["actor_duration_s"]
                if future
                else 0.0
            )
            self.rows.setdefault((index, phase, case["own"]), []).append(
                {
                    **labels,
                    "delay": delay,
                    "duration": steps[future[0]]["tool_duration_s"] if future else 0.0,
                }
            )

    def predict(self, state, agent):
        own = agent.task_id == state.task_id
        rows = self.rows.get((agent.completed_calls, agent.phase, own))
        if not rows:
            rows = [
                r
                for (i, p, o), values in self.rows.items()
                if p == agent.phase and o == own
                for r in values
            ]
        if not rows:
            rows = [r for values in self.rows.values() for r in values]
        yes = [r for r in rows if r["next"]]
        times = yes or rows
        times = [times[i * len(times) // min(128, len(times))] for i in range(min(128, len(times)))]
        return Forecast(
            (sum(bool(r["reuse"]) for r in yes) + 1) / (len(yes) + 2),
            (len(yes) + 1) / (len(rows) + 2),
            tuple(r["delay"] for r in times),
            tuple(r["duration"] for r in times),
            (sum(r["continues"] for r in yes) + 1) / (len(yes) + 2),
        )


def collect(
    dataset,
    output,
    *,
    backend="jev",
    mode="progress",
    development_count=20,
    workers=4,
    max_requests=2000,
    resume=False,
    split="all",
    max_candidate_age=0,
    seed_bank=None,
):
    positive_int(workers, "workers")
    positive_int(max_requests, "max_requests")
    data, root = load_dataset(dataset), Path(output)
    if not 1 <= development_count < len(data["tapes"]):
        raise ValueError("Development/evaluation splits must both be nonempty")
    dev = {t["task_id"] for t in data["tapes"][:development_count]}
    history = TapeHistory(data["tapes"][:development_count])
    selected = [
        t
        for t in data["tapes"]
        if split == "all" or (t["task_id"] in dev) == (split == "development")
    ]
    positive_int(max_candidate_age, "max_candidate_age", 0)
    rows = list(cases(selected, mode, max_candidate_age=max_candidate_age))
    unique = {c["key"]: (c, s, a) for c, s, a, _ in rows}
    constructor = {
        "jev": JevPredictor,
        "kev": KevPredictor,
        "kev-space": KevSpacePredictor,
        "mock": MockSystemOnePredictor,
    }[backend]

    def predictor():
        return constructor(history, context=mode, timeout_s=30, decision_timeout_s=60)

    probe = predictor()
    config = {
        "version": 1,
        "backend": backend,
        "mode": mode,
        "model": probe.model,
        "revision": probe.model_revision,
        "base_url": probe.base_url,
        "dataset_sha256": hashlib.sha256(
            (Path(dataset) / "dataset-manifest.json").read_bytes()
        ).hexdigest(),
        "development": sorted(dev),
        "split": split,
        "keys_sha256": digest(sorted(unique)),
        "elapsed": "phase-entry zero",
        "workers": workers,
        "adapter_sha256": hashlib.sha256(
            Path(__file__).with_name("adapters.py").read_bytes()
        ).hexdigest(),
    }
    if max_candidate_age or seed_bank:
        config["max_candidate_age"] = max_candidate_age
        config["seed_bank_sha256"] = None
    seeded = []
    if seed_bank:
        prior = json.loads(Path(seed_bank).read_text())
        if prior.get("sha256") != digest({k: v for k, v in prior.items() if k != "sha256"}):
            raise ValueError("Seed bank checksum mismatch")
        for field in (
            "backend",
            "mode",
            "model",
            "revision",
            "base_url",
            "dataset_sha256",
            "development",
        ):
            if prior["config"][field] != config[field]:
                raise ValueError("Seed bank model/input mismatch: " + field)
        config["seed_bank_sha256"] = prior["sha256"]
        seeded = [
            {**value, "seed_bank_sha256": prior["sha256"]}
            for key, value in prior["responses"].items()
            if key in unique
        ]
    if root.exists() and not resume:
        raise ValueError("Choose fresh output or explicit --resume")
    if root.exists():
        if json.loads((root / "config.json").read_text()) != config:
            raise ValueError("Resume configuration mismatch")
    else:
        root.mkdir(parents=True)
        write_json(root / "config.json", config)
    path = root / "responses.jsonl"
    if not path.exists() and seeded:
        path.write_text("".join(json.dumps(row) + "\n" for row in seeded))
    attempts = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    responses = {r["key"]: r for r in attempts if not r.get("failure")}
    pending = [v for k, v in unique.items() if k not in responses]
    if len(pending) > max_requests:
        raise ValueError(f"Need {len(pending)} calls, exceeding max_requests")

    def request(item):
        case, state, agent = item
        model = predictor()
        start = time.perf_counter()
        row = {"key": case["key"], "context": case["context"]}
        try:
            f = model.predict(state, agent)
            row.update(
                reuse=f.reuse_probability,
                next=f.next_probability,
                continues=f.continue_probability,
                failure=None,
            )
        except ValueError as exc:
            row["failure"] = str(exc)
        row.update(latency_s=time.perf_counter() - start, telemetry=model.records[-1])
        return row

    print(f"Collecting {len(pending)} {backend}/{mode} contexts", flush=True)
    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool,
        path.open("a") as stream,
    ):
        iterator = iter(pending)
        futures = {
            pool.submit(request, item)
            for item in [next(iterator, None) for _ in range(workers)]
            if item is not None
        }
        n, failures = 0, 0
        while futures:
            finished, futures = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in finished:
                row = future.result()
                n += 1
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                attempts.append(row)
                failures += bool(row["failure"])
                if not row["failure"]:
                    responses[row["key"]] = row
                if n % 25 == 0:
                    print(f"{backend}: {n}/{len(pending)} saved", flush=True)
                item = next(iterator, None) if failures < 2 else None
                if item is not None:
                    futures.add(pool.submit(request, item))
    bank = {"config": config, "responses": responses, "complete": set(responses) == set(unique)}
    bank["sha256"] = digest(bank)
    write_json(root / "bank.json", bank)
    report = {
        "complete": bank["complete"],
        "unique_contexts": len(unique),
        "summary": summarize_inference(r["telemetry"] for r in attempts),
        "seeded_responses": sum("seed_bank_sha256" in r for r in attempts),
        "new_collection_summary": summarize_inference(
            r["telemetry"] for r in attempts if "seed_bank_sha256" not in r
        ),
        "calibration": {},
    }
    for group, ids in (
        ("development", dev),
        ("evaluation", {t["task_id"] for t in data["tapes"]} - dev),
    ):
        report["calibration"][group] = {}
        for field in ("reuse", "next", "continues"):
            pairs = [
                (responses[c["key"]][field], lab[field])
                for c, _, _, lab in rows
                if c["task_id"] in ids
                and c["key"] in responses
                and lab[field] is not None
                and (field != "reuse" or lab["next"])
                and (field != "continues" or lab["next"])
            ]
            report["calibration"][group][field] = calibration(pairs)
    write_json(root / "report.json", report)
    return report


class TapeBankPredictor:
    """Exact finite bank; runtime contains neither task labels nor network clients.

    Parallel decision mode charges the slowest observed forecast; serial charges
    their sum. Every logical call is costed, even when its frozen input repeats.
    """

    measured_overhead = False

    def __init__(self, history, path, *, parallel=True, latency_scale=1.0):
        nonnegative(latency_scale, "latency scale")
        bank = json.loads(Path(path).read_text())
        if bank.get("sha256") != digest({k: v for k, v in bank.items() if k != "sha256"}):
            raise ValueError("Forecast bank checksum mismatch")
        if not bank["complete"]:
            raise ValueError("Incomplete forecast bank")
        self.history, self.responses = history, bank["responses"]
        if "development" in bank["config"] and set(bank["config"]["development"]) != set(
            history.training_ids
        ):
            raise ValueError("Forecast/history development split mismatch")
        self.mode = bank["config"]["mode"]
        self.parallel, self.latency_scale = parallel, latency_scale
        self.decision_overhead_s = self.logical_cost_usd = self.logical_calls = 0
        self.unknown_cost_calls = 0
        for key, r in self.responses.items():
            if key != digest(r["context"]) or r["failure"]:
                raise ValueError("Invalid forecast context")
            Forecast(r["reuse"], r["next"], (0,), (0,), r["continues"])
            nonnegative(r["latency_s"], "forecast latency")

    def begin_decision(self):
        self.decision_overhead_s = 0.0

    def predict(self, state, agent):
        frozen = replace(agent, phase_since_s=state.now_s)
        context = bounded_context(state, frozen, self.mode)
        if "elapsed_s" in context:
            context["elapsed_s"] = 0  # identical declared phase-entry JSON, including numeric type
        key = digest(context)
        if key not in self.responses:
            raise ValueError("Uncovered exact predictor context")
        row = self.responses[key]
        latency = row["latency_s"] * self.latency_scale
        self.decision_overhead_s = (
            max(self.decision_overhead_s, latency)
            if self.parallel
            else self.decision_overhead_s + latency
        )
        self.logical_calls += 1
        cost = row["telemetry"].get("cost_usd")
        if cost is None:
            self.unknown_cost_calls += 1
        else:
            self.logical_cost_usd += cost
        return replace(
            self.history.predict(state, agent),
            reuse_probability=row["reuse"],
            next_probability=row["next"],
            continue_probability=row["continues"],
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--backend", choices=("jev", "kev", "kev-space", "mock"), default="jev")
    p.add_argument("--mode", default="progress")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--development-count", type=int, default=20)
    p.add_argument("--max-requests", type=int, default=2000)
    p.add_argument("--split", choices=("all", "development", "evaluation"), default="all")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-candidate-age", type=int, default=0)
    p.add_argument("--seed-bank", type=Path)
    a = p.parse_args()
    print(
        json.dumps(
            collect(
                a.dataset,
                a.output,
                backend=a.backend,
                mode=a.mode,
                workers=a.workers,
                development_count=a.development_count,
                max_requests=a.max_requests,
                split=a.split,
                resume=a.resume,
                max_candidate_age=a.max_candidate_age,
                seed_bank=a.seed_bank,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
