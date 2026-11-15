import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.adapters import MockSystemOnePredictor
from quota_spec.capture_audit import audit
from quota_spec.context_engine import ContextCoordinator, ForecastCache, SharedSearch
from quota_spec.hotpot_runtime import MockSearch
from quota_spec.multi_agent import ObservedEvents, parser, run
from quota_spec.prediction import Forecast


class History:
    def predict(self, state, agent):
        return Forecast(0.95, 1, (0.01,), (0.03,), 0)


class ContextTests(unittest.IsolatedAsyncioTestCase):
    def setup_engine(self, **kwargs):
        events = ObservedEvents()
        c = ContextCoordinator(events, **kwargs)
        events.coordinator = c
        events.emit("episode_started", episode="a", question="Only observed question")
        return events, c

    async def test_required_fifo_and_atomic_optional_claims(self):
        events, c = self.setup_engine(capacity=1, window_s=0.04, policy="current_capacity")
        self.assertTrue(c.claim_candidate("a", "optional"))
        self.assertFalse(c.claim_candidate("a", "other"))
        first = asyncio.create_task(c.acquire_required("a", "first"))
        second = asyncio.create_task(c.acquire_required("b", "second"))
        await asyncio.sleep(0.005)
        self.assertFalse(c.claim_candidate("a", "wrong"))
        await asyncio.gather(first, second)
        claims = [e for e in events.rows if e["event"] == "quota_claimed"]
        self.assertEqual([e["query"] for e in claims], ["optional", "first", "second"])
        self.assertEqual([e["window_index"] for e in claims], [0, 1, 2])

    async def test_candidate_retained_until_refill_but_expires_at_answer(self):
        _, c = self.setup_engine(capacity=1, window_s=0.04, policy="current_capacity")
        c.claim_candidate("a", "one")
        pending = asyncio.create_task(c.admit_candidate("a", "two", lambda: True))
        await asyncio.sleep(0.005)
        self.assertFalse(pending.done())
        self.assertTrue(await pending)
        self.assertTrue(c.claim_candidate("a", "two"))
        valid = True
        late = asyncio.create_task(c.admit_candidate("a", "three", lambda: valid))
        valid = False
        self.assertFalse(await late)

    async def test_snapshot_has_only_observed_progress_and_no_optional_result(self):
        events, c = self.setup_engine(policy="current_capacity")
        events.emit("required_action", episode="a", action="Search[known]", step=1)
        state = c.observation("a", "candidate")
        self.assertEqual(state.snapshot.agents[0].result_excerpt, "")
        self.assertEqual(len(state.snapshot.agents[0].history), 1)
        events.emit(
            "tool_observed",
            episode="a",
            action="Search[known]",
            step=1,
            observation="real observation",
            done=False,
        )
        self.assertEqual(
            c.observation("a", "candidate").snapshot.agents[0].result_excerpt, "real observation"
        )
        search = SharedSearch(MockSearch(events), c)
        self.assertTrue(c.claim_candidate("a", "optional"))
        await search.search("optional", "a", 2, True)
        self.assertEqual(c.agents["a"].result_excerpt, "real observation")
        self.assertEqual(c.agents["a"].completed_calls, 1)

    async def test_cached_demand_singleflight_is_bounded_and_audited(self):
        _, c = self.setup_engine()
        cache = ForecastCache(
            lambda: MockSystemOnePredictor(
                History(), input_usd_per_million=0, output_usd_per_million=0
            ),
            max_requests=1,
        )
        state = c.observation("a", "candidate")
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network")):
            values = await asyncio.gather(*(cache.forecast(state, c.agents["a"]) for _ in range(4)))
        self.assertEqual(len(values), 4)
        self.assertEqual(cache.requests, 1)
        self.assertEqual(cache.hits, 3)
        self.assertEqual(
            cache.records[0]["input"]["candidate"]["arguments_json"],
            json.dumps({"query": "candidate"}, sort_keys=True),
        )
        self.assertNotIn("reference_answer", str(cache.records))
        self.assertEqual(cache.reserved, 0)
        with self.assertRaises(ValueError):
            await cache.forecast(c.observation("a", "different"), c.agents["a"])

    async def test_context_modes_retain_exact_declared_inputs(self):
        _, c = self.setup_engine()
        for mode in ("task", "history", "progress", "no_history", "no_progress"):
            cache = ForecastCache(
                lambda: MockSystemOnePredictor(
                    History(), context=mode, input_usd_per_million=0, output_usd_per_million=0
                ),
                mode=mode,
            )
            await cache.forecast(c.observation("a", "candidate"), c.agents["a"])
            context = cache.records[0]["input"]
            self.assertEqual("history" in context, mode in ("history", "progress", "no_progress"))
            self.assertEqual("phase" in context, mode in ("progress", "no_history"))
            self.assertEqual(
                "excerpt" in context, mode in ("progress", "no_history", "no_progress")
            )
            self.assertEqual(cache.records[0]["context"], mode)

    async def test_context_changes_reject_late_decision_without_spending_quota(self):
        events, c = self.setup_engine(history=History())

        class Slow:
            async def forecast(self, state, agent):
                await asyncio.sleep(0.01)
                events.emit(
                    "tool_observed",
                    episode="a",
                    step=state.completed_calls + 1,
                    observation="fresh",
                    action="Lookup[x]",
                    done=False,
                )
                return History().predict(state, agent)

        c.forecasts = Slow()
        self.assertFalse(await c.admit_candidate("a", "draft", lambda: True))
        self.assertEqual(c.decisions[-1]["reason"], "context_changed")
        self.assertEqual(c.quota.used, 0)

    async def test_failed_forecast_fails_closed_and_required_work_continues(self):
        events, c = self.setup_engine(history=History())

        class Broken:
            async def forecast(self, state, agent):
                raise ValueError("provider failed")

        c.forecasts = Broken()
        self.assertFalse(await c.admit_candidate("a", "draft", lambda: True))
        result = await SharedSearch(MockSearch(events), c).search("real", "a", 1)
        self.assertIn("obs", result)
        self.assertEqual(c.decisions[-1]["reason"], "forecast_failed")
        self.assertEqual(c.quota.used, 1)

    async def test_cancelled_required_queue_does_not_deadlock_next_request(self):
        _, c = self.setup_engine(capacity=1, window_s=0.04, policy="current_capacity")
        c.claim_candidate("a", "one")
        first = asyncio.create_task(c.acquire_required("a", "cancel"))
        second = asyncio.create_task(c.acquire_required("b", "keep"))
        await asyncio.sleep(0.005)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        await asyncio.wait_for(second, 0.2)
        self.assertFalse(c.queue)

    async def test_live_full_rule_protects_other_agent_with_identical_forecasts(self):
        decisions = []
        inputs = []
        for policy in ("jev_full", "jev_own"):
            events, c = self.setup_engine(capacity=1, window_s=10, policy=policy)
            events.emit("episode_started", episode="b", question="Other observed question")

            class Fixed:
                async def forecast(self, state, agent):
                    inputs.append((policy, agent.task_id))
                    return Forecast(1, 1, (4 if agent.task_id == "a" else 2,), (1,), 0)

            c.forecasts = Fixed()
            decisions.append(await c.admit_candidate("a", "q", lambda: True))
        self.assertEqual(decisions, [False, True])
        self.assertEqual(
            inputs, [("jev_full", "a"), ("jev_full", "b"), ("jev_own", "a"), ("jev_own", "b")]
        )

    async def test_final_claim_rejects_sibling_approval_on_old_quota_ledger(self):
        _, c = self.setup_engine(capacity=3, policy="history_full", history=History())
        self.assertTrue(await c.admit_candidate("a", "one", lambda: True))
        self.assertTrue(await c.admit_candidate("a", "two", lambda: True))
        self.assertTrue(c.claim_candidate("a", "one"))
        self.assertFalse(c.claim_candidate("a", "two"))
        self.assertEqual(c.quota.used, 1)

    async def test_forecast_budget_reserves_concurrent_requests_and_drains_cancelled_waiter(self):
        import time

        class Slow(MockSystemOnePredictor):
            def predict(self, state, agent):
                time.sleep(0.02)
                return super().predict(state, agent)

        _, c = self.setup_engine()
        cache = ForecastCache(
            lambda: Slow(History(), input_usd_per_million=0, output_usd_per_million=0),
            max_usd=0.015,
            request_reserve_usd=0.01,
        )
        one = asyncio.create_task(cache.forecast(c.observation("a", "one"), c.agents["a"]))
        await asyncio.sleep(0.005)
        with self.assertRaises(ValueError):
            await cache.forecast(c.observation("a", "two"), c.agents["a"])
        one.cancel()
        await asyncio.gather(one, return_exceptions=True)
        self.assertEqual(cache.requests, 1)
        self.assertEqual(len(cache.records), 1)
        self.assertEqual(cache.reserved, 0)
        self.assertFalse(cache.inflight)

    async def test_multiagent_runtime_runs_real_orchestration_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            args = parser().parse_args(
                [
                    "--backend",
                    "mock",
                    "--agents",
                    "4",
                    "--count",
                    "8",
                    "--capacity",
                    "100",
                    "--window-s",
                    ".12",
                    "--output",
                    str(Path(temp) / "run"),
                ]
            )
            with patch.object(socket.socket, "connect", side_effect=AssertionError("Network")):
                result = await run(args)
                checked = audit(args.output)
                self.assertEqual(checked["episodes"], 8)
            self.assertEqual(result["tasks"], 8)
            self.assertEqual(result["max_active_agents"], 4)
            self.assertTrue(result["quota_valid"])
            self.assertEqual(result["optional_failures"], 0)
            self.assertEqual(result["forecasts"]["failures"], 0)
            self.assertIsNone(result["em"])
            self.assertGreater(result["forecasts"]["requests"], 0)


if __name__ == "__main__":
    unittest.main()
