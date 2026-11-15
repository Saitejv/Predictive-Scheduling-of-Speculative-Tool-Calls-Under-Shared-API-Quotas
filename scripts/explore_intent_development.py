"""Compare intent augmentation on the original development questions only."""

import argparse
import json
import random
from pathlib import Path

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.artifacts import append_json, write_json
from quota_spec.forecast_study import TimedHistory, validate
from quota_spec.frozen_replay import FrozenReplay, load_dataset, scheduling_options
from quota_spec.matched_context_study import CalibratedBank
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.probability_calibration import ProbabilityCalibration

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
tapes = load_dataset("results/hotpot-dataset-50")["tapes"][:20]
history = TimedHistory(tapes)
inputs = {
    "progress": (
        "results/multi-agent-context-2026-11-15-episode-bank/bank.json",
        "results/multi-agent-context-2026-11-15-calibration.json",
    ),
    "intent": (
        "results/quota-win-2026-11-15-intent-development/bank.json",
        "results/quota-win-2026-11-15-intent-calibration.json",
    ),
}
rows = []
for setting in [(4, 16, 5), (2, 8, 5), (4, 8, 2)]:
    for seed in range(248, 258):
        ordered = list(tapes)
        random.Random(seed).shuffle(ordered)
        for name in ("none", "all", "progress", "intent"):
            if name in inputs:
                bank, calibration = inputs[name]
                cal = ProbabilityCalibration(json.loads(Path(calibration).read_text()))
                rule = PredictiveAdmission(
                    CalibratedBank(history, bank, cal),
                    AdmissionConfig(samples=32, seed=seed, nonblocking=True),
                )
            else:
                rule = NoSpeculation() if name == "none" else CurrentCapacity()
            count, capacity, window = setting
            run = FrozenReplay(
                ordered,
                capacity,
                window,
                max_active_agents=count,
                max_candidate_age=7,
                suppress_known_calls=True,
                revalidate_reset=True,
                **scheduling_options("overlap"),
            ).run(rule)
            validate(run, ordered, capacity, window, count)
            row = {
                "agents": count,
                "capacity": capacity,
                "window_s": window,
                "seed": seed,
                "policy": name,
                **run["metrics"],
            }
            rows.append(row)
            append_json(a.output / "rows.jsonl", row)
    print("Development intent comparison", setting, "done", flush=True)
write_json(a.output / "rows.json", rows)
