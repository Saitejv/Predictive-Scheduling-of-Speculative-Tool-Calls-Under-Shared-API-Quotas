import argparse
import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.capture_audit import audit
from quota_spec.capture_bank import complete
from quota_spec.capture_cohort import merge_datasets
from quota_spec.frozen_forecasts import prepare
from quota_spec.frozen_replay import FrozenReplay, load_dataset, recorded_candidate_options
from quota_spec.hotpot_runtime import run
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.upstream import REVISION


class BankIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_bank_is_offline_self_contained_and_ready_for_predictor_inputs(self):
        source = Path(__file__).resolve().parents[2] / "data/raw/speculative-action" / REVISION
        if not (source / "upstream.json").exists() or any(
            importlib.util.find_spec(m) is None
            for m in ("gymnasium", "pandas", "requests", "bs4", "httpx")
        ):
            self.skipTest("Prepare pinned upstream and install paper extras")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = argparse.Namespace(
                output=root / "live",
                source=source,
                count=2,
                offset=0,
                max_usd=0.5,
                max_requests=100,
                backend="mock",
                actor="fixture",
                speculator="fixture",
            )
            with (
                patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
                patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network")),
            ):
                summary = await run(args)
                self.assertEqual(summary["episodes"], 4)
                audit(args.output, source)
                result = await complete(args.output, root / "bank", upstream=source)
                self.assertEqual(result["questions"], 2)
                self.assertEqual(result["completion"]["requests"], 0)
                dataset = load_dataset(root / "bank")
                lifetime, options = recorded_candidate_options(dataset["tapes"])
                self.assertEqual(lifetime, "episode")
                self.assertTrue(options["suppress_known_calls"])
                sequential = FrozenReplay(dataset["tapes"], 100, 100).run(NoSpeculation())
                speculative = FrozenReplay(dataset["tapes"], 100, 100).run(CurrentCapacity())
                self.assertEqual(
                    sequential["metrics"]["answers"], speculative["metrics"]["answers"]
                )
                plan = prepare(root / "bank", root / "predictors", development_count=1)
                self.assertEqual(plan["predictor_calls_made"], 0)
                self.assertEqual(plan["development_count"], 1)
                self.assertEqual(plan["evaluation_count"], 1)
                contexts = json.loads((root / "predictors/contexts.json").read_text())
                for row in contexts:
                    self.assertNotIn("answer", row["context"])
                    self.assertNotIn("reuse", row["context"])
                    if "elapsed_s" in row["context"]:
                        self.assertEqual(row["context"]["elapsed_s"], 0)
                with self.assertRaisesRegex(ValueError, "overlap"):
                    merge_datasets([root / "bank", root / "bank"], root / "merged")
                merged = merge_datasets([root / "bank"], root / "combined")
                self.assertEqual(merged["questions"], 2)
                self.assertEqual(len(load_dataset(root / "combined")["tapes"]), 2)
                self.assertEqual(
                    recorded_candidate_options(load_dataset(root / "combined")["tapes"])[0],
                    "episode",
                )
                nested = merge_datasets([root / "combined"], root / "flattened")
                self.assertEqual(nested["questions"], 2)
                self.assertEqual(len(load_dataset(root / "flattened")["tapes"]), 2)
                result_path = next((root / "bank/live-capture/blobs").glob("*.json"))
                result_path.write_text("tampered")
                with self.assertRaisesRegex(ValueError, "integrity"):
                    load_dataset(root / "bank")


if __name__ == "__main__":
    unittest.main()
