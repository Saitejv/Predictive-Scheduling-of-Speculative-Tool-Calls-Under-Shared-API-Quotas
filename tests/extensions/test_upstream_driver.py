import argparse
import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

for dependency in ("httpx", "numpy", "requests", "bs4", "gymnasium", "pandas"):
    if importlib.util.find_spec(dependency) is None:
        raise unittest.SkipTest("Requires paper extras")

httpx = __import__("httpx")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_upstream_baseline.py"
SPEC = importlib.util.spec_from_file_location("upstream_driver", SCRIPT)
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


class BudgetTests(unittest.TestCase):
    def guard(self, output):
        guard = object.__new__(driver.BoundedTransport)
        guard.key, guard.budget, guard.output = "fixture", 0.01, Path(output)
        guard.spent, guard.known_costs = 0.0, True
        guard.prices = {"fixture": {"prompt": "0.0000003", "completion": "0.0000025"}}
        return guard

    def request(self, tokens=100):
        return httpx.Request(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            json={"model": "fixture", "max_tokens": tokens, "messages": []},
        )

    def test_budget_denial_never_sends(self):
        with tempfile.TemporaryDirectory() as out, patch("httpx.Client") as client:
            with self.assertRaises(driver.StopRun):
                self.guard(out)(self.request(10000))
            client.assert_not_called()

    def test_unknown_cost_stops_and_preserves_response(self):
        with tempfile.TemporaryDirectory() as out, patch("httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = httpx.Response(
                200, json={"id": "unknown-cost", "usage": {}}
            )
            guard = self.guard(out)
            with self.assertRaises(driver.StopRun):
                guard(self.request())
            self.assertFalse(guard.known_costs)
            saved = json.loads((Path(out) / "requests.jsonl").read_text())
            self.assertEqual(saved["response"]["id"], "unknown-cost")
            self.assertIsNone(saved["cost_usd"])
            with self.assertRaises(driver.StopRun):
                guard(self.request())
            self.assertEqual(client.call_count, 1)


class OriginalRunnerTests(unittest.TestCase):
    def test_original_and_corrected_runner_without_network(self):
        root = SCRIPT.parents[1] / "tmp/speculative-action-upstream"
        if not (root / ".git").exists():
            self.skipTest("Clone the pinned upstream Git checkout first")
        with (
            tempfile.TemporaryDirectory() as out,
            patch.object(
                socket.socket, "connect", side_effect=AssertionError("Unexpected network")
            ),
            patch.object(
                socket.socket, "connect_ex", side_effect=AssertionError("Unexpected network")
            ),
        ):
            for fixed in (False, True):
                output = Path(out) / str(fixed)
                result = driver.run(
                    argparse.Namespace(
                        checkout=root,
                        output=output,
                        count=2,
                        backend="mock",
                        max_usd=None,
                        max_requests=64,
                        state_fixes=fixed,
                        actor="google/gemini-2.5-flash",
                        speculator="google/gemini-2.5-flash",
                    )
                )
                self.assertIsNone(result["failure"])
                self.assertEqual(result["tasks"], 2)
                self.assertEqual(result["actual_indices_match"], fixed)
                self.assertIsNone(result["qa_em"])
                self.assertFalse(result["live_speedup_measured"])
                self.assertEqual(len(list((output / "tasks").glob("*.json"))), 2)
                for k in (1, 3):
                    self.assertEqual(
                        result["original_scorer"][f"top{k}"],
                        result["agreement"][f"top{k}"]["upstream_macro_accuracy"],
                    )


if __name__ == "__main__":
    unittest.main()
