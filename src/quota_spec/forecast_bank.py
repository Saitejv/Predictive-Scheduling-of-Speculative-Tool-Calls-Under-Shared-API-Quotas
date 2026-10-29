"""Freeze model forecasts from observed states, then replay without further API calls.

A bank intentionally fixes elapsed time to zero at each phase entry. This isolates
predictor/context quality and the cross-agent admission objective from changing
model responses. Live adaptive inference remains available through cli/gateway.
"""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from .adapters import JevPredictor, KevPredictor, MockSystemOnePredictor
from .collect_qa import write_json
from .models import AgentState, Call, Observation, Snapshot, load_tasks, nonnegative
from .prediction import Forecast, HistoryPredictor, bounded_context, calibration
from .search import sha256_json
from .workload import dump_tasks

CONTEXTS = ("task", "history", "progress", "no_history", "no_progress")


def bank_cases(tasks):
    """Yield inputs separately from labels. No current/future results enter inputs."""
    for task in tasks:
        history = []
        excerpt = ""
        for index in range(len(task.steps) + 1):
            step = task.steps[index] if index < len(task.steps) else None
            candidate = step.candidate if step else task.final_candidate
            agent = AgentState(
                task.task_id,
                0,
                index,
                "thinking",
                0,
                task_context=task.task_context,
                history=tuple(history[-8:]),
                result_excerpt=excerpt,
            )
            for own in (False, True):
                if own and candidate is None:
                    continue
                state = Observation(
                    0,
                    task.task_id if own else "__other_agent__",
                    index,
                    candidate if own else Call.search("[other agent candidate omitted]"),
                    3,
                    0,
                    Snapshot(3, 1, (agent,)),
                )
                labels = {
                    "reuse": bool(step and candidate == step.required) if own else None,
                    "next": step is not None,
                    "continues": index + 1 < len(task.steps),
                }
                yield (task.task_id, index, "thinking", own), state, agent, labels
            if step:
                history.append(step.required)
                for phase in ("queued", "running"):
                    pending = replace(agent, phase=phase, history=tuple(history[-8:]))
                    state = Observation(
                        0,
                        "__other_agent__",
                        index,
                        Call.search("[other agent candidate omitted]"),
                        3,
                        0,
                        Snapshot(3, 1, (pending,)),
                    )
                    yield (
                        (task.task_id, index, phase, False),
                        state,
                        pending,
                        {
                            "reuse": None,
                            "next": index + 1 < len(task.steps),
                            "continues": index + 2 < len(task.steps),
                        },
                    )
                excerpt = step.result_excerpt


def case_key(task_id, index, phase, own):
    return json.dumps([task_id, index, phase, own])


def prepare(
    data,
    output,
    *,
    backends=("mock",),
    contexts=CONTEXTS,
    resume=False,
    execute=False,
    max_requests=10000,
    predictor_options=None,
):
    if not backends or any(b not in ("mock", "jev", "kev") for b in backends):
        raise ValueError("Choose mock, jev, and/or kev")
    if not contexts or any(c not in CONTEXTS for c in contexts):
        raise ValueError("Unknown context")
    if len(set(backends)) != len(backends) or len(set(contexts)) != len(contexts):
        raise ValueError("Backends and contexts must be unique")
    from .models import positive_int

    positive_int(max_requests, "max_requests")
    development = load_tasks(json.loads((data / "development.json").read_text()))
    evaluation = load_tasks(json.loads((data / "evaluation.json").read_text()))
    if not evaluation or any(
        len({t.task_id for t in rows}) != len(rows) for rows in (development, evaluation)
    ):
        raise ValueError("Forecast splits must be nonempty with unique task IDs")
    if {t.task_id for t in development} & {t.task_id for t in evaluation}:
        raise ValueError("Development/evaluation overlap")
    history = HistoryPredictor.fit(development)
    cases = list(bank_cases(evaluation))
    unique = {
        context: len(
            {sha256_json(bounded_context(state, agent, context)) for _, state, agent, _ in cases}
        )
        for context in contexts
    }
    requests = sum(unique.values()) * len(backends)
    plan = {
        "backends": list(backends),
        "contexts": list(contexts),
        "cases": len(cases),
        "maximum_new_requests": requests,
        "unique_inputs_per_backend": unique,
        "external_inference": execute and any(b != "mock" for b in backends),
        "protocol": "Frozen phase-entry contexts; elapsed=0; development-only timing distributions",
    }
    if not execute:
        return plan
    if requests > max_requests:
        raise ValueError(
            f"Plan needs up to {requests} requests, exceeding --max-requests {max_requests}"
        )
    # Validate every selected provider before starting a potentially paid batch.
    constructors = {"jev": JevPredictor, "kev": KevPredictor, "mock": MockSystemOnePredictor}
    predictors = {
        (b, c): constructors[b](history, context=c, **(predictor_options or {}))
        for b in backends
        for c in contexts
    }
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError("Output is not empty; choose a new directory or use --resume")
    paths = []
    from .experiments import source_hashes

    prepared = []
    # Check every saved bank before issuing a request or changing any artifact.
    for (backend, context), predictor in predictors.items():
        path = output / f"{backend}-{context}.json"
        config = {
            "version": 1,
            "backend": backend,
            "context": context,
            "model": predictor.model,
            "model_revision": predictor.model_revision,
            "base_url": predictor.base_url,
            "timeout_s": predictor.timeout_s,
            "decision_timeout_s": predictor.decision_timeout_s,
            "source_sha256": source_hashes(),
            "input_price": predictor.input_price,
            "output_price": predictor.output_price,
            "development_sha256": sha256_json(dump_tasks(development)),
            "evaluation_sha256": sha256_json(dump_tasks(evaluation)),
        }
        bank = {"config": config, "responses": {}, "cases": {}, "complete": False}
        if resume and path.exists():
            bank = json.loads(path.read_text())
            if bank["config"] != config:
                raise ValueError("Bank resume configuration/input mismatch")
            if bank.get("sha256") != sha256_json({k: v for k, v in bank.items() if k != "sha256"}):
                raise ValueError("Forecast bank checksum mismatch")
        prepared.append((backend, context, predictor, path, bank))
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "plan.json", plan)

    def checkpoint(path, bank):
        bank["sha256"] = sha256_json({k: v for k, v in bank.items() if k != "sha256"})
        write_json(path, bank)

    for backend, context, predictor, path, bank in prepared:
        for identity, state, agent, labels in cases:
            key = sha256_json(bounded_context(state, agent, context))
            if key not in bank["responses"] or bank["responses"][key].get("failure"):
                if key in bank["responses"]:
                    bank.setdefault("failed_attempts", []).append(bank["responses"][key])
                started = time.perf_counter()
                try:
                    forecast = predictor.predict(state, agent)
                    response = {
                        "reuse": forecast.reuse_probability,
                        "next": forecast.next_probability,
                        "continues": forecast.continue_probability,
                        "failure": None,
                    }
                except ValueError:
                    response = {"failure": "prediction_failed"}
                response["latency_s"] = time.perf_counter() - started
                response["telemetry"] = predictor.records[-1]
                response["input"] = bounded_context(state, agent, context)
                bank["responses"][key] = response
                checkpoint(path, bank)
                if response["failure"]:
                    raise ValueError(
                        f"{backend}/{context} failed; telemetry saved. Fix access and resume"
                    )
            bank["cases"][case_key(*identity)] = {"response": key, "labels": labels}
        bank["calibration"] = {}
        for field in ("reuse", "next", "continues"):
            bank["calibration"][field] = calibration(
                [
                    (
                        bank["responses"][row["response"]][field]
                        * (bank["responses"][row["response"]]["next"] if field == "reuse" else 1),
                        row["labels"][field],
                    )
                    for row in bank["cases"].values()
                    if row["labels"][field] is not None
                    and (field != "continues" or row["labels"]["next"])
                ]
            )
        bank["complete"] = True
        checkpoint(path, bank)
        paths.append(str(path))
        print(f"Frozen {backend}/{context}: {len(bank['responses'])} unique inputs", flush=True)
    return {**plan, "banks": paths}


class BankPredictor:
    """Fixed probabilities, observed runtime timing; replay charges saved inference time."""

    measured_overhead = False

    def __init__(self, history, path, evaluation):
        self.history = history
        self.bank = json.loads(Path(path).read_text())
        if not self.bank.get("complete"):
            raise ValueError("Forecast bank is incomplete")
        if "sha256" in self.bank and self.bank["sha256"] != sha256_json(
            {k: v for k, v in self.bank.items() if k != "sha256"}
        ):
            raise ValueError("Forecast bank checksum mismatch")
        config = self.bank["config"]
        expected_cases = {case_key(*identity) for identity, _, _, _ in bank_cases(evaluation)}
        if set(self.bank["cases"]) != expected_cases:
            raise ValueError("Forecast bank has missing or unexpected cases")
        for row in self.bank["cases"].values():
            response = self.bank["responses"].get(row["response"])
            if response is None or response.get("failure"):
                raise ValueError("Forecast bank has missing or failed responses")
            nonnegative(response["latency_s"], "forecast latency")
            Forecast(response["reuse"], response["next"], (0,), (0,), response["continues"])
        self.digest = sha256_json(self.bank)
        # Evaluation labels remain in the offline artifact only, never the runtime predictor.
        self.calibration = self.bank.pop("calibration", {})
        self.bank["cases"] = {
            key: {"response": row["response"]} for key, row in self.bank["cases"].items()
        }
        if config["evaluation_sha256"] != sha256_json(dump_tasks(evaluation)):
            raise ValueError("Forecast bank does not match evaluation traces")
        self.name = config["backend"] + "_" + config["context"]
        self.decision_overhead_s = 0.0
        self.mock = config["backend"] == "mock"
        self.decision_timeout_s = config.get("decision_timeout_s", 5.0)
        nonnegative(self.decision_timeout_s, "decision timeout")
        if not 0 < self.decision_timeout_s <= 120:
            raise ValueError("Invalid forecast decision timeout")

    def begin_decision(self):
        self.decision_overhead_s = 0.0

    def predict(self, state, agent):
        key = case_key(
            agent.task_id, agent.completed_calls, agent.phase, agent.task_id == state.task_id
        )
        row = self.bank["cases"].get(key)
        if row is None:
            raise ValueError("No frozen forecast for this observed state")
        response = self.bank["responses"][row["response"]]
        if response["failure"]:
            raise ValueError("Frozen inference failed")
        if not self.mock:
            charged = self.decision_overhead_s + response["latency_s"]
            self.decision_overhead_s = min(charged, self.decision_timeout_s)
            if charged > self.decision_timeout_s:
                raise TimeoutError("Frozen inference exceeds the total decision budget")
        return replace(
            self.history.predict(state, agent),
            reuse_probability=response["reuse"],
            next_probability=response["next"],
            continue_probability=response["continues"],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("results/forecasts"))
    parser.add_argument("--backends", nargs="+", choices=("mock", "jev", "kev"), default=["mock"])
    parser.add_argument("--contexts", nargs="+", choices=CONTEXTS, default=list(CONTEXTS))
    parser.add_argument(
        "--execute", action="store_true", help="Perform explicitly selected inference"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-requests", type=int, default=10000)
    parser.add_argument("--timeout-s", type=float, default=2)
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    args = parser.parse_args()
    try:
        result = prepare(
            args.data,
            args.output,
            backends=args.backends,
            contexts=args.contexts,
            resume=args.resume,
            execute=args.execute,
            max_requests=args.max_requests,
            predictor_options={
                "timeout_s": args.timeout_s,
                "input_usd_per_million": args.input_usd_per_million,
                "output_usd_per_million": args.output_usd_per_million,
            },
        )
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
