import asyncio
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import httpx

from quota_spec.models import AgentState, Call, Observation, Snapshot
from quota_spec.pooled_jev import JevHTTPPool, PooledJevPredictor
from quota_spec.prediction import Forecast


class History:
    def predict(self, state, agent):
        return Forecast(0.5, 0.5, (1,), (0.2,), 0.5)


class PooledJevTests(unittest.TestCase):
    def state(self):
        agent = AgentState("a", 0, 0, "thinking", 0, task_context="Observed question")
        return Observation(0, "a", 0, Call.search("query"), 3, 0, Snapshot(3, 10, (agent,))), agent

    def test_pool_reuses_one_event_loop_for_concurrent_predictors_and_closes(self):
        loops = []

        async def handler(request):
            loops.append(asyncio.get_running_loop())
            await asyncio.sleep(0.005)
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "fixture",
                    "answers": {k: {"noul": 0.7} for k in payload["questions"]},
                    "usage": {"cost": 0.00001},
                },
            )

        state, agent = self.state()
        with JevHTTPPool(transport=httpx.MockTransport(handler)) as pool:

            def call(_):
                p = PooledJevPredictor(
                    History(),
                    pool=pool,
                    api_key="fixture",
                    base_url="http://fixture",
                    model="fixture",
                )
                result = p.predict(state, agent)
                self.assertEqual(p.records[0]["cost_usd"], 0.00001)
                return result

            with ThreadPoolExecutor(max_workers=4) as workers:
                results = list(workers.map(call, range(8)))
            self.assertEqual(len(results), 8)
            self.assertEqual(len(set(loops)), 1)
        self.assertTrue(pool.closed)
        self.assertFalse(pool.thread.is_alive())

    def test_pooled_timeout_is_a_total_deadline_and_records_failed_attempt(self):
        async def handler(request):
            await asyncio.sleep(0.2)
            return httpx.Response(200, json={})

        state, agent = self.state()
        with JevHTTPPool(transport=httpx.MockTransport(handler)) as pool:
            p = PooledJevPredictor(
                History(),
                pool=pool,
                api_key="fixture",
                base_url="http://fixture",
                model="fixture",
                timeout_s=0.02,
            )
            started = time.perf_counter()
            with self.assertRaises(ValueError):
                p.predict(state, agent)
            self.assertLess(time.perf_counter() - started, 0.15)
            self.assertEqual(len(p.records), 1)
            self.assertIsNotNone(p.records[0]["failure"])


if __name__ == "__main__":
    unittest.main()
