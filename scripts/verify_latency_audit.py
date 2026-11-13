"""Evidence integrity, original-engine compatibility, and compact-policy parity."""

import argparse
import hashlib
import importlib.util
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.artifacts import write_json
from quota_spec.frozen_replay import FrozenReplay, load_dataset
from quota_spec.latency_study import CompactTapeAdmission, change_durations, replay
from quota_spec.policies import CurrentCapacity, FixedReserve, NoSpeculation
from quota_spec.tape_forecasts import TapeBankPredictor, TapeHistory


def verify(root):
    before = json.loads((root / "protected-before.json").read_text())
    changed = [
        name
        for name, expected in before.items()
        if not Path(name).is_file()
        or hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected
    ]
    assert not changed, changed
    write_json(
        root / "protected-verification.json",
        {"protected_files": len(before), "changed_files": changed, "all_unchanged": True},
    )
    spec = importlib.util.spec_from_file_location(
        "quota_spec._original_replay", root / "source-before/src/quota_spec/frozen_replay.py"
    )
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    source = load_dataset("results/hotpot-dataset-50")["tapes"]
    comparisons = 0
    compact = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for scale in [1, 10]:
            tapes = change_durations(source[20:], scale=scale)
            for cap, w in [(10000, 1), (3, 10), (12, 30), (6, 60)]:
                for workers in [1, 2, 4, 8]:
                    for release in [False, True]:
                        for age in [0, 1]:
                            for constructor in [
                                NoSpeculation,
                                CurrentCapacity,
                                lambda: FixedReserve(1),
                            ]:
                                kwargs = {
                                    "max_active_agents": workers,
                                    "release_on_answer": release,
                                    "max_candidate_age": age,
                                    "suppress_known_calls": bool(age),
                                }
                                old = original.FrozenReplay(tapes, cap, w, **kwargs).run(
                                    constructor()
                                )
                                new = FrozenReplay(tapes, cap, w, **kwargs).run(constructor())
                                assert old == new, (scale, cap, w, workers, release, age)
                                comparisons += 1
            predictor = TapeBankPredictor(
                TapeHistory(change_durations(source[:20], scale=scale)),
                "results/hotpot-jev-persistent-progress-50/bank.json",
            )
            random.Random(248).shuffle(tapes)
            for cap, w in [(12, 30), (6, 60)]:
                for workers in [2, 8]:
                    kwargs = {"capacity": cap, "window": w, "workers": workers, "release": True}
                    old = replay(
                        tapes,
                        policy=PredictiveAdmission(
                            predictor,
                            AdmissionConfig(
                                samples=16, horizon_s=max(30, 2 * w), seed=248, nonblocking=True
                            ),
                        ),
                        **kwargs,
                    )
                    new = replay(
                        tapes,
                        policy=CompactTapeAdmission(
                            predictor,
                            AdmissionConfig(
                                samples=16, horizon_s=max(30, 2 * w), seed=248, nonblocking=True
                            ),
                        ),
                        **kwargs,
                    )
                    for run in [old, new]:
                        for d in run["decisions"]:
                            d["forecast"].pop("decision_wall_s", None)
                    assert old == new, (scale, cap, w, workers)
                    compact.append(
                        {
                            "scale": scale,
                            "capacity": cap,
                            "window_s": w,
                            "workers": workers,
                            "identical": True,
                        }
                    )
    repeats = []
    for tape in source:
        seen = {}
        for row in tape["steps"]:
            if row["tool"] != "search":
                continue
            if row["query"] in seen:
                repeats.append(
                    {
                        "task_id": tape["task_id"],
                        "query": row["query"],
                        "identical_observed_text": row.get("observed_excerpt")
                        == seen[row["query"]].get("observed_excerpt"),
                    }
                )
            seen[row["query"]] = row
    assert all(r["identical_observed_text"] for r in repeats)
    write_json(
        root / "source-equivalence.json",
        {
            "compared_schedules": comparisons,
            "all_metrics_events_decisions_identical": True,
            "final_replay_sha256": hashlib.sha256(
                Path("src/quota_spec/frozen_replay.py").read_bytes()
            ).hexdigest(),
            "new_model_calls": 0,
        },
    )
    write_json(
        root / "compact-policy-parity.json",
        {
            "comparisons": compact,
            "all_metrics_events_forecast_decisions_identical": True,
            "ignored_field": "diagnostic CPU wall time only; declared 1 ms scheduler budget unchanged",
        },
    )
    write_json(root / "repeated-search-content.json", repeats)
    return {
        "protected_files": len(before),
        "source_comparisons": comparisons,
        "compact_policy_comparisons": len(compact),
        "repeated_searches": len(repeats),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    a = p.parse_args()
    print(json.dumps(verify(a.root), indent=2), flush=True)
