import asyncio
import unittest
from dataclasses import replace

from quota_spec.admission import AdmissionConfig, Demand, PredictiveAdmission, rollout
from quota_spec.models import AgentState, Call, Observation, Snapshot, Step, Task
from quota_spec.prediction import Forecast, HistoryPredictor, bounded_context, calibration
from quota_spec.replay import Replay


class Constant:
    def predict(self, state, agent):
        delay = 4 if agent.task_id == "a" else 2
        return Forecast(1, 1, (delay,), (1,), 0)


def state(deadline=None):
    agents = (AgentState("a", 0, 0, "thinking", 0), AgentState("b", 0, 0, "thinking", 0, deadline))
    return Observation(0, "a", 0, Call.search("q"), 1, 0, Snapshot(1, 10, agents))


class PredictionTests(unittest.TestCase):
    def test_cross_agent_ablation_with_identical_forecasts(self):
        full = PredictiveAdmission(Constant(), AdmissionConfig(samples=4, overhead_s=0))
        own = PredictiveAdmission(Constant(), full.config, own_only=True)
        self.assertFalse(full.admit(state()))
        self.assertTrue(own.admit(state()))
        self.assertEqual(full.last_decision["owner_gain_s"], own.last_decision["owner_gain_s"])

    def test_incremental_deadline_risk_blocks_positive_mean_gain(self):
        # A saves 7 s, B loses 3 s, but B's deadline becomes missed.
        class Forecasts:
            def predict(self, observed, agent):
                return Forecast(
                    1,
                    1,
                    (4 if agent.task_id == "a" else 2,),
                    (5 if agent.task_id == "a" else 1,),
                    0,
                )

        p = PredictiveAdmission(Forecasts(), AdmissionConfig(samples=4, overhead_s=0, epsilon=0))
        self.assertFalse(p.admit(state(3)))
        self.assertGreater(p.last_decision["estimated_gain_s"], 0)
        self.assertEqual(p.last_decision["incremental_miss_risk"], 1)

    def test_horizon_does_not_reward_demand_beyond_boundary(self):
        p = PredictiveAdmission(Constant(), AdmissionConfig(horizon_s=1, overhead_s=0))
        self.assertFalse(p.admit(state()))

    def test_timeout_or_invalid_forecast_falls_back_to_rejection(self):
        class Broken:
            def predict(self, *_):
                raise TimeoutError("late")

        p = PredictiveAdmission(Broken())
        self.assertFalse(p.admit(state()))
        self.assertEqual(p.last_decision["fallback"], "TimeoutError")
        for probability in (float("nan"), -0.1, 1.1):
            with self.assertRaises(ValueError):
                Forecast(probability, 1, (1,), (1,), 0)

    def test_context_rejects_future_and_bounds_excerpts(self):
        agent = replace(
            state().snapshot.agents[0], result_excerpt="x" * 5000, task_context="q" * 5000
        )
        context = bounded_context(state(), agent)
        self.assertEqual(len(context["excerpt"]), 1024)
        self.assertEqual(len(context["task"]), 2048)
        self.assertNotIn("history", bounded_context(state(), agent, "no_history"))
        self.assertNotIn("phase", bounded_context(state(), agent, "no_progress"))
        with self.assertRaises(ValueError):
            bounded_context(state(), replace(agent, observed_at_s=1))

    def test_snapshots_only_show_arrived_agents_and_observed_results(self):
        snapshots = []

        class Inspect:
            def admit(self, observed):
                snapshots.append(observed)
                return False

        a = Task(
            "a", 0, (Step(1, Call.search("x"), 1, Call.search("y"), 1, "secret-after-result"),)
        )
        b = Task("b", 10, (Step(1, Call.search("b"), 1),))
        Replay((a, b), 2, 10).run(Inspect())
        self.assertEqual([x.task_id for x in snapshots[0].snapshot.agents], ["a"])
        self.assertEqual(snapshots[0].snapshot.agents[0].result_excerpt, "")
        self.assertTrue(
            all(a.observed_at_s <= s.now_s for s in snapshots for a in s.snapshot.agents)
        )

    def test_history_and_calibration_use_real_labels(self):
        task = Task("dev", 0, (Step(2, Call.search("x"), 1, Call.search("x"), 1),))
        p = HistoryPredictor.fit((task,))
        forecast = p.predict(state(), state().snapshot.agents[0])
        self.assertEqual(p.training_ids, ("dev",))
        self.assertEqual(forecast.delays_s, (2,))
        self.assertEqual(calibration([(1, True), (0, False)])["brier"], 0)
        self.assertIsNone(calibration([])["brier"])

    def test_quota_debt_and_dependency_shift_in_rollout(self):
        s = state()
        scenario = {"a": (Demand(4, 1, s.candidate),), "b": (Demand(2, 1, Call.search("b")),)}
        self.assertEqual(rollout(s, scenario, False, 0, 30), {"a": 11, "b": 3})
        self.assertEqual(rollout(s, scenario, True, 0, 30), {"a": 4, "b": 11})

    def test_rollout_preserves_queued_fifo_at_refill_ties(self):
        # C's original future arrival at refill cannot jump B's earlier quota wait.
        s = state()
        s = replace(
            s,
            snapshot=replace(
                s.snapshot, agents=(*s.snapshot.agents, AgentState("c", 0, 0, "thinking", 0))
            ),
        )
        scenario = {
            "a": (Demand(0, 1, Call.search("a")),),
            "b": (Demand(2, 1, Call.search("b")),),
            "c": (Demand(10, 1, Call.search("c")),),
        }
        result = rollout(s, scenario, False, 0, 40)
        self.assertEqual(result, {"a": 1, "b": 11, "c": 21})


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            __import__("httpx")
        except ImportError:
            raise unittest.SkipTest("Install .[live] for adapter tests")

    def history(self):
        return HistoryPredictor.fit((Task("dev", 0, (Step(2, Call.search("x"), 1),)),))

    def test_system_one_contract_usage_and_no_future_input(self):
        import httpx

        from quota_spec.adapters import SystemOnePredictor

        def handler(request):
            import json

            payload = json.loads(request.content)
            self.assertNotIn("steps", payload["state"])
            return httpx.Response(
                200,
                json={
                    "model": "pinned-model",
                    "answers": {
                        "reuse": {"noul": 0.8},
                        "next": {"noul": 1},
                        "continues": {"noul": 0.2},
                    },
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                },
            )

        adapter = SystemOnePredictor(
            self.history(),
            base_url="http://test",
            model="test",
            transport=httpx.MockTransport(handler),
        )
        prediction = adapter.predict(state(), state().snapshot.agents[0])
        self.assertEqual(prediction.reuse_probability, 0.8)
        self.assertEqual(adapter.records[0]["input_tokens"], 100)
        self.assertIsNone(adapter.records[0]["cost_usd"])

    def test_total_request_timeout_and_failure_record(self):
        import httpx

        from quota_spec.adapters import SystemOnePredictor

        async def handler(request):
            await asyncio.sleep(1)
            return httpx.Response(200)

        adapter = SystemOnePredictor(
            self.history(),
            base_url="http://test",
            model="test",
            timeout_s=0.01,
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(ValueError):
            adapter.predict(state(), state().snapshot.agents[0])
        self.assertEqual(adapter.records[0]["failure"], "TimeoutError")
