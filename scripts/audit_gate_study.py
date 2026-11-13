"""Check saved evidence and reproduce the independent no-quota arithmetic."""

import argparse
import hashlib
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.artifacts import write_json
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset
from quota_spec.perfect_gate import exact_gates
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.speculation_audit import unlimited_reference


def audit(output):
    tapes = load_dataset("results/hotpot-dataset-50")["tapes"]
    residuals, lifetimes = [], []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network in audit")):
        for tape in tapes:
            for enabled, policy in [(False, NoSpeculation()), (True, CurrentCapacity())]:
                reference = unlimited_reference(tape, enabled)
                actual = FrozenReplay([tape], 10000, 1).run(policy)["metrics"]
                residuals.append(abs(reference["completion_s"] - actual["mean_completion_s"]))
                assert reference["cache_hits"] == actual["cache_hits"]
            for age in [0, 1, 999]:
                options = {"max_candidate_age": age, "suppress_known_calls": age > 0}
                base = FrozenReplay([tape], 10000, 1, **options).run(NoSpeculation())["metrics"]
                ungated = FrozenReplay([tape], 10000, 1, **options).run(CurrentCapacity())[
                    "metrics"
                ]
                oracle = exact_gates([tape], 10000, 1, agents=1, **options)
                lifetimes.append(
                    {
                        "task_id": tape["task_id"],
                        "max_candidate_age": age,
                        "none_s": base["mean_completion_s"],
                        "ungated_s": ungated["mean_completion_s"],
                        "oracle_bits": oracle["candidate_bits"],
                        "ideal_post_s": oracle["winners"]["post_latency"]["metrics"][
                            "mean_completion_s"
                        ],
                        "ideal_pipeline_s": oracle["winners"]["pipeline_latency"]["metrics"][
                            "mean_completion_s"
                        ],
                    }
                )
        assert max(residuals) < 1e-8
        ordered = list(tapes[20:])
        random.Random(248).shuffle(ordered)
        for name, forced, windows in [
            ("none", None, None),
            ("ideal_post", frozenset({("6031", 2, 1)}), None),
            ("ideal_pipeline", frozenset({("6031", 2, 1)}), frozenset({("6031", 2)})),
        ]:
            run = FrozenReplay(ordered, 6, 60, max_active_agents=2).run(
                NoSpeculation(), forced=forced, generation_windows=windows
            )
            validate(run, ordered, 6, 60, 2)
            write_json(output / ("example-6-per-60s-2-agents-" + name + ".json"), run)
    write_json(output / "lifetime-noquota-all50.json", lifetimes)
    preserved = {}
    for inventory in [
        "results/hotpot-capture-50-bundle-manifest.json",
        "results/jev-study-bundle-inventory.json",
        "results/jev-async-bundle-inventory.json",
    ]:
        entries = json.loads(Path(inventory).read_text())["files"]
        checked = 0
        for name, record in entries.items():
            if not name.startswith(("results/", "data/")):
                continue
            path = Path(name)
            assert path.is_file(), name
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], name
            checked += 1
        preserved[inventory] = checked
    write_json(
        output / "arithmetic-and-evidence-audit.json",
        {
            "independent_serial_recurrence_checks": len(residuals),
            "max_completion_residual_s": max(residuals),
            "all_cache_hit_counts_match": True,
            "lifetime_task_cases": len(lifetimes),
            "representative_full_event_schedules": 3,
            "prior_evidence_files_unchanged": preserved,
            "new_inference_calls": 0,
            "network_blocked": True,
        },
    )
    print("Arithmetic and preserved-evidence audit passed", preserved)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    audit(parser.parse_args().output)
