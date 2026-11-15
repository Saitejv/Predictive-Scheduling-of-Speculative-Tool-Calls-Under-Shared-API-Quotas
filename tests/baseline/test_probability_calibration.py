import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.prediction import Forecast
from quota_spec.probability_calibration import ProbabilityCalibration, apply_bins, fit, fit_bins
from quota_spec.tape_forecasts import digest


class CalibrationTests(unittest.TestCase):
    def test_monotonic_smoothing_and_pooled_contradictory_bins(self):
        blocks = fit_bins([(0.2, True), (0.2, True), (0.8, False), (0.8, False)])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(apply_bins(blocks, 0), 0.5)
        self.assertEqual(apply_bins(blocks, 1), 0.5)
        with self.assertRaises(ValueError):
            fit_bins([])

    def test_fit_maps_cannot_change_when_only_evaluation_labels_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "dataset-manifest.json").write_text("{}")
            rows = [
                (
                    {"key": key, "task_id": task},
                    None,
                    None,
                    {"next": True, "continues": label, "reuse": label},
                )
                for key, task, label in [("one", "dev", False), ("two", "evaluation", True)]
            ]
            bank = {
                "config": {
                    "dataset_sha256": hashlib.sha256(b"{}").hexdigest(),
                    "development": ["dev"],
                    "model": "fixture",
                    "mode": "progress",
                },
                "responses": {
                    key: {"reuse": 0.8, "next": 0.9, "continues": 0.7} for key in ["one", "two"]
                },
            }
            bank["sha256"] = digest(bank)
            (root / "bank.json").write_text(json.dumps(bank))
            data = {"tapes": [{"task_id": "dev"}, {"task_id": "evaluation"}]}
            with (
                patch("quota_spec.probability_calibration.load_dataset", return_value=data),
                patch("quota_spec.probability_calibration.cases", return_value=rows),
            ):
                first = fit(root, root / "bank.json", root / "first.json", 1)
                rows[-1][-1].update(continues=False, reuse=False)
                second = fit(root, root / "bank.json", root / "second.json", 1)
            self.assertEqual(first["maps"], second["maps"])
            self.assertNotEqual(first["metrics"]["evaluation"], second["metrics"]["evaluation"])
            calibrated = ProbabilityCalibration(first).transform(
                Forecast(0.8, 0.9, (1,), (2,), 0.7)
            )
            self.assertLess(calibrated.reuse_probability, 0.8)
            self.assertEqual(calibrated.delays_s, (1,))
            self.assertEqual(calibrated.durations_s, (2,))
            first["maps"]["reuse"][0]["probability"] = 1
            with self.assertRaisesRegex(ValueError, "checksum"):
                ProbabilityCalibration(first)


if __name__ == "__main__":
    unittest.main()
