"""Monotone probability calibration using only declared development questions."""

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from .artifacts import write_json
from .frozen_replay import load_dataset
from .prediction import calibration
from .tape_forecasts import cases, digest


def fit_bins(pairs):
    """Decile bins with Beta(1,1) smoothing and weighted PAV monotonicity."""
    blocks = []
    for index in range(10):
        labels = [y for p, y in pairs if min(int(p * 10), 9) == index]
        if not labels:
            continue
        blocks.append(
            {"upper": (index + 1) / 10, "positive": sum(labels) + 1, "weight": len(labels) + 2}
        )
        while (
            len(blocks) > 1
            and blocks[-2]["positive"] / blocks[-2]["weight"]
            > blocks[-1]["positive"] / blocks[-1]["weight"]
        ):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                {
                    "upper": right["upper"],
                    "positive": left["positive"] + right["positive"],
                    "weight": left["weight"] + right["weight"],
                }
            )
    if not blocks:
        raise ValueError("Calibration requires development labels")
    return [
        {"upper": b["upper"], "probability": b["positive"] / b["weight"], "weight": b["weight"]}
        for b in blocks
    ]


def apply_bins(blocks, p):
    return next((b["probability"] for b in blocks if p < b["upper"]), blocks[-1]["probability"])


class ProbabilityCalibration:
    def __init__(self, artifact):
        if artifact.get("sha256") != digest({k: v for k, v in artifact.items() if k != "sha256"}):
            raise ValueError("Calibration checksum mismatch")
        self.artifact = artifact

    def transform(self, forecast):
        fields = {
            "reuse_probability": "reuse",
            "next_probability": "next",
            "continue_probability": "continues",
        }
        return replace(
            forecast,
            **{
                field: apply_bins(self.artifact["maps"][name], getattr(forecast, field))
                for field, name in fields.items()
            },
        )


def fit(dataset, bank, output, development_count=20, *, development_only=False):
    if Path(output).exists():
        raise ValueError("Choose a fresh calibration artifact")
    data = load_dataset(dataset)
    if not 1 <= development_count < len(data["tapes"]):
        raise ValueError("Need disjoint development and evaluation questions")
    saved = json.loads(Path(bank).read_text())
    if saved.get("sha256") != digest({k: v for k, v in saved.items() if k != "sha256"}):
        raise ValueError("Forecast bank checksum mismatch")
    if (
        saved["config"]["dataset_sha256"]
        != hashlib.sha256((Path(dataset) / "dataset-manifest.json").read_bytes()).hexdigest()
    ):
        raise ValueError("Calibration dataset differs from forecast bank")
    dev = {t["task_id"] for t in data["tapes"][:development_count]}
    if set(saved["config"]["development"]) != dev:
        raise ValueError("Calibration development split differs from bank")
    grouped = {
        split: {field: [] for field in ("reuse", "next", "continues")}
        for split in ("development", "evaluation")
    }
    seen = set()
    for case, _, _, labels in cases(
        data["tapes"][:development_count] if development_only else data["tapes"],
        mode=saved["config"]["mode"],
        max_candidate_age=saved["config"].get("max_candidate_age", 0),
    ):
        if case["key"] in seen:
            continue
        seen.add(case["key"])
        row = saved["responses"].get(case["key"])
        if not row or row.get("failure"):
            raise ValueError("Calibration bank is incomplete")
        split = "development" if case["task_id"] in dev else "evaluation"
        for field in ("reuse", "next", "continues"):
            if labels[field] is not None and (field == "next" or labels["next"]):
                grouped[split][field].append((row[field], labels[field]))
    maps = {field: fit_bins(pairs) for field, pairs in grouped["development"].items()}
    artifact = {
        "version": 1,
        "evaluation_scored": not development_only,
        "model": saved["config"]["model"],
        "context": saved["config"]["mode"],
        "development_ids": sorted(dev),
        "maps": maps,
        "bank_sha256": saved["sha256"],
        "fit": "Development-only deciles, Beta(1,1) smoothing, weighted monotone pooling",
        "transfer_limit": "Training contexts have phase-entry elapsed=0; live elapsed and persistent-candidate transfer is approximate.",
        "metrics": {
            split: {
                field: {
                    "raw": calibration(pairs),
                    "calibrated": calibration([(apply_bins(maps[field], p), y) for p, y in pairs]),
                }
                for field, pairs in fields.items()
            }
            for split, fields in grouped.items()
        },
    }
    artifact["sha256"] = digest(artifact)
    write_json(Path(output), artifact)
    return artifact


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("bank", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--development-count", type=int, default=20)
    p.add_argument("--development-only", action="store_true")
    a = p.parse_args()
    result = fit(
        a.dataset, a.bank, a.output, a.development_count, development_only=a.development_only
    )
    print(
        json.dumps(
            {
                split: {
                    field: {name: values["brier"] for name, values in metrics.items()}
                    for field, metrics in fields.items()
                }
                for split, fields in result["metrics"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
