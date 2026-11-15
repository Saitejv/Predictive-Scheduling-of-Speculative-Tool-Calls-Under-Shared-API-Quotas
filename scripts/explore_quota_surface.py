"""Development-only quota/refill exploration on the retained 20-question split.

This reproduction uses fresh outputs and must not be treated as confirmatory.
"""

import argparse
import itertools
import json
import time
from pathlib import Path

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.artifacts import append_json, write_json
from quota_spec.forecast_study import TimedBank, TimedHistory, validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset, scheduling_options
from quota_spec.matched_context_study import CalibratedBank
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.probability_calibration import ProbabilityCalibration

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = args.output
root.mkdir(parents=True, exist_ok=False)
tapes = load_dataset("results/hotpot-dataset-50")["tapes"][:20]
hist = TimedHistory(tapes)
bank = "results/multi-agent-context-2026-11-15-episode-bank/bank.json"
cal = ProbabilityCalibration(
    json.loads(Path("results/multi-agent-context-2026-11-15-calibration.json").read_text())
)
options = {
    **scheduling_options("overlap"),
    "max_candidate_age": 7,
    "suppress_known_calls": True,
    "revalidate_reset": True,
}
write_json(
    root / "config.json",
    {
        "development_ids": [t["task_id"] for t in tapes],
        "settings": {
            "agents": [2, 4, 8],
            "capacities": [2, 3, 4, 6, 8, 12, 16, 24],
            "windows": [0.5, 1, 2, 3, 5, 10, 20, 30],
        },
        "samples": 8,
        "seed": 248,
        "note": "DEVELOPMENT ONLY; no settings selected on evaluation tasks; native timing",
    },
)
rows = []
start = time.perf_counter()
for agents, capacity, window in itertools.product(
    [2, 4, 8], [2, 3, 4, 6, 8, 12, 16, 24], [0.5, 1, 2, 3, 5, 10, 20, 30]
):
    for name in ["none", "all", "raw", "cal"]:
        pred = None
        if name == "none":
            policy = NoSpeculation()
        elif name == "all":
            policy = CurrentCapacity()
        else:
            pred = TimedBank(hist, bank) if name == "raw" else CalibratedBank(hist, bank, cal)
            policy = PredictiveAdmission(
                pred, AdmissionConfig(samples=8, seed=248, nonblocking=True)
            )
        run = FrozenReplay(tapes, capacity, window, max_active_agents=agents, **options).run(policy)
        validate(run, tapes, capacity, window, agents)
        row = {
            "agents": agents,
            "capacity": capacity,
            "window_s": window,
            "policy": name,
            **{k: v for k, v in run["metrics"].items() if not isinstance(v, (list, dict))},
        }
        rows.append(row)
        append_json(root / "rows.jsonl", row)
    if len(rows) % 64 == 0:
        print(len(rows), "rows", round(time.perf_counter() - start, 1), "s", flush=True)
write_json(root / "rows.json", rows)
wins = []
for agents, capacity, window in itertools.product(
    [2, 4, 8], [2, 3, 4, 6, 8, 12, 16, 24], [0.5, 1, 2, 3, 5, 10, 20, 30]
):
    by = {
        r["policy"]: r
        for r in rows
        if (r["agents"], r["capacity"], r["window_s"]) == (agents, capacity, window)
    }
    for method in ["raw", "cal"]:
        r = by[method]
        mean = min(by["none"]["mean_completion_s"], by["all"]["mean_completion_s"])
        wall = min(by["none"]["resource_makespan_s"], by["all"]["resource_makespan_s"])
        wins.append(
            {
                "agents": agents,
                "capacity": capacity,
                "window_s": window,
                "method": method,
                "mean_win_percent": 100 * (1 - r["mean_completion_s"] / mean),
                "resource_win_percent": 100 * (1 - r["resource_makespan_s"] / wall),
                "hits": r["cache_hits"],
            }
        )
write_json(
    root / "ranking.json",
    sorted(
        wins,
        key=lambda r: (
            min(r["mean_win_percent"], r["resource_win_percent"]),
            r["mean_win_percent"],
        ),
        reverse=True,
    ),
)
print(json.dumps(sorted(wins, key=lambda r: r["mean_win_percent"], reverse=True)[:20], indent=2))
