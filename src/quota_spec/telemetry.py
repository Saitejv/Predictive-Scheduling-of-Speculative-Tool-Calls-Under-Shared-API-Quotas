"""Summaries of actual inference calls, including retained failed attempts."""

import json


def summarize_inference(records):
    records = list(records)
    result = {"requests": len(records), "failures": sum(bool(r.get("failure")) for r in records)}
    for field in ("input_tokens", "output_tokens", "cost_usd"):
        known = [r[field] for r in records if r.get(field) is not None]
        result[field] = sum(known) if len(known) == len(records) else None
        result[f"known_{field}"] = sum(known)
        result[f"unknown_{field}_requests"] = len(records) - len(known)
    return result


def audit_pipeline(output):
    groups = {"collection_qa": [], "forecast_collection": [], "live_qa": [], "live_predictor": []}
    for folder in ("tasks", "failed_attempts"):
        for path in (output / "traces" / folder).glob("*.json"):
            groups["collection_qa"].extend(json.loads(path.read_text()).get("inference", []))
    for path in (output / "forecasts").glob("*.json"):
        bank = json.loads(path.read_text())
        for response in [*bank.get("responses", {}).values(), *bank.get("failed_attempts", [])]:
            groups["forecast_collection"].append(response["telemetry"])
    # Interrupted live runs are real requests too, and must not disappear from the budget.
    for folder in output.glob("live*"):
        if not folder.is_dir():
            continue
        for path in folder.glob("*-inference.jsonl"):
            category = (
                "live_predictor" if path.name.endswith("-predictor-inference.jsonl") else "live_qa"
            )
            groups[category].extend(
                json.loads(line) for line in path.read_text().splitlines() if line
            )
    return {name: summarize_inference(records) for name, records in groups.items()}
