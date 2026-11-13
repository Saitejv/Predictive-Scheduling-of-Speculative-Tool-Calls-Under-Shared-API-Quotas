import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.capture import Capture, CaptureStore, restore, snapshot
from quota_spec.capture_audit import audit
from quota_spec.hotpot_runtime import Events, MockChat, MockSearch, Runtime
from quota_spec.upstream import REVISION, load_upstream, paper_indices, workload_indices


class BlobTests(unittest.TestCase):
    def test_immutable_blobs_verify_integrity_and_do_not_collapse_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Capture(Path(temp))
            a = capture.instant("fixture", "agent", 1, "branch", inputs={"a": 1}, output="one")
            b = capture.instant("fixture", "agent", 1, "branch", inputs={"a": 1}, output="two")
            self.assertNotEqual(a, b)
            self.assertEqual(capture.nodes[0]["input"], capture.nodes[1]["input"])
            capture.seal()
            store = CaptureStore(temp)
            self.assertEqual(store.blob(store.by_id[b]["output"]), "two")
            (Path(temp) / "blobs" / (capture.nodes[0]["input"] + ".json")).write_text("tampered")
            with self.assertRaisesRegex(ValueError, "integrity"):
                CaptureStore(temp)

    def test_fifty_question_order_extends_original_twenty_without_overlap(self):
        self.assertEqual(workload_indices(20), paper_indices(20))
        self.assertEqual(workload_indices(50), workload_indices(20) + workload_indices(30, 20))
        self.assertEqual(len(set(workload_indices(50))), 50)
        for args in ((0, 0), (1, -1), (7406, 0), (True, 0)):
            with self.assertRaises(ValueError):
                workload_indices(*args)


class FullCaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = Path(__file__).resolve().parents[2] / "data/raw/speculative-action" / REVISION
        if not (self.source / "upstream.json").exists() or any(
            importlib.util.find_spec(m) is None for m in ("gymnasium", "pandas", "requests", "bs4")
        ):
            self.skipTest("Prepare pinned upstream and install paper extras")

        class NoSync:
            def __init__(self, **kwargs):
                pass

        self.module = load_upstream(self.source, NoSync)

    def test_snapshot_restores_lookup_cursor_and_absent_attributes(self):
        env = self.module.environment.WikiEnv("unused")
        env.page = "A keyword here. A second keyword here."
        env.step("lookup[keyword]")
        saved = snapshot(env)
        expected = env.step("lookup[keyword]")[0]
        restored = restore(self.module.environment.WikiEnv("unused"), saved)
        self.assertEqual(restored.step("lookup[keyword]")[0], expected)
        restored.result_titles = ["not present in snapshot"]
        restore(restored, saved)
        self.assertFalse(hasattr(restored, "result_titles"))
        self.assertEqual(saved["lookup_cnt"], 1)

    async def test_socket_blocked_capture_preserves_unused_tools_and_reexecutes_states(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tasks").mkdir()
            events = Events(root / "events.jsonl")
            capture = Capture(root / "capture", events.start)
            runtime = Runtime(
                self.module, MockChat(), MockSearch(events), events, "Examples\n", capture=capture
            )
            with (
                patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
                patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network")),
            ):
                for mode in ("sequential", "speculative"):
                    row = await runtime.episode(1, "Fixture?", "mock answer", mode, "mock")
                    self.assertIsNone(row["failure"])
                    (root / "tasks" / f"1-{mode}.json").write_text(json.dumps(row))
            capture.seal()
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "backend": "mock",
                        "indices": [1],
                        "upstream": json.loads((self.source / "upstream.json").read_text()),
                    }
                )
            )
            result = audit(root, self.source)
            self.assertTrue(result["passed"])
            self.assertEqual(result["state_transitions_reexecuted"], 8)
            self.assertEqual(result["prefetch_hits"], 1)
            self.assertEqual(result["unused_prefetches"], 2)
            store = CaptureStore(root / "capture")
            unused = [n for n in store.nodes if n["kind"] == "search" and n["branch"] == "prefetch"]
            self.assertEqual(len(unused), 3)
            self.assertTrue(all("state_after" in store.blob(n["output"]) for n in unused))


if __name__ == "__main__":
    unittest.main()
