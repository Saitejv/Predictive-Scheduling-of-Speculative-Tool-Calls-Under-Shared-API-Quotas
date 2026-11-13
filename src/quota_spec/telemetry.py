"""Summaries of actual inference calls, including retained failed attempts."""

import json


def record_usage(record, usage, input_field, output_field, input_price, output_price):
    """Prefer billed provider cost; only token counters must be integers."""
    from .models import nonnegative

    if not isinstance(usage, dict):
        raise ValueError("usage must be an object")
    for source, target in ((input_field, "input_tokens"), (output_field, "output_tokens")):
        value = usage.get(source)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid token usage")
        record[target] = value
    if usage.get("cost") is not None:
        cost = usage["cost"]
        if type(cost) not in (int, float):
            raise ValueError("Invalid provider cost")
        nonnegative(cost, "provider cost")
        record.update(cost_usd=cost, cost_source="provider")
    elif all(record.get(f) is not None for f in ("input_tokens", "output_tokens")) and all(
        p is not None for p in (input_price, output_price)
    ):
        record.update(
            cost_usd=(record["input_tokens"] * input_price + record["output_tokens"] * output_price)
            / 1e6,
            cost_source="token_price_estimate",
        )


def summarize_inference(records):
    records = list(records)
    result = {"requests": len(records), "failures": sum(bool(r.get("failure")) for r in records)}
    result["cancelled"] = sum(bool(r.get("cancelled")) for r in records)
    for field in ("input_tokens", "output_tokens", "cost_usd"):
        known = [r[field] for r in records if r.get(field) is not None]
        result[field] = sum(known) if len(known) == len(records) else None
        result[f"known_{field}"] = sum(known)
        result[f"unknown_{field}_requests"] = len(records) - len(known)
    return result


def audit_pipeline(output):
    groups = {
        "collection_qa": [],
        "collection_speculator": [],
        "forecast_collection": [],
        "live_qa": [],
        "live_speculator": [],
        "live_predictor": [],
    }
    for folder in ("tasks", "failed_attempts"):
        for path in (output / "traces" / folder).glob("*.json"):
            task = json.loads(path.read_text())
            groups["collection_qa"].extend(task.get("inference", []))
            groups["collection_speculator"].extend(task.get("speculator_inference", []))
    for path in (output / "forecasts").glob("*.json"):
        bank = json.loads(path.read_text())
        for response in [*bank.get("responses", {}).values(), *bank.get("failed_attempts", [])]:
            groups["forecast_collection"].append(response["telemetry"])
    # Interrupted live runs are real requests too, and must not disappear from the budget.
    for folder in output.glob("live*"):
        if not folder.is_dir():
            continue
        for path in folder.glob("*-inference.jsonl"):
            category = "live_qa"
            if path.name.endswith("-predictor-inference.jsonl"):
                category = "live_predictor"
            elif path.name.endswith("-speculator-inference.jsonl"):
                category = "live_speculator"
            groups[category].extend(
                json.loads(line) for line in path.read_text().splitlines() if line
            )
    return {name: summarize_inference(records) for name, records in groups.items()}
