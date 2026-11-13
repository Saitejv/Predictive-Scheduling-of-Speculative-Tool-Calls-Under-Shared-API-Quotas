"""Speculative tools keep running across actor thinking and later actions."""

import argparse
import asyncio
import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.capture_audit import audit, load_module
from quota_spec.hotpot_runtime import Events, LiveChat, MockChat, Runtime, run
from quota_spec.single_agent_reference import ServiceTimeLoop
from quota_spec.upstream import REVISION

ROOT = Path(__file__).resolve().parents[2]


class PersistentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.source = ROOT / "data/raw/speculative-action" / REVISION
        if not (self.source / "upstream.json").exists() or any(
            importlib.util.find_spec(m) is None for m in ["gymnasium", "pandas", "requests", "bs4"]
        ):
            self.skipTest("Prepare pinned upstream and paper extras")
        self.module = load_module(self.source)

    def play(
        self,
        steps,
        generation,
        candidates,
        *,
        mode="speculative",
        lifetime="episode",
        wrong_duration=12,
    ):
        loop = ServiceTimeLoop()
        events = Events(clock=loop.time)
        searches = []

        class Chat:
            async def call(self, prompt, role, episode, step):
                if role == "observation_speculator":
                    await asyncio.sleep(generation / 2)
                    return "A keyword article."
                if role == "speculative_actor":
                    await asyncio.sleep(generation / 2)
                    actions = candidates.get(step - 1, ["Finish[answer]"])
                else:
                    await asyncio.sleep(steps[step - 1][1])
                    actions = [steps[step - 1][0]]
                return f"Thought {step}: use evidence.\nAction {step}: " + ", ".join(actions)

        class Search:
            async def search(self, query, episode, step, speculative=False):
                searches.append((query, speculative, loop.time()))
                duration = next(
                    (s[2] for s in steps if s[0] == "Search[" + query + "]"), wrong_duration
                )
                await asyncio.sleep(duration)
                return {
                    "obs": "Real keyword evidence.",
                    "page": "Real keyword evidence.",
                    "result_titles": None,
                }

        async def local(env, action, step):
            value = env.step(action[0].lower() + action[1:])
            await asyncio.sleep(steps[step - 1][2])
            return value

        runtime = Runtime(
            self.module,
            Chat(),
            Search(),
            events,
            "Examples\n",
            clock=loop.time,
            local_step=local,
            candidate_lifetime=lifetime,
        )
        try:
            result = loop.run_until_complete(
                runtime.episode(1, "Question?", "answer", mode, "mock")
            )
            self.assertIsNone(result["failure"])
            return result, events.rows, searches
        finally:
            loop.close()

    def test_prefetch_launches_after_parent_tool_finishes_while_actor_is_thinking(self):
        steps = [("Search[A]", 0.1, 1), ("Search[B]", 2, 1), ("Finish[answer]", 0.1, 0)]
        for lifetime in ["next_action", "episode"]:
            yes, events, _ = self.play(steps, 1.5, {1: ["Search[B]"]}, lifetime=lifetime)
            no, _, _ = self.play(steps, 1.5, {}, mode="sequential")
            launch = next(e for e in events if e["event"] == "prefetch_launched")
            self.assertAlmostEqual(launch["time_s"], 1.6)
            self.assertTrue(launch["actor_thinking"])
            self.assertEqual(launch["actor_step"], 2)
            self.assertAlmostEqual(no["completion_s"], 4.2)
            self.assertAlmostEqual(yes["completion_s"], 3.2)
            self.assertEqual(yes["prefetches_while_actor_thinking"], 1)

    def test_tool_can_be_joined_when_its_result_is_not_finished_at_demand(self):
        steps = [("Search[A]", 0.1, 1), ("Search[B]", 2, 4), ("Finish[answer]", 0.1, 0)]
        yes, events, _ = self.play(steps, 1.5, {1: ["Search[B]"]})
        no, _, _ = self.play(steps, 1.5, {}, mode="sequential")
        self.assertAlmostEqual(no["completion_s"], 7.2)
        self.assertAlmostEqual(yes["completion_s"], 5.7)
        self.assertEqual(yes["inflight_hits"], 1)
        join = next(e for e in events if e["event"] == "cache_joined")
        self.assertAlmostEqual(join["requested_at_s"], 3.1)
        self.assertAlmostEqual(join["time_s"], 5.6)

    def test_prediction_survives_a_returned_local_action_and_helps_later_search(self):
        steps = [
            ("Search[A]", 0.1, 1),
            ("Lookup[keyword]", 0.1, 0),
            ("Search[B]", 2, 1),
            ("Finish[answer]", 0.1, 0),
        ]
        legacy, _, _ = self.play(steps, 1.5, {1: ["Search[B]"]}, lifetime="next_action")
        current, events, _ = self.play(steps, 1.5, {1: ["Search[B]"]})
        self.assertAlmostEqual(legacy["completion_s"], 4.3)
        self.assertAlmostEqual(current["completion_s"], 3.3)
        launch = next(e for e in events if e["event"] == "prefetch_launched")
        self.assertEqual(launch["actor_step"], 3)
        self.assertEqual(current["answer"], legacy["answer"])

    def test_late_prediction_cannot_duplicate_an_already_requested_search(self):
        steps = [("Search[A]", 0.1, 1), ("Search[B]", 0.1, 1), ("Finish[answer]", 2, 0)]
        result, _, searches = self.play(steps, 1.5, {1: ["Search[B]"]})
        self.assertEqual(result["prefetches"], 0)
        self.assertEqual(result["duplicate_candidates_suppressed"], 1)
        self.assertEqual([(q, s) for q, s, _ in searches], [("A", False), ("B", False)])

    def test_started_unused_work_is_charged_after_answer_and_endpoints_reconcile(self):
        steps = [("Search[A]", 0.1, 1), ("Search[B]", 0.5, 1), ("Finish[answer]", 0.1, 0)]
        result, _, _ = self.play(steps, 0.2, {1: ["Search[wrong]"]})
        self.assertAlmostEqual(result["completion_s"], 2.7)
        self.assertAlmostEqual(result["resource_s"], 12.3)
        self.assertAlmostEqual(
            result["answer_at_s"] - result["started_at_s"], result["completion_s"]
        )
        self.assertAlmostEqual(
            result["drained_at_s"] - result["started_at_s"], result["resource_s"]
        )
        self.assertEqual(result["unused_prefetches"], 1)


class RecordingAndServingTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_requests_leave_a_slot_for_the_real_actor(self):
        import httpx

        release = asyncio.Event()
        three_started = asyncio.Event()
        count = 0

        async def handler(request):
            nonlocal count
            if json.loads(request.content)["model"] == "optional":
                count += 1
                if count == 3:
                    three_started.set()
                await release.wait()
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Search[fixture]"}}],
                    "usage": {"cost": 0},
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                chat = LiveChat(
                    client,
                    "fixture",
                    {m: {"prompt": "0", "completion": "0"} for m in ["actor", "optional"]},
                    Path(directory),
                    Events(),
                    1,
                    10,
                    "actor",
                    "optional",
                )
                work = [
                    asyncio.create_task(chat.call("guess", "observation_speculator", "a", i))
                    for i in range(4)
                ]
                try:
                    await asyncio.wait_for(three_started.wait(), 1)
                    await asyncio.wait_for(chat.call("real", "actor", "a", 1), 1)
                    self.assertEqual(count, 3)
                finally:
                    release.set()
                    await asyncio.gather(*work, return_exceptions=True)
                self.assertEqual(chat.requests, 5)

    async def test_new_recording_verifies_thinking_overlap_and_rejects_timing_tampering(self):
        source = ROOT / "data/raw/speculative-action" / REVISION
        if not (source / "upstream.json").exists():
            self.skipTest("Prepare upstream")

        class ThinkingChat(MockChat):
            async def call(self, prompt, role, episode, step):
                if role == "actor" and step == 2:
                    await asyncio.sleep(0.06)
                if role in ["observation_speculator", "speculative_actor"]:
                    await asyncio.sleep(0.02)
                return await super().call(prompt, role, episode, step)

        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                output=Path(directory) / "recording",
                source=source,
                count=2,
                offset=0,
                max_usd=1,
                max_requests=100,
                backend="mock",
                actor="fixture",
                speculator="fixture",
            )
            with (
                patch("quota_spec.hotpot_runtime.MockChat", ThinkingChat),
                patch.object(socket.socket, "connect", side_effect=AssertionError("offline")),
            ):
                await run(args)
                checked = audit(args.output, source)
                self.assertEqual(checked["episode_endpoint_checks"], 4)
                self.assertGreater(checked["prefetches_during_actor_thinking_verified"], 0)
                task = next((args.output / "tasks").glob("*.json"))
                data = json.loads(task.read_text())
                data["completion_s"] += 1
                task.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "duration does not match"):
                    audit(args.output, source)


if __name__ == "__main__":
    unittest.main()
