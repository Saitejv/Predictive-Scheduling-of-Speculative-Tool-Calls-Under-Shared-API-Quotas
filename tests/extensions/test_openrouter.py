import asyncio
import json
import threading
import unittest
from unittest.mock import patch

from quota_spec.adapters import JevPredictor
from quota_spec.models import AgentState, Call, Observation, Snapshot, Step, Task
from quota_spec.prediction import HistoryPredictor
from quota_spec.qa import HTTPQA, MockQA, run_agent
from quota_spec.speculation import MockSpeculator
from quota_spec.telemetry import summarize_inference


class OpenRouterContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            __import__("httpx")
        except ImportError:
            raise unittest.SkipTest("Requires live extras")

    def test_decisions_endpoint_accepts_billed_cost_and_nested_usage(self):
        import httpx

        def handler(request):
            self.assertEqual(request.url.path, "/api/alpha/decisions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            return httpx.Response(
                200,
                json={
                    "answers": {k: {"noul": 0.5} for k in ("reuse", "next", "continues")},
                    "model": "typesafe/jev-1.14-20261014",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 3,
                        "cost": 0.0000042,
                        "cost_details": {"upstream_inference_cost": 0.0000042},
                    },
                },
            )

        history = HistoryPredictor.fit((Task("dev", 0, (Step(1, Call.search("q"), 1),)),))
        agent = AgentState("a", 0, 0, "thinking", 0)
        state = Observation(0, "a", 0, Call.search("q"), 3, 0, Snapshot(3, 10, (agent,)))
        model = JevPredictor(
            history,
            base_url="https://openrouter.ai/api/alpha",
            model="typesafe/jev-1.14",
            api_key="test-secret",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(model.predict(state, agent).next_probability, 0.5)
        self.assertEqual(model.records[0]["cost_usd"], 0.0000042)
        self.assertEqual(model.records[0]["cost_source"], "provider")
        self.assertNotIn("test-secret", json.dumps(model.records))

    def test_malformed_decisions_response_keeps_billed_usage(self):
        import httpx

        history = HistoryPredictor.fit((Task("dev", 0, (Step(1, Call.search("q"), 1),)),))
        agent = AgentState("a", 0, 0, "thinking", 0)
        state = Observation(0, "a", 0, Call.search("q"), 3, 0, Snapshot(3, 10, (agent,)))
        model = JevPredictor(
            history,
            api_key="fixture",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"usage": {"cost": 0.01}})
            ),
        )
        with self.assertRaises(ValueError):
            model.predict(state, agent)
        self.assertEqual(model.records[0]["cost_usd"], 0.01)
        self.assertEqual(model.records[0]["failure"], "ValueError")


class ParallelAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def httpx_module(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("Requires live extras")
        return httpx

    async def test_required_search_proceeds_while_admission_is_running(self):
        from quota_spec.gateway import Gateway

        entered = asyncio.Event()
        required_executed = threading.Event()
        loop = asyncio.get_running_loop()

        class Policy:
            def admit(self, state):
                loop.call_soon_threadsafe(entered.set)
                if not required_executed.wait(timeout=1):
                    raise AssertionError("Required work waited for optional admission")
                return True

        class Main(MockQA):
            async def decide(self, question, history, final=False):
                if not history:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                return await super().decide(question, history, final)

        async def tool(call):
            required_executed.set()
            return []

        gateway = Gateway(tool, policy=Policy())
        try:
            result = await run_agent(
                {"task_id": "a", "task_context": "q"},
                gateway,
                Main(),
                max_calls=1,
                speculator=MockSpeculator(),
            )
            self.assertIsNone(result["failure"])
            self.assertTrue(required_executed.is_set())
            calls = [e for e in gateway.events if e["event"] == "call_started"]
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0]["speculative"])
            self.assertFalse(gateway.agents)
        finally:
            required_executed.set()
            await gateway.close()

    async def test_queued_admission_is_cancelled_before_task_finishes(self):
        from quota_spec.gateway import Gateway

        class Main(MockQA):
            async def decide(self, *args, **kwargs):
                await asyncio.sleep(0.005)
                return await super().decide(*args, **kwargs)

        async def tool(call):
            return []

        gateway = Gateway(tool)
        await gateway.prediction_lock.acquire()
        try:
            await asyncio.wait_for(
                run_agent(
                    {"task_id": "a", "task_context": "q"},
                    gateway,
                    Main(),
                    max_calls=1,
                    speculator=MockSpeculator(),
                ),
                timeout=1,
            )
            gateway.prediction_lock.release()
            await asyncio.sleep(0)
            self.assertFalse(gateway.agents)
            self.assertFalse(gateway.registry)
            self.assertEqual(len([e for e in gateway.events if e["event"] == "call_started"]), 1)
        finally:
            if gateway.prediction_lock.locked():
                gateway.prediction_lock.release()
            await gateway.close()

    async def test_queued_proposal_cannot_reappear_in_a_later_phase(self):
        from quota_spec.gateway import Gateway

        submitted = []

        class RecordingGateway(Gateway):
            async def speculate(self, task_id, call):
                try:
                    return await super().speculate(task_id, call)
                finally:
                    submitted.append(call)

        class Main(MockQA):
            async def decide(self, question, history, final=False):
                await asyncio.sleep(0.005)
                if not history:
                    return {"action": "search", "query": question}
                gateway.prediction_lock.release()
                await asyncio.sleep(0.005)
                return {"action": "answer", "answer": "done"}

        class FirstDraft(MockSpeculator):
            async def propose(self, question, history):
                return "old proposal" if not history else None

        async def tool(call):
            return []

        gateway = RecordingGateway(tool)
        await gateway.prediction_lock.acquire()
        try:
            await run_agent(
                {"task_id": "a", "task_context": "q"},
                gateway,
                Main(),
                max_calls=2,
                speculator=FirstDraft(),
            )
            starts = [e for e in gateway.events if e["event"] == "call_started"]
            self.assertEqual(len(starts), 1)
            self.assertFalse(starts[0]["speculative"])
            self.assertEqual(submitted, [Call.search("old proposal")])
        finally:
            if gateway.prediction_lock.locked():
                gateway.prediction_lock.release()
            await gateway.close()

    async def test_chat_options_and_billed_cost_are_preserved_on_parse_failure(self):
        httpx = self.httpx_module()

        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["reasoning"], {"effort": "low"})
            self.assertEqual(payload["provider"], {"sort": "latency"})
            self.assertEqual(payload["response_format"], {"type": "json_object"})
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost": 0.00001},
                },
            )

        with patch.dict(
            "os.environ",
            {
                "QA_REASONING_EFFORT": "low",
                "QA_RESPONSE_FORMAT": "json_object",
                "QA_PROVIDER_SORT": "latency",
            },
        ):
            model = HTTPQA(
                url="http://test/chat/completions",
                model="fixture",
                input_price=100,
                output_price=100,
                transport=httpx.MockTransport(handler),
            )
        with self.assertRaises(ValueError):
            await model.decide("q", [])
        self.assertEqual(model.records[0]["cost_usd"], 0.00001)
        self.assertEqual(model.records[0]["finish_reason"], "length")

    async def test_cancelled_http_request_has_unknown_cost_and_is_not_a_failure(self):
        httpx = self.httpx_module()

        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.sleep(10)

        model = HTTPQA(
            url="http://test/chat/completions",
            model="fixture",
            transport=httpx.MockTransport(handler),
        )
        task = asyncio.create_task(model.decide("q", []))
        await entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        usage = summarize_inference(model.records)
        self.assertEqual((usage["requests"], usage["cancelled"], usage["failures"]), (1, 1, 0))
        self.assertIsNone(usage["cost_usd"])
