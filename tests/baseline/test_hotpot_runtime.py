import asyncio
import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.hotpot_runtime import (
    Events,
    LiveChat,
    MockChat,
    MockSearch,
    Runtime,
    paired_summary,
)
from quota_spec.paper import REVISION, load_upstream


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "data/raw/speculative-action" / REVISION
        if not (root / "upstream.json").exists() or any(
            importlib.util.find_spec(m) is None for m in ("gymnasium", "pandas", "requests", "bs4")
        ):
            self.skipTest("Prepare pinned upstream and install paper extras")

        class NoSync:
            def __init__(self, **kw):
                pass

            def call(self, *a, **kw):
                raise AssertionError("Unexpected synchronous inference")

        self.module = load_upstream(root, NoSync)
        self.events = Events()

    async def episode(self, chat=None, search=None, mode="speculative"):
        runtime = Runtime(
            self.module,
            chat or MockChat(),
            search or MockSearch(self.events),
            self.events,
            "Examples\n",
        )
        with (
            patch.object(
                socket.socket, "connect", side_effect=AssertionError("Unexpected network")
            ),
            patch.object(
                socket.socket, "connect_ex", side_effect=AssertionError("Unexpected network")
            ),
        ):
            return await runtime.episode(1, "Fixture?", "mock answer", mode, "mock")

    async def test_live_generation_budget_uses_progress_without_changing_authoritative_actions(
        self,
    ):
        roles = []

        class DraftLookup(MockChat):
            async def call(self, prompt, role, episode, step):
                roles.append(role)
                if role == "speculative_actor":
                    return f"Thought {step}: Need a local lookup.\nAction {step}: Lookup[keyword]"
                return await super().call(prompt, role, episode, step)

        sequential = await self.episode(mode="sequential")
        runtime = Runtime(
            self.module,
            DraftLookup(),
            MockSearch(self.events),
            self.events,
            "Examples\n",
            max_generation_step=1,
        )
        result = await runtime.episode(1, "Fixture?", "mock answer", "speculative", "mock")
        self.assertEqual(roles.count("observation_speculator"), 1)
        self.assertEqual(roles.count("speculative_actor"), 1)
        self.assertEqual(result["generation_windows_suppressed"], 1)
        self.assertEqual(result["answer"], sequential["answer"])
        self.assertEqual(
            [s["action"] for s in result["trajectory"]],
            [s["action"] for s in sequential["trajectory"]],
        )

    async def test_real_concurrency_exact_reuse_and_authoritative_lookup(self):
        sequential = await self.episode(mode="sequential")
        speculative = await self.episode()
        self.assertIsNone(speculative["failure"])
        self.assertEqual(speculative["cache_hits"], 1)
        self.assertEqual(speculative["prefetches"], 3)
        self.assertEqual(speculative["unused_prefetches"], 2)
        self.assertEqual(
            [r["action"] for r in sequential["trajectory"]],
            [r["action"] for r in speculative["trajectory"]],
        )
        self.assertEqual(
            sequential["trajectory"][2]["observation"], speculative["trajectory"][2]["observation"]
        )
        events = [r for r in self.events.rows if r.get("episode") == "1:speculative"]
        launched = next(
            r for r in events if r["event"] == "prefetch_launched" and r["query"] == "Mock second"
        )
        required = next(r for r in events if r["event"] == "required_action" and r["step"] == 2)
        first_done = next(r for r in events if r["event"] == "search_finished" and r["step"] == 1)
        self.assertLess(launched["time_s"], required["time_s"])
        self.assertLess(launched["time_s"], first_done["time_s"])
        self.assertGreaterEqual(speculative["resource_s"], speculative["completion_s"])
        self.assertIsNone(speculative["em"])
        summary = paired_summary([sequential, speculative], [])
        self.assertFalse(summary["live_execution"])
        self.assertEqual(summary["paired"]["identical_action_pairs"], 1)

    async def test_late_observation_never_blocks_answer_and_launches_nothing(self):
        class SlowObservation(MockChat):
            async def call(self, prompt, role, episode, step):
                if role == "observation_speculator":
                    await asyncio.sleep(0.15)
                return await super().call(prompt, role, episode, step)

        result = await self.episode(SlowObservation())
        self.assertEqual(result["prefetches"], 0)
        self.assertEqual(result["late_windows"], 2)
        self.assertGreater(result["drain_s"], 0.05)
        self.assertEqual(result["answer"], "mock answer")

    async def test_late_speculative_actor_is_drained_without_launching_searches(self):
        class SlowBranch(MockChat):
            async def call(self, prompt, role, episode, step):
                if role == "speculative_actor":
                    await asyncio.sleep(0.15)
                return await super().call(prompt, role, episode, step)

        result = await self.episode(SlowBranch())
        self.assertEqual(result["prefetches"], 0)
        self.assertEqual(result["late_windows"], 2)
        self.assertGreater(result["drain_s"], 0.05)

    async def test_case_different_arguments_cannot_reuse_cache(self):
        class DifferentCase(MockChat):
            async def call(self, prompt, role, episode, step):
                content = await super().call(prompt, role, episode, step)
                return (
                    content.replace("Mock second", "MOCK SECOND")
                    if role == "speculative_actor"
                    else content
                )

        result = await self.episode(DifferentCase())
        self.assertEqual(result["cache_hits"], 0)
        self.assertEqual(result["answer"], "mock answer")

    async def test_hypothetical_lookup_and_finish_cannot_change_real_state(self):
        class Poison(MockChat):
            async def call(self, prompt, role, episode, step):
                if role == "speculative_actor":
                    return f"Thought {step}: Ignore reality.\nAction {step}: Finish[poison], Lookup[poison]"
                return await super().call(prompt, role, episode, step)

        result = await self.episode(Poison())
        self.assertEqual(result["prefetches"], 0)
        self.assertEqual(result["answer"], "mock answer")
        self.assertIn("keyword", result["trajectory"][2]["observation"])

    async def test_failed_prefetch_falls_back_to_required_search_and_is_counted(self):
        events = self.events

        class FailingPrefetch(MockSearch):
            async def search(self, query, episode, step, speculative=False):
                if speculative and query == "Mock second":
                    raise ValueError("Optional tool failure")
                return await super().search(query, episode, step, speculative)

        result = await self.episode(search=FailingPrefetch(events))
        self.assertIsNone(result["failure"])
        self.assertEqual(result["optional_failures"], 1)
        self.assertEqual(result["cache_hits"], 0)

    def test_failed_exact_page_search_keeps_previous_lookup_state(self):
        env = self.module.environment.WikiEnv("unused")
        env.page, env.lookup_keyword, env.lookup_cnt = "Real page.", "Real", 2
        env.lookup_list = ["First.", "Second.", "Third."]
        Runtime.apply_search(
            env, {"page": None, "obs": "Similar pages.", "result_titles": ["Alternative"]}
        )
        self.assertEqual(env.page, "Real page.")
        self.assertEqual(env.lookup_cnt, 2)
        self.assertEqual(env.lookup_keyword, "Real")
        self.assertEqual(env.obs, "Similar pages.")


class LiveBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_reservations_prevent_overspending_and_keep_costs(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("Install live extras")
        seen = []

        async def handler(request):
            seen.append(request)
            await asyncio.sleep(0.02)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Search[fixture]"}}],
                    "usage": {"cost": 0.0001},
                },
            )

        with tempfile.TemporaryDirectory() as out:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                chat = LiveChat(
                    client,
                    "secret-fixture",
                    {"fixture": {"prompt": "0", "completion": "0.000001"}},
                    Path(out),
                    Events(),
                    0.0015,
                    10,
                    "fixture",
                    "fixture",
                )
                result = await asyncio.gather(
                    chat.call("p", "actor", "a", 1),
                    chat.call("p", "actor", "a", 1),
                    return_exceptions=True,
                )
                self.assertEqual(sum(isinstance(r, RuntimeError) for r in result), 1)
                self.assertEqual(len(seen), 1)
                self.assertAlmostEqual(chat.spent, 0.0001)
                self.assertAlmostEqual(chat.reserved, 0)
                self.assertNotIn("secret-fixture", (Path(out) / "requests.jsonl").read_text())

    async def test_unknown_billed_cost_blocks_subsequent_requests(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("Install live extras")

        async def handler(request):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "Search[x]"}}], "usage": {}}
            )

        with tempfile.TemporaryDirectory() as out:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                chat = LiveChat(
                    client,
                    "fixture",
                    {"fixture": {"prompt": "0", "completion": "0"}},
                    Path(out),
                    Events(),
                    1,
                    10,
                    "fixture",
                    "fixture",
                )
                await chat.call("p", "actor", "a", 1)
                with self.assertRaises(RuntimeError):
                    await chat.call("p", "actor", "a", 2)
                self.assertEqual(chat.requests, 1)
                self.assertTrue(chat.unknown)
                self.assertIsNone(
                    json.loads((Path(out) / "inference.jsonl").read_text())["cost_usd"]
                )


if __name__ == "__main__":
    unittest.main()
