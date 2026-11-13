"""Upstream timing sanity checks and a protected single-agent benchmark entry point."""

import asyncio
import importlib.util
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.capture_audit import load_module
from quota_spec.hotpot_runtime import Events, LiveChat, Runtime, run, validate_run_protocol
from quota_spec.single_agent_reference import (
    ServiceTimeLoop,
    chess_reference,
    original_chess_analysis,
)
from quota_spec.upstream import REVISION

ROOT = Path(__file__).resolve().parents[2]


def chess_steps(a=5, generation=1, b=5, hit=True):
    return {
        "0": {
            "current_move": "e4",
            "guessed_moves": ["e4"] if hit else ["d4"],
            "time_taken_current_agent": a,
            "guess_prediction_time": generation,
            "total_tokens_current_agent": 10,
            "guess_total_tokens": 1,
        },
        "1": {
            "current_move": "d4",
            "guessed_moves": [],
            "time_taken_current_agent": b,
            "guess_prediction_time": 1,
            "total_tokens_current_agent": 10,
            "guess_total_tokens": 1,
        },
    }


class BaselineProtocolTests(unittest.TestCase):
    def test_shared_capture_pacing_delays_real_actor_by_one_extra_interval(self):
        import httpx

        def actor_answer(interval, optional):
            loop = ServiceTimeLoop()

            async def handler(request):
                await asyncio.sleep(0.01)
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": "Search[fixture]"}}],
                        "usage": {"cost": 0},
                    },
                )

            async def execute(directory):
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    chat = LiveChat(
                        client,
                        "fixture",
                        {"fixture": {"prompt": "0", "completion": "0"}},
                        Path(directory),
                        Events(clock=loop.time),
                        1,
                        10,
                        "fixture",
                        "fixture",
                        min_request_interval_s=interval,
                    )
                    await chat.call("first", "actor", "fixture", 1)
                    background = (
                        asyncio.create_task(
                            chat.call("guess", "observation_speculator", "fixture", 1)
                        )
                        if optional
                        else None
                    )
                    await asyncio.sleep(0.04)  # required Search runs concurrently
                    await chat.call("next", "actor", "fixture", 2)
                    answer = loop.time()
                    if background is not None:
                        await background
                    return answer

            try:
                with (
                    tempfile.TemporaryDirectory() as directory,
                    patch(
                        "quota_spec.transport.time", types.SimpleNamespace(perf_counter=loop.time)
                    ),
                ):
                    return loop.run_until_complete(execute(directory))
            finally:
                loop.close()

        self.assertAlmostEqual(actor_answer(1.1, False), 1.11)
        self.assertAlmostEqual(actor_answer(1.1, True), 2.21)
        self.assertAlmostEqual(actor_answer(0, False), 0.06)
        self.assertAlmostEqual(actor_answer(0, True), 0.06)

    def test_live_make_target_has_no_capture_pacing(self):
        live = subprocess.run(
            ["make", "-n", "live", "OUTPUT=results/not-executed"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("--purpose benchmark", live)
        self.assertNotIn("--min-request-interval-s", live)
        capture = subprocess.run(
            ["make", "-n", "capture", "OUTPUT=results/not-executed"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("--purpose capture", capture)
        self.assertIn("--min-request-interval-s 1.1", capture)

    def test_artificial_pacing_requires_explicit_capture_purpose(self):
        with self.assertRaisesRegex(ValueError, "--purpose capture"):
            validate_run_protocol("http", 1.1, "benchmark")
        self.assertEqual(validate_run_protocol("http", 0, "benchmark")["purpose"], "benchmark")
        self.assertEqual(
            validate_run_protocol("http", 1.1, "capture")["kind"], "paced_model_submission"
        )

    def test_guard_runs_before_output_creation_keys_or_source_download(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "not-created"
            args = types.SimpleNamespace(
                output=out,
                max_usd=1,
                max_requests=5,
                backend="http",
                min_request_interval_s=1.1,
                purpose="benchmark",
            )
            with self.assertRaisesRegex(ValueError, "speed benchmark"):
                asyncio.run(run(args))
            self.assertFalse(out.exists())


class OriginalChessTimingTests(unittest.TestCase):
    def test_correct_prediction_overlaps_real_calls(self):
        r = chess_reference(chess_steps())
        self.assertEqual(r["sequential_s"], 10)
        self.assertEqual(r["speculative_s"], 6)

    def test_incorrect_prediction_has_no_saving(self):
        r = chess_reference(chess_steps(hit=False))
        self.assertEqual(r["sequential_s"], r["speculative_s"])

    def test_next_hit_has_no_new_window_in_original_algorithm(self):
        rows = chess_steps()
        rows["1"]["guessed_moves"] = ["d4"]
        rows["2"] = dict(rows["1"], current_move="c4")
        r = chess_reference(rows)
        self.assertEqual(r["sequential_s"], 15)
        self.assertEqual(r["speculative_s"], 11)

    def test_slow_speculator_can_lose_in_original_analysis(self):
        r = chess_reference(chess_steps(generation=7))
        self.assertEqual(r["sequential_s"], 10)
        self.assertEqual(r["speculative_s"], 12)

    def test_independent_recurrence_matches_actual_authors_function(self):
        checkout = ROOT / "tmp/speculative-action-upstream"
        if not (checkout / "chess-game/guess_analysis.py").exists():
            self.skipTest("Original public repository checkout unavailable")
        original = original_chess_analysis(checkout)
        for args in [{}, {"generation": 7}, {"hit": False}]:
            rows = chess_steps(**args)
            a = original(rows, 2)
            b = chess_reference(rows)
            self.assertEqual(a["time_regular"], b["sequential_s"])
            self.assertEqual(a["time_speculate"], b["speculative_s"])


class AsyncRuntimeReferenceTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "data/raw/speculative-action" / REVISION
        if not (source / "upstream.json").exists() or any(
            importlib.util.find_spec(m) is None for m in ["gymnasium", "pandas", "requests", "bs4"]
        ):
            self.skipTest("Pinned upstream and paper dependencies required")
        self.module = load_module(source)

    def playback(self, mode, parent=4, next_tool=4, generation=0.2):
        loop = ServiceTimeLoop()
        events = Events(clock=loop.time)

        class Chat:
            async def call(self, prompt, role, episode, step):
                if role == "observation_speculator":
                    await asyncio.sleep(generation / 2)
                    return "A mock article."
                if role == "speculative_actor":
                    await asyncio.sleep(generation / 2)
                    action = "Search[B]" if step == 2 else "Finish[answer]"
                else:
                    await asyncio.sleep(0.5 if step == 2 else 0.1)
                    action = {1: "Search[A]", 2: "Search[B]", 3: "Finish[answer]"}[step]
                return f"Thought {step}: use evidence.\nAction {step}: {action}"

        class Search:
            async def search(self, query, episode, step, speculative=False):
                await asyncio.sleep(parent if query == "A" else next_tool)
                return {"obs": "Real evidence.", "page": "Real evidence.", "result_titles": None}

        runtime = Runtime(self.module, Chat(), Search(), events, "Examples\n", clock=loop.time)
        try:
            row = loop.run_until_complete(runtime.episode(1, "Question?", "answer", mode, "mock"))
            self.assertIsNone(row["failure"])
            return row
        finally:
            loop.close()

    def test_real_runtime_completed_reuse_has_expected_seconds(self):
        no = self.playback("sequential")
        yes = self.playback("speculative")
        self.assertAlmostEqual(no["completion_s"], 8.7)
        self.assertAlmostEqual(yes["completion_s"], 4.7)
        self.assertEqual(yes["cache_hits"], 1)
        self.assertEqual(yes["answer"], no["answer"])

    def test_real_runtime_joins_only_remainder_of_prefetch(self):
        no = self.playback("sequential", parent=1, next_tool=10)
        yes = self.playback("speculative", parent=1, next_tool=10)
        self.assertAlmostEqual(no["completion_s"], 11.7)
        self.assertAlmostEqual(yes["completion_s"], 10.4)
        self.assertEqual(yes["inflight_hits"], 1)

    def test_real_runtime_does_not_wait_for_late_generation(self):
        yes = self.playback("speculative", parent=1, next_tool=1, generation=8)
        self.assertAlmostEqual(yes["completion_s"], 2.7)
        self.assertGreater(yes["resource_s"], yes["completion_s"])
        self.assertEqual(yes["prefetches"], 0)


if __name__ == "__main__":
    unittest.main()
