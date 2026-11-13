"""Prepare label-blind frozen cases for the existing history/Jev/Kev interface.

This command does not call predictors. Contexts deliberately use phase-entry
elapsed=0, matching the existing forecast-bank approximation.
"""

import argparse
import hashlib
import json
from pathlib import Path

from .artifacts import write_json
from .frozen_replay import load_dataset
from .models import AgentState, Call, Observation, Snapshot
from .prediction import bounded_context

CONTEXTS = ("task", "history", "progress", "no_history", "no_progress")


def as_call(action):
    boundary = action.index("[")
    tool, value = action[:boundary].lower(), action[boundary + 1 : -1]
    return Call.search(value) if tool == "search" else Call(tool, json.dumps({"value": value}))


def prepare(dataset, output, development_count=20):
    root, output = Path(dataset), Path(output)
    if output.exists():
        raise ValueError("Choose a fresh predictor-input directory")
    data = load_dataset(root)
    tapes = data["tapes"]
    if not 1 <= development_count < len(tapes):
        raise ValueError("Provide nonempty disjoint development and evaluation sets")
    dev = {t["task_id"] for t in tapes[:development_count]}
    contexts, references = {}, []

    def add(case_id, state, agent):
        for mode in CONTEXTS:
            context = bounded_context(state, agent, mode)
            identity = hashlib.sha256(
                json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            contexts[identity] = {"context_sha256": identity, "mode": mode, "context": context}
            references.append(
                {
                    "case_id": case_id,
                    "task_id": agent.task_id,
                    "split": "development" if agent.task_id in dev else "evaluation",
                    "context_mode": mode,
                    "context_sha256": identity,
                }
            )

    for tape in tapes:
        tid, history = tape["task_id"], []
        for index in range(len(tape["steps"]) + 1):
            row = tape["steps"][index] if index < len(tape["steps"]) else None
            excerpt = tape["steps"][index - 1].get("observed_excerpt", "") if index else ""
            for phase in ("thinking", "queued", "running") if row else ("thinking",):
                observed_history = history + (
                    [as_call(row["action"])] if phase != "thinking" else []
                )
                agent = AgentState(
                    tid,
                    0,
                    index,
                    phase,
                    0,
                    task_context=tape["question"],
                    history=tuple(observed_history[-8:]),
                    result_excerpt=excerpt,
                )
                state = Observation(
                    0,
                    "__other_agent__",
                    index,
                    Call.search("[other candidate omitted]"),
                    3,
                    0,
                    Snapshot(3, 10, (agent,)),
                )
                add(f"{tid}:{index}:{phase}:demand", state, agent)
            if row:
                history.append(as_call(row["action"]))
    for case in json.loads((root / "forecast-cases.json").read_text()):
        agent = AgentState(
            case["task_id"],
            0,
            case["completed_steps"],
            case["phase"],
            0,
            task_context=case["question"],
            history=tuple(as_call(a) for a in case["history"][-8:]),
            result_excerpt=case["previous_result_excerpt"] or "",
        )
        state = Observation(
            0,
            case["task_id"],
            case["completed_steps"],
            as_call(case["candidate"]),
            3,
            0,
            Snapshot(3, 10, (agent,)),
        )
        add(case["id"] + ":reuse", state, agent)
    output.mkdir(parents=True)
    write_json(output / "contexts.json", list(contexts.values()))
    write_json(output / "case-index.json", references)
    write_json(
        output / "splits.json",
        {
            "development": [t["task_id"] for t in tapes if t["task_id"] in dev],
            "evaluation": [t["task_id"] for t in tapes if t["task_id"] not in dev],
            "status": "Exploratory pilot split, not fresh held-out confirmation",
        },
    )
    result = {
        "version": 1,
        "questions": len(tapes),
        "unique_contexts": len(contexts),
        "case_references": len(references),
        "context_modes": list(CONTEXTS),
        "source_manifest_sha256": hashlib.sha256(
            (root / "dataset-manifest.json").read_bytes()
        ).hexdigest(),
        "predictor_calls_made": 0,
        "development_count": len(dev),
        "evaluation_count": len(tapes) - len(dev),
        "next_integration": [
            "Use existing JevPredictor/KevPredictor.predict(state, agent) interface on these exact contexts",
            "Freeze Forecast outputs with exact context/model/config hashes plus measured cost and latency",
            "History timing distributions must use development questions only; reuse labels are separate",
            "Compare full and own-agent PredictiveAdmission using the same forecast bank",
            "Extend coverage or explicitly retain phase-entry elapsed=0; never fetch missing contexts during replay",
        ],
    }
    write_json(output / "PLAN.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--development-count", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(prepare(args.dataset, args.output, args.development_count), indent=2))


if __name__ == "__main__":
    main()
