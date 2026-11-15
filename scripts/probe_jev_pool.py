"""Paid paired transport probe on development contexts only."""

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from quota_spec.adapters import JevPredictor
from quota_spec.artifacts import append_json, write_json
from quota_spec.forecast_study import TimedHistory
from quota_spec.frozen_replay import load_dataset
from quota_spec.pooled_jev import JevHTTPPool, PooledJevPredictor
from quota_spec.tape_forecasts import cases

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
tapes = load_dataset("results/quota-win-2026-11-15-native-bank")["tapes"][:20]
history = TimedHistory(tapes)
unique = {c["key"]: (c, s, agent) for c, s, agent, _ in cases(tapes, max_candidate_age=7)}
selected = random.Random(17).sample(list(unique.values()), 32)
records = []
started = time.perf_counter()
with JevHTTPPool(connections=4) as pool:
    startup = time.perf_counter() - started
    for index, (case, state, agent) in enumerate(selected):
        for mode in ("per_request", "pooled") if index % 2 == 0 else ("pooled", "per_request"):
            if sum(r["telemetry"].get("cost_usd") or 0 for r in records) + 0.003 > 0.02:
                raise RuntimeError("Transport probe budget cap")
            predictor = (
                JevPredictor(history, timeout_s=10)
                if mode == "per_request"
                else PooledJevPredictor(history, pool=pool, timeout_s=10)
            )
            value = predictor.predict(state, agent)
            row = {"case": case, "mode": mode, "telemetry": predictor.records[-1]}
            records.append(row)
            append_json(a.output / "records.jsonl", row)
summary = {
    "requests": len(records),
    "cost_usd": sum(r["telemetry"].get("cost_usd") or 0 for r in records),
    "pool_startup_s": startup,
    "development_only": True,
    "paired_cases": 32,
    "order": "Alternated transport order inside each identical-input pair",
}
for mode in ("per_request", "pooled"):
    times = [r["telemetry"]["latency_s"] for r in records if r["mode"] == mode]
    summary[mode] = {
        "mean_s": statistics.mean(times),
        "median_s": statistics.median(times),
        "p95_s": sorted(times)[round(0.95 * (len(times) - 1))],
    }
write_json(a.output / "summary.json", summary)
print(json.dumps(summary, indent=2))
