"""Exploratory replay control: the reserve instruction without an LLM gate."""

import argparse
import gzip
import json
import random
import socket
from pathlib import Path
from unittest.mock import patch

from quota_spec.artifacts import write_json
from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset, scheduling_options
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.quota import FixedWindowQuota


class ObservedHeadroom:
    def admit(self, state):
        snapshot = state.snapshot
        delay = (
            FixedWindowQuota(snapshot.capacity, snapshot.window_s).next_refill(state.now_s)
            - state.now_s
        )
        reserve = len(snapshot.agents) - 1 if delay > 1 else 0
        return state.queued_required == 0 and state.quota_remaining > reserve


def explore(output):
    if output.exists():
        raise ValueError("Choose fresh output")
    protocol = json.loads(
        Path("results/quota-win-2026-11-15-replication-protocol.json").read_text()
    )
    ids = set(map(str, protocol["evaluation_indices"]))
    tapes = [
        t
        for t in load_dataset("results/quota-win-2026-11-15-replication-cohort")["tapes"]
        if t["task_id"] in ids
    ]
    output.mkdir(parents=True)
    write_json(
        output / "config.json",
        {
            "exploratory": True,
            "evaluation_tasks": len(tapes),
            "seeds": list(range(248, 258)),
            "rule": "Reserve one call per other active worker when refill is more than 1s away",
            "scope": "Controller ablation with saved quota-unaware candidates; does not measure the quota-aware language planner",
        },
    )
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        for capacity, window in [(12, 3), (8, 5), (24, 1)]:
            for seed in range(248, 258):
                selected = list(tapes)
                random.Random(seed).shuffle(selected)
                for name, factory in [
                    ("none", NoSpeculation),
                    ("all", CurrentCapacity),
                    ("headroom", ObservedHeadroom),
                ]:
                    run = FrozenReplay(
                        selected,
                        capacity,
                        window,
                        max_active_agents=4,
                        max_generation_step=4 if name == "headroom" else None,
                        max_candidate_age=7,
                        suppress_known_calls=True,
                        revalidate_reset=True,
                        **scheduling_options("overlap"),
                    ).run(factory())
                    validate(run, selected, capacity, window, 4)
                    filename = f"{capacity}-{window}-{seed}-{name}.json.gz"
                    (output / filename).write_bytes(gzip.compress(json.dumps(run).encode()))
                    rows.append(
                        {
                            "capacity": capacity,
                            "window_s": window,
                            "seed": seed,
                            "policy": name,
                            "schedule": filename,
                            **{
                                k: v
                                for k, v in run["metrics"].items()
                                if k
                                in [
                                    "mean_completion_s",
                                    "resource_makespan_s",
                                    "unused_speculative_calls",
                                    "cache_hits",
                                ]
                            },
                        }
                    )
    write_json(output / "rows.json", rows)
    write_json(
        output / "validation.json",
        {"pass": True, "runs": len(rows), "network_blocked": True, "answers_preserved": True},
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    explore(p.parse_args().output)
