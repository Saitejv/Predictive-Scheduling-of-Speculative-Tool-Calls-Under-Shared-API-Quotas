import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.collect_qa import collect, trajectory
from quota_spec.gateway import Gateway
from quota_spec.models import Call, load_tasks
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.qa import HTTPQA, MockQA, evaluate, run_agent
from quota_spec.replay import Replay
from quota_spec.search import SearchCorpus
from quota_spec.speculation import HTTPSpeculator, MockSpeculator, make_speculator
from quota_spec.telemetry import audit_pipeline


def source(path):
    path.mkdir()
    corpus = SearchCorpus([{"title": "Ada", "text": "Ada wrote algorithms."}])
    corpus.save(path / "corpus.json")
    for split, tid in (("development", "dev"), ("evaluation", "eval")):
        (path / f"{split}.json").write_text(
            json.dumps([{"task_id": tid, "task_context": "Who wrote algorithms?"}])
        )
    (path / "labels.json").write_text(
        json.dumps([{"task_id": tid, "answer": "PRIVATE-GOLD"} for tid in ("dev", "eval")])
    )
    (path / "manifest.json").write_text(json.dumps({"corpus_sha256": corpus.digest}))
    return corpus


class SpeculatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_proposal_is_independent_of_required_action_and_recorded_before_results(self):
        class Draft(MockSpeculator):
            async def propose(self, question, history):
                self_test.assertEqual(history, [])
                return "draft guess"

        class Main(MockQA):
            async def decide(self, *args, **kwargs):
                await asyncio.sleep(0.005)
                return await super().decide(*args, **kwargs)

        self_test = self
        result = await trajectory(
            {"task_id": "a", "task_context": "required query"},
            SearchCorpus([{"title": "Ada", "text": "observed later"}]),
            Main(),
            1,
            Draft(),
        )
        trace = load_tasks([result["trace"]])[0]
        self.assertEqual(trace.steps[0].required, Call.search("required query"))
        self.assertEqual(trace.steps[0].candidate, Call.search("draft guess"))
        self.assertEqual(result["observations"][0]["history"], [])
        self.assertEqual(result["observations"][0]["result_excerpt"], "")
        self.assertIsNone(trace.final_candidate)  # Search budget is exhausted.

    async def test_late_proposal_is_cancelled_without_delaying_required_search(self):
        main_started = asyncio.Event()
        cancelled = asyncio.Event()

        class Main(MockQA):
            async def decide(self, question, history, final=False):
                main_started.set()
                return await super().decide(question, history, final)

        class Draft(MockSpeculator):
            async def propose(self, question, history):
                await asyncio.wait_for(main_started.wait(), timeout=1)
                try:
                    await asyncio.sleep(10)
                    return question
                finally:
                    cancelled.set()

        result = await trajectory(
            {"task_id": "a", "task_context": "Ada"},
            SearchCorpus([{"title": "Ada", "text": "algorithms"}]),
            Main(),
            1,
            Draft(),
        )
        trace = load_tasks([result["trace"]])[0]
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(trace.steps[0].candidate)
        self.assertLess(trace.steps[0].think_s, 1)
        self.assertTrue(result["speculator_inference"][0]["cancelled"])
        replay = Replay((trace,), 3, 10).run(CurrentCapacity())
        dispatch = next(e for e in replay.events if e["event"] == "call_started")
        self.assertAlmostEqual(dispatch["time_s"], trace.steps[0].think_s)
        self.assertFalse(dispatch["speculative"])

    async def test_gateway_still_controls_acceptance_and_required_results(self):
        for policy, accepted in ((CurrentCapacity(), True), (NoSpeculation(), False)):
            started = asyncio.Event()

            class Main(MockQA):
                async def decide(self, question, history, final=False):
                    started.set()
                    await asyncio.sleep(0.01)
                    return await super().decide(question, history, final)

            class Draft(MockSpeculator):
                async def propose(self, question, history):
                    await asyncio.wait_for(started.wait(), timeout=1)
                    return question

            async def search(call):
                return [{"title": "Ada", "text": "algorithms"}]

            gateway = Gateway(search, capacity=3, window_s=10, policy=policy)
            try:
                result = await run_agent(
                    {"task_id": "a", "task_context": "Ada"},
                    gateway,
                    Main(),
                    max_calls=1,
                    speculator=Draft(),
                )
                calls = [e for e in gateway.events if e["event"] == "call_started"]
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["speculative"], accepted)
                self.assertEqual(result["history"][0]["query"], "Ada")
                self.assertEqual(result["history"][0]["results"][0]["title"], "Ada")
            finally:
                await gateway.close()

    async def test_failure_does_not_replace_or_block_required_action(self):
        class Broken(MockSpeculator):
            async def propose(self, question, history):
                raise TimeoutError("private exception details")

        draft = Broken()
        result = await trajectory(
            {"task_id": "a", "task_context": "Ada"},
            SearchCorpus([{"title": "Ada", "text": "algorithms"}]),
            MockQA(),
            1,
            draft,
        )
        self.assertEqual(result["trace"]["steps"][0]["query"], "Ada")
        self.assertIsNone(result["trace"]["steps"][0]["candidate_query"])
        self.assertEqual(draft.records[0]["failure"], "TimeoutError")
        self.assertNotIn("private exception details", json.dumps(result))

    async def test_resume_freezes_speculator_configuration_and_usage_is_separate(self):
        class Recorded(MockSpeculator):
            identity = "fixture-small-v1"

            async def propose(self, question, history):
                self.records.append(
                    {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "cost_usd": 0.001,
                        "failure": None,
                    }
                )
                return await super().propose(question, history)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source(root / "source")
            with patch("builtins.print"):
                await collect(
                    root / "source",
                    root / "traces",
                    count=2,
                    speculator_factory=Recorded,
                )
                with patch.object(Recorded, "propose", side_effect=AssertionError("new call")):
                    await collect(
                        root / "source",
                        root / "traces",
                        count=2,
                        speculator_factory=Recorded,
                        resume=True,
                    )
            usage = audit_pipeline(root)
            self.assertEqual(usage["collection_qa"]["requests"], 0)
            self.assertEqual(usage["collection_speculator"]["requests"], 4)
            self.assertAlmostEqual(usage["collection_speculator"]["cost_usd"], 0.004)
            with patch.object(Recorded, "identity", "changed-small-model"):
                with self.assertRaisesRegex(ValueError, "configuration"):
                    await collect(
                        root / "source",
                        root / "traces",
                        count=2,
                        speculator_factory=Recorded,
                        resume=True,
                    )


class HTTPDraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("Requires live extras")
        self.httpx = httpx

    def draft(self, action, payloads):
        def handler(request):
            payloads.append(json.loads(request.content))
            return self.httpx.Response(
                200,
                json={
                    "model": "small-v1",
                    "choices": [{"message": {"content": json.dumps(action)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                },
            )

        return HTTPSpeculator(
            url="http://test/v1/chat/completions",
            model="small",
            api_key="PRIVATE-KEY",
            transport=self.httpx.MockTransport(handler),
            input_price=1,
            output_price=2,
        )

    async def test_http_contract_bounded_observed_context_and_cost(self):
        requests = []
        draft = self.draft({"action": "search", "query": "Ada Lovelace"}, requests)
        from quota_spec.speculation import propose

        history = [
            {
                "query": "q" * 5000,
                "results": [{"title": "t" * 5000, "text": "x" * 5000} for _ in range(10)],
            }
            for _ in range(10)
        ]
        query = await propose(draft, "q" * 5000, history)
        self.assertEqual(query, "Ada Lovelace")
        user = json.loads(requests[0]["messages"][1]["content"])
        self.assertEqual(set(user), {"question", "history"})
        self.assertEqual(len(user["question"]), 2048)
        self.assertEqual(len(user["history"]), 4)
        self.assertEqual(len(user["history"][0]["query"]), 2048)
        self.assertEqual(len(user["history"][0]["results"]), 3)
        self.assertEqual(len(user["history"][0]["results"][0]["text"]), 1000)
        self.assertEqual(requests[0]["max_tokens"], 128)
        self.assertEqual(draft.records[0]["candidate_query"], query)
        self.assertAlmostEqual(draft.records[0]["cost_usd"], 0.000014)
        self.assertNotIn("PRIVATE-KEY", json.dumps(draft.records))

    async def test_skip_and_malformed_responses_never_launch_candidates(self):
        from quota_spec.speculation import propose

        for response, failed in (
            ({"action": "skip"}, False),
            ({"action": "search", "query": ""}, True),
            ({"action": "answer", "answer": "Ada"}, True),
        ):
            draft = self.draft(response, [])
            self.assertIsNone(await propose(draft, "Who?", []))
            self.assertEqual(bool(draft.records[0]["failure"]), failed)
            self.assertEqual(draft.records[0]["input_tokens"], 10)

    async def test_http_timeout_is_recorded_and_returns_no_candidate(self):
        from quota_spec.speculation import propose

        async def handler(request):
            await asyncio.sleep(1)
            return self.httpx.Response(200)

        draft = HTTPSpeculator(
            url="http://test/v1/chat/completions",
            model="small",
            timeout_s=0.01,
            transport=self.httpx.MockTransport(handler),
        )
        self.assertIsNone(await propose(draft, "Who?", []))
        self.assertEqual(draft.records[0]["failure"], "TimeoutError")

    async def test_http_collection_and_live_use_speculator_and_exclude_gold(self):
        requests = []

        draft = self.draft({"action": "search", "query": "Ada"}, requests)

        async def main_handler(request):
            await asyncio.sleep(0.005)
            user = json.loads(json.loads(request.content)["messages"][1]["content"])
            action = (
                {"action": "answer", "answer": "Ada"}
                if user["history"]
                else {"action": "search", "query": "Ada"}
            )
            return self.httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(action)}}],
                },
            )

        main_options = dict(
            url="http://main/v1/chat/completions",
            model="main",
            transport=self.httpx.MockTransport(main_handler),
        )
        draft_options = dict(
            url=draft.url,
            model=draft.model,
            transport=draft.transport,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source(root / "source")
            with patch("builtins.print"):
                await collect(
                    root / "source",
                    root / "traces",
                    count=2,
                    backend="http",
                    model_factory=lambda: HTTPQA(**main_options),
                    speculator_options=draft_options,
                )
            self.assertNotIn("PRIVATE-GOLD", json.dumps(requests))
            self.assertEqual(len(requests), 4)
            trace = json.loads((root / "traces/evaluation.json").read_text())[0]
            self.assertEqual(trace["steps"][0]["candidate_query"], "Ada")
            self.assertEqual(
                json.loads((root / "traces/manifest.json").read_text())["candidate_generator"],
                "http-speculator-v1",
            )
            summary = await evaluate(
                root / "source",
                root / "live",
                backend="http",
                count=1,
                max_calls=1,
                model_options=main_options,
                speculator_options=draft_options,
                policies={"current_capacity": CurrentCapacity()},
            )
            self.assertEqual(summary["current_capacity"]["speculator_usage"]["requests"], 1)
            usage = audit_pipeline(root)
            self.assertEqual(usage["live_speculator"]["requests"], 1)
            self.assertEqual(usage["live_qa"]["requests"], 2)
            self.assertEqual(usage["collection_speculator"]["requests"], 4)

    async def test_missing_speculator_config_fails_before_paid_main_inference(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            root = Path(directory)
            source(root / "source")
            with patch.object(
                HTTPQA,
                "decide",
                side_effect=AssertionError("paid main call"),
            ):
                with self.assertRaisesRegex(ValueError, "SPECULATOR_CHAT_URL"):
                    await collect(
                        root / "source",
                        root / "traces",
                        backend="http",
                        count=2,
                        model_factory=lambda: HTTPQA(url="http://main", model="main"),
                    )
            self.assertFalse((root / "traces").exists())
            with self.assertRaisesRegex(ValueError, "backend=http"):
                make_speculator("http", backend="mock")
