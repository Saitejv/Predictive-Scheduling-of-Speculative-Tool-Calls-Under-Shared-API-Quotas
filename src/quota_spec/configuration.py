"""Shared environment-driven policy factory for the live gateway and QA harness."""

import json
import os
from pathlib import Path

from .admission import AdmissionConfig, PredictiveAdmission
from .models import load_tasks
from .policies import CurrentCapacity, FixedReserve, NoSpeculation, UsageForecastReserve
from .prediction import HistoryPredictor


def configured_policy(name=None):
    name = name or os.environ.get("QUOTA_POLICY", "current_capacity")
    baselines = {
        "no_speculation": NoSpeculation,
        "current_capacity": CurrentCapacity,
        "fixed_reserve": lambda: FixedReserve(int(os.environ.get("QUOTA_RESERVE", "1"))),
        "usage_forecast": UsageForecastReserve,
    }
    if name in baselines:
        return baselines[name]()
    if name not in ("predictive", "own_agent_only"):
        raise ValueError(f"Unknown QUOTA_POLICY: {name}")
    history = HistoryPredictor.fit(
        load_tasks(
            json.loads(Path(os.environ.get("QUOTA_HISTORY", "data/development.json")).read_text())
        )
    )
    predictor_name = os.environ.get("QUOTA_PREDICTOR", "history")
    predictor = history
    if predictor_name != "history":
        from .adapters import JevPredictor, KevPredictor, MockSystemOnePredictor

        constructors = {"jev": JevPredictor, "kev": KevPredictor, "mock": MockSystemOnePredictor}
        if predictor_name not in constructors:
            raise ValueError(f"Unknown QUOTA_PREDICTOR: {predictor_name}")
        options = dict(
            context=os.environ.get("QUOTA_CONTEXT", "progress"),
            timeout_s=float(os.environ.get("QUOTA_MODEL_TIMEOUT_S", "2")),
            decision_timeout_s=float(os.environ.get("QUOTA_DECISION_TIMEOUT_S", "5")),
        )
        for option, env in (
            ("input_usd_per_million", "QUOTA_INPUT_USD_PER_MILLION"),
            ("output_usd_per_million", "QUOTA_OUTPUT_USD_PER_MILLION"),
        ):
            if os.environ.get(env):
                options[option] = float(os.environ[env])
        predictor = constructors[predictor_name](history, **options)
    config = AdmissionConfig(
        samples=int(os.environ.get("QUOTA_SAMPLES", "16")),
        horizon_s=float(os.environ.get("QUOTA_HORIZON_S", "30")),
        max_calls=int(os.environ.get("QUOTA_MAX_CALLS", "4")),
        epsilon=float(os.environ.get("QUOTA_EPSILON", ".05")),
        overhead_s=float(os.environ.get("QUOTA_OVERHEAD_S", ".001")),
    )
    return PredictiveAdmission(predictor, config, own_only=name == "own_agent_only")
