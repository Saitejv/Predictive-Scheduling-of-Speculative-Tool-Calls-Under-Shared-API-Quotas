"""Regression coverage for boundary, concurrency and credential-free integration bugs."""

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from quota_spec.admission import (
    AdmissionConfig,
    Demand,
    PredictiveAdmission,
    rollout,
    sample_scenarios,
)
from quota_spec.experiments import summarize
from quota_spec.gateway import Gateway
from quota_spec.models import AgentState, Call, KnownExecution, Observation, Snapshot, Step, Task
from quota_spec.policies import CurrentCapacity
from quota_spec.prediction import Forecast, HistoryPredictor
from quota_spec.qa import HTTPQA, MockQA, answer_scores, parse_action, run_agent
from quota_spec.quota import FixedWindowQuota
from quota_spec.replay import Replay


def observed():
    return Observation(
        0, "a", 0, Call.search("q"), 1, 0, Snapshot(1, 10, (AgentState("a", 0, 0, "thinking", 0),))
    )


def history():
    return HistoryPredictor.fit((Task("dev", 0, (Step(1, Call.search("x"), 1),)),))


class CoreRegressionTests(unittest.TestCase):
    def test_integer_budgets_reject_bool_and_fractional_values(self):
        for value in (True, 1.5, 0):
            with self.assertRaises(ValueError):
                AdmissionConfig(samples=value)
            with self.assertRaises(ValueError):
                AdmissionConfig(max_calls=value)

    def test_exact_call_identity_canonicalizes_json_only(self):
        self.assertEqual(Call("search", '{"query":"x"}'), Call.search("x"))
        self.assertNotEqual(Call.search("x"), Call.search(" x"))
        for value in ("", " ", None, 3):
            with self.assertRaises(ValueError):
                Call.search(value)

    def test_clock_cannot_go_backwards_in_same_window(self):
        quota = FixedWindowQuota(2, 10)
        quota.consume(5)
        with self.assertRaises(ValueError):
            quota.remaining(4)

    def test_completed_zero_think_step_cannot_speculate_after_finish(self):
        task = Task("a", 0, (Step(0, Call.search("x"), 0, Call.search("wrong"), 1),))
        result = Replay((task,), 3, 10).run(CurrentCapacity())
        self.assertEqual(result.metrics["calls_started"], 1)

    def test_replay_does_not_expose_hidden_execution_duration(self):
        snapshots = []

        class Inspect:
            def admit(self, state):
                snapshots.append(state)
                return False

        running = Task("running", 0, (Step(0, Call.search("slow"), 100),))
        other = Task("other", 1, (Step(1, Call.search("q"), 1, Call.search("hint"), 1),))
        Replay((running, other), 3, 10, expected_duration_s=2).run(Inspect())
        execution = snapshots[0].snapshot.executions[0]
        self.assertEqual(execution.finish_s, 2)
        self.assertNotEqual(execution.finish_s, 100)

    def test_running_agent_is_passed_with_observed_count(self):
        seen = []

        class Inspect:
            def predict(self, state, agent):
                seen.append(agent)
                return Forecast(1, 0, (1,), (1,), 0)

        s = observed()
        agent = replace(s.snapshot.agents[0], phase="running")
        sample_scenarios(
            replace(s, snapshot=replace(s.snapshot, agents=(agent,))), Inspect(), AdmissionConfig()
        )
        self.assertEqual(seen[0].completed_calls, 0)

    def test_history_running_final_step_does_not_always_forecast_more(self):
        agent = replace(observed().snapshot.agents[0], phase="running")
        self.assertLess(history().predict(observed(), agent).next_probability, 1)

    def test_horizon_deadline_does_not_turn_late_completion_into_success(self):
        s = observed()
        finishes = rollout(s, {"a": (Demand(0, 20, Call.search("x")),)}, False, 0, 10)
        self.assertGreater(finishes["a"], 10)
        finishes = rollout(s, {"a": (Demand(10, 0, Call.search("x")),)}, False, 0, 10)
        self.assertEqual(finishes["a"], 10)

    def test_overdue_execution_estimate_does_not_roll_clock_backwards(self):
        s = observed()
        agent = replace(
            s.snapshot.agents[0], observed_at_s=5, phase="running", history=(Call.search("old"),)
        )
        s = replace(
            s,
            now_s=5,
            snapshot=replace(
                s.snapshot,
                agents=(agent,),
                executions=(KnownExecution("a", Call.search("old"), 2),),
            ),
        )
        finishes = rollout(s, {"a": (Demand(0, 1, Call.search("next")),)}, False, 0, 10)
        self.assertEqual(finishes["a"], 6)

    def test_required_wait_aggregation_is_per_request(self):
        a = Task("a", 0, (Step(0, Call.search("a"), 1), Step(0, Call.search("b"), 1)))
        b = Task("b", 0, (Step(0, Call.search("c"), 1),))
        results = [Replay((a,), 1, 10).run(), Replay((b,), 1, 10).run()]
        self.assertEqual(summarize(results)["mean_required_wait_s"], 3)

    def test_small_collection_pilot_stays_inside_development(self):
        from quota_spec.collect import prepare

        rows = [
            {
                "row": {
                    "id": f"row-{i}",
                    "question": "Which topic?",
                    "answer": "topic",
                    "context": {"title": ["topic"], "sentences": [["A topic document."]]},
                    "supporting_facts": {"title": ["topic"]},
                }
            }
            for i in range(20)
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("urllib.request.urlopen", side_effect=AssertionError("network")),
            patch("builtins.print"),
        ):
            output = Path(directory)
            (output / "raw").mkdir()
            (output / "raw/hotpot-page-0.json").write_text(json.dumps({"rows": rows}))
            prepare(output, count=20, think_s=0, service_s=0)
            pilot = json.loads((output / "pilot.json").read_text())
            development = json.loads((output / "development.json").read_text())
            evaluation = json.loads((output / "evaluation.json").read_text())
            self.assertTrue({t["task_id"] for t in pilot} <= {t["task_id"] for t in development})
            self.assertFalse({t["task_id"] for t in pilot} & {t["task_id"] for t in evaluation})
            with self.assertRaises(ValueError):
                prepare(output, count=20)

    def test_preflight_never_connects_by_default(self):
        from quota_spec.preflight import inspect

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("urllib.request.urlopen", side_effect=AssertionError("network")),
            patch("builtins.print"),
        ):
            report = inspect(Path(directory))
        self.assertEqual(
            report["kev"]["selected_artifact"]["metadata_status"], "not_probed_offline"
        )

    def test_answer_scoring_and_schema(self):
        self.assertEqual(answer_scores("The Eiffel Tower!", "Eiffel Tower")["exact_match"], 1)
        self.assertEqual(answer_scores("yes", "yes indeed")["f1"], 0)
        self.assertEqual(answer_scores("red blue", "red green")["f1"], 0.5)
        with self.assertRaises(ValueError):
            parse_action({"action": "search", "query": "q"}, final=True)


class GatewayRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.release = asyncio.Event()

        async def tool(call):
            await self.release.wait()
            return [{"title": "x", "text": "observed"}]

        self.gateway = Gateway(tool, capacity=5, window_s=10)

    async def asyncTearDown(self):
        self.release.set()
        await self.gateway.close()

    async def test_duplicate_waiters_increment_progress_once(self):
        tasks = [
            asyncio.create_task(self.gateway.required("a", Call.search("x"))) for _ in range(10)
        ]
        await asyncio.sleep(0.01)
        self.release.set()
        await asyncio.gather(*tasks)
        self.assertEqual(self.gateway.agents["a"].completed_calls, 1)
        self.assertEqual(len(self.gateway.agents["a"].history), 1)
        self.assertEqual(len(self.gateway.recent_required), 1)

    async def test_speculative_join_is_running_and_progress_survives_disconnect(self):
        await self.gateway.speculate("a", Call.search("x"))
        waiter = asyncio.create_task(self.gateway.required("a", Call.search("x")))
        await asyncio.sleep(0.001)
        self.assertEqual(self.gateway.agents["a"].phase, "running")
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.release.set()
        await self.gateway.registry["a", Call.search("x")].worker
        self.assertEqual(self.gateway.agents["a"].completed_calls, 1)
        self.assertEqual(self.gateway.agents["a"].phase, "thinking")

    async def test_cancel_before_worker_starts_does_not_poison_registry(self):
        await self.gateway.speculate("a", Call.search("x"))
        entry = self.gateway.registry["a", Call.search("x")]
        entry.worker.cancel()
        await asyncio.gather(entry.worker, return_exceptions=True)
        await asyncio.sleep(0)
        self.assertNotIn(("a", Call.search("x")), self.gateway.registry)
        self.assertTrue(entry.future.cancelled())
        self.assertEqual(self.gateway.quota.remaining(self.gateway.now()), 4)

    async def test_only_one_candidate_per_observed_step(self):
        self.assertTrue(await self.gateway.speculate("a", Call.search("x")))
        self.assertFalse(await self.gateway.speculate("a", Call.search("y")))

    async def test_distinct_concurrent_required_calls_are_rejected(self):
        first = asyncio.create_task(self.gateway.required("a", Call.search("x")))
        await asyncio.sleep(0.001)
        with self.assertRaises(ValueError):
            await self.gateway.required("a", Call.search("y"))
        self.release.set()
        await first

    async def test_finished_task_excluded_from_future_predictions(self):
        await self.gateway.speculate("a", Call.search("x"))
        await self.gateway.finish_task("a")
        self.assertNotIn("a", self.gateway.agents)

    async def test_finishing_releases_cached_results_for_task_id_reuse(self):
        self.release.set()
        await self.gateway.required("a", Call.search("x"))
        await self.gateway.finish_task("a")
        self.assertFalse(self.gateway.registry)
        await self.gateway.required("a", Call.search("x"))
        starts = [e for e in self.gateway.events if e["event"] == "call_started"]
        self.assertEqual(len(starts), 2)

    async def test_mock_qa_uses_gateway_and_never_scores_gold(self):
        self.release.set()
        result = await run_agent(
            {"task_id": "a", "task_context": "question"}, self.gateway, MockQA()
        )
        self.assertEqual(result["answer"], "mock answer")
        self.assertEqual(len(result["history"]), 1)
        self.assertNotIn("a", self.gateway.agents)


class HTTPRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            __import__("httpx")
        except ImportError:
            raise unittest.SkipTest("Install .[live] for HTTP contracts")

    def test_both_predictor_contracts_and_versioned_base_url(self):
        import httpx

        from quota_spec.adapters import JevPredictor, KevPredictor

        for cls in (JevPredictor, KevPredictor):

            def handler(request):
                self.assertEqual(request.url.path, "/v1/systemone")
                self.assertEqual(request.headers["Authorization"], "Bearer offline-test-token")
                return httpx.Response(
                    200,
                    json={
                        "answers": {k: {"noul": 0.5} for k in ("reuse", "next", "continues")},
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    },
                )

            predictor = cls(
                history(),
                api_key="offline-test-token",
                base_url="http://test/v1",
                transport=httpx.MockTransport(handler),
                input_usd_per_million=1,
                output_usd_per_million=2,
            )
            predictor.predict(observed(), observed().snapshot.agents[0])
            self.assertEqual(predictor.records[0]["cost_usd"], 14 / 1e6)

    def test_failed_inference_latency_is_charged_to_replay(self):
        import httpx

        from quota_spec.adapters import SystemOnePredictor

        async def handler(request):
            await asyncio.sleep(0.02)
            return httpx.Response(429)

        predictor = SystemOnePredictor(
            history(),
            base_url="http://test",
            model="fixture",
            transport=httpx.MockTransport(handler),
        )
        policy = PredictiveAdmission(predictor, AdmissionConfig(overhead_s=0))
        task = Task("a", 0, (Step(0.001, Call.search("q"), 0.001, Call.search("q"), 0.001),))
        result = Replay((task,), 1, 10).run(policy)
        self.assertGreater(result.metrics["modeled_decision_overhead_s"], 0.015)
        self.assertGreater(result.metrics["mean_completion_s"], 0.015)
        self.assertIsNotNone(predictor.records[0]["failure"])

    def test_invalid_api_responses_fail_closed(self):
        import httpx

        from quota_spec.adapters import SystemOnePredictor

        bodies = [
            [],
            {"answers": None},
            {"answers": {k: {"noul": True} for k in ("reuse", "next", "continues")}},
            {
                "answers": {k: {"noul": 0.5} for k in ("reuse", "next", "continues")},
                "usage": {"input_tokens": -1},
            },
        ]
        for body in bodies:
            predictor = SystemOnePredictor(
                history(),
                base_url="http://test",
                model="fixture",
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
            )
            policy = PredictiveAdmission(predictor)
            self.assertFalse(policy.admit(observed()))
            self.assertIsNotNone(predictor.records[0]["failure"])

    def test_response_size_and_decision_timeout_are_bounded(self):
        import httpx

        from quota_spec.adapters import SystemOnePredictor

        predictor = SystemOnePredictor(
            history(),
            base_url="http://test",
            model="fixture",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * 70000)
            ),
        )
        with self.assertRaises(ValueError):
            predictor.predict(observed(), observed().snapshot.agents[0])

        async def slow(request):
            await asyncio.sleep(0.03)
            return httpx.Response(
                200, json={"answers": {k: {"noul": 0.5} for k in ("reuse", "next", "continues")}}
            )

        predictor = SystemOnePredictor(
            history(),
            base_url="http://test",
            model="fixture",
            timeout_s=1,
            decision_timeout_s=0.01,
            transport=httpx.MockTransport(slow),
        )
        self.assertFalse(PredictiveAdmission(predictor).admit(observed()))
        self.assertEqual(predictor.records[-1]["failure"], "TimeoutError")

    def test_qa_http_contract_without_network(self):
        import httpx

        def handler(request):
            body = json.loads(request.content)
            self.assertNotIn("gold", json.dumps(body))
            self.assertEqual(request.headers["Authorization"], "Bearer offline-test-token")
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"action":"answer","answer":"Ada"}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                },
            )

        model = HTTPQA(
            url="http://test/v1/chat/completions",
            model="fixture",
            api_key="offline-test-token",
            transport=httpx.MockTransport(handler),
            input_price=1,
            output_price=2,
        )
        result = asyncio.run(model.decide("Who?", [], True))
        self.assertEqual(result["answer"], "Ada")
        self.assertEqual(model.records[0]["cost_usd"], 14 / 1e6)
