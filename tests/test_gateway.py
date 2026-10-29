import asyncio
import json
import unittest
from collections import Counter

from quota_spec.gateway import Gateway, create_app
from quota_spec.models import Call
from quota_spec.search import SearchCorpus


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = 0

        async def tool(call):
            self.calls += 1
            await asyncio.sleep(0.005)
            return {"query": json.loads(call.arguments_json)["query"]}

        self.gateway = Gateway(tool, capacity=2, window_s=0.03)

    async def asyncTearDown(self):
        await self.gateway.close()

    async def test_atomic_duplicate_requests_and_agent_scoping(self):
        values = await asyncio.gather(
            *[self.gateway.required("a", Call.search("x")) for _ in range(20)]
        )
        self.assertTrue(all(v == {"query": "x"} for v in values))
        self.assertEqual(self.calls, 1)
        await self.gateway.required("b", Call.search("x"))
        self.assertEqual(self.calls, 2)

    async def test_speculative_result_is_hidden_and_exactly_reused(self):
        accepted = await self.gateway.speculate("a", Call.search("x"))
        self.assertIs(accepted, True)
        await asyncio.sleep(0.01)
        value = await self.gateway.required("a", Call.search("x"))
        self.assertEqual(value, {"query": "x"})
        self.assertEqual(self.calls, 1)
        await self.gateway.required("a", Call.search("X"))
        self.assertEqual(self.calls, 2)

    async def test_client_cancellation_keeps_spent_quota_and_execution(self):
        waiter = asyncio.create_task(self.gateway.required("a", Call.search("x")))
        await asyncio.sleep(0.001)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        value = await self.gateway.required("a", Call.search("x"))
        self.assertEqual(value, {"query": "x"})
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.gateway.quota.remaining(self.gateway.now()), 1)

    async def test_cancelled_execution_retains_spent_unit(self):
        await self.gateway.speculate("a", Call.search("x"))
        await asyncio.sleep(0)
        self.gateway.registry["a", Call.search("x")].worker.cancel()
        await asyncio.sleep(0.001)
        self.assertEqual(self.gateway.quota.remaining(self.gateway.now()), 1)
        await self.gateway.required("a", Call.search("x"))
        self.assertEqual(self.gateway.quota.remaining(self.gateway.now()), 0)

    async def test_failed_speculation_is_not_cached_and_retry_is_charged(self):
        async def fail(call):
            raise RuntimeError("tool failure")

        self.gateway.tool = fail
        await self.gateway.speculate("a", Call.search("x"))
        await asyncio.sleep(0.002)
        self.assertNotIn(("a", Call.search("x")), self.gateway.registry)
        with self.assertRaises(RuntimeError):
            await self.gateway.required("a", Call.search("x"))
        self.assertEqual(self.gateway.quota.remaining(self.gateway.now()), 0)

    async def test_fifo_required_priority_and_window_budget_under_burst(self):
        await asyncio.gather(
            *[self.gateway.required(str(i), Call.search(str(i))) for i in range(10)]
        )
        starts = [e for e in self.gateway.events if e["event"] == "call_started"]
        self.assertEqual([e["task_id"] for e in starts], list(map(str, range(10))))
        counts = Counter(int(e["time_s"] / 0.03) for e in starts)
        self.assertTrue(all(v <= 2 for v in counts.values()))

    async def test_optional_revalidates_after_slow_prediction(self):
        import threading

        entered, release = threading.Event(), threading.Event()

        class Slow:
            def admit(self, state):
                entered.set()
                release.wait(1)
                return True

        self.gateway.policy = Slow()
        self.gateway.quota.capacity = 1
        optional = asyncio.create_task(self.gateway.speculate("a", Call.search("x")))
        await asyncio.to_thread(entered.wait, 1)
        required = asyncio.create_task(self.gateway.required("b", Call.search("b")))
        await asyncio.sleep(0.001)
        release.set()
        self.assertFalse(await optional)
        await required

    async def test_http_surface_validates_requests_and_returns_only_admission(self):
        try:
            import httpx

            __import__("fastapi")
        except ImportError:
            self.skipTest("Install .[live] for HTTP tests")
        corpus = SearchCorpus([{"title": "x", "text": "x is a document"}])
        app = create_app(corpus, window_s=0.05)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            health = await client.get("/health")
            self.assertEqual(health.status_code, 200)
            await client.post("/observe", json={"task_id": "a", "task_context": "find x"})
            candidate = await client.post("/candidate", json={"task_id": "a", "query": "x"})
            self.assertEqual(candidate.json(), {"admitted": True})
            result = await client.post("/required", json={"task_id": "a", "query": "x"})
            self.assertEqual(result.json()["results"][0]["title"], "x")
            invalid = await client.post("/required", json={"task_id": "a", "query": ""})
            self.assertEqual(invalid.status_code, 422)
        await app.state.gateway.close()
