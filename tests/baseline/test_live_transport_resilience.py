import asyncio
import json
import socket
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from quota_spec.capture import ACTIVE_CAPTURE, Capture
from quota_spec.hotpot_runtime import Events, MockChat, MockSearch, Runtime
from quota_spec.live_context_audit import audit
from quota_spec.multi_agent import parser, run
from quota_spec.transport import LiveChat, OptionalExpired


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_502_retries_with_separate_nodes_and_conservative_budget(self):
        attempts = []

        async def handler(request):
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(502, json={"error": {"message": "Provider error"}})
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Finish[fixture]"}}],
                    "usage": {"cost": 0.0001},
                },
            )

        with tempfile.TemporaryDirectory() as temp:
            root, events = Path(temp), Events()
            capture = Capture(root / "capture", events.start)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                chat = LiveChat(
                    client,
                    "fixture-key",
                    {"fixture": {"prompt": "0", "completion": ".000001"}},
                    root,
                    events,
                    0.01,
                    3,
                    "fixture",
                    "fixture",
                    reserve_unknown_cost=True,
                )
                module = types.SimpleNamespace(HotPotQARun=type("Parser", (), {}))
                runtime = Runtime(module, chat, None, events, "", capture=capture, model_retries=1)
                result, _ = await runtime.model("observed prompt", "actor", "episode", 1)
                self.assertEqual(result, "Finish[fixture]")
                self.assertEqual(len(attempts), 2)
                self.assertEqual([n["status"] for n in capture.nodes], ["failed", "completed"])
                self.assertIsNone(chat.records[0]["cost_usd"])
                self.assertEqual(
                    chat.records[0]["budget_charge_source"], "unknown_cost_upper_bound"
                )
                self.assertAlmostEqual(chat.spent, 0.0011)
                self.assertEqual(chat.reserved, 0)
                self.assertFalse(chat.unknown)
                self.assertEqual(capture.nodes[0]["usage"]["budget_charge_usd"], 0.001)
                self.assertNotIn("fixture-key", (root / "requests.jsonl").read_text())

    async def test_full_live_path_recovers_non_json_502_and_passes_independent_audit(self):
        original_client = httpx.AsyncClient
        failed = False

        async def handler(request):
            nonlocal failed
            if request.method == "GET":
                if request.url.path.endswith("/models"):
                    return httpx.Response(
                        200,
                        json={
                            "data": [
                                {
                                    "id": "fixture",
                                    "pricing": {"prompt": "0", "completion": ".000001"},
                                }
                            ]
                        },
                    )
                return httpx.Response(200, json={"data": {"usage": 0, "limit": 5}})
            node = ACTIVE_CAPTURE.get()[1]
            if node["branch"] == "actor" and not failed:
                failed = True
                return httpx.Response(502, text="Transient gateway HTML")
            payload = json.loads(request.content)
            content = await MockChat().call(
                payload["messages"][-1]["content"], node["branch"], node["episode"], node["step"]
            )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": content}}],
                    "usage": {"cost": 0.00001, "prompt_tokens": 0, "completion_tokens": 0},
                },
            )

        def client(*args, **kwargs):
            return original_client(*args, **kwargs, transport=httpx.MockTransport(handler))

        with tempfile.TemporaryDirectory() as temp:
            args = parser().parse_args(
                [
                    "--backend",
                    "http",
                    "--policy",
                    "current_capacity",
                    "--actor",
                    "fixture",
                    "--speculator",
                    "fixture",
                    "--agents",
                    "2",
                    "--count",
                    "2",
                    "--capacity",
                    "100",
                    "--output",
                    str(Path(temp) / "live"),
                ]
            )
            with (
                patch("httpx.AsyncClient", side_effect=client),
                patch(
                    "quota_spec.multi_agent.WikiSearch",
                    side_effect=lambda module, events, **kwargs: MockSearch(events),
                ),
                patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-only-key"}),
                patch.object(socket.socket, "connect", side_effect=AssertionError("Network")),
            ):
                result = await run(args)
                checked = audit(args.output)
            self.assertTrue(checked["passed"])
            self.assertEqual(result["failures"], 0)
            self.assertEqual(result["inference"]["failures"], 1)
            self.assertEqual(result["inference"]["unknown_cost_usd_requests"], 1)
            self.assertGreater(result["unknown_cost_upper_bound_usd"], 0)
            self.assertEqual(checked["episodes"], 2)

    async def test_expired_unsent_draft_is_skipped_without_http_or_budget_charge(self):
        called = []

        async def handler(request):
            called.append(request)
            raise AssertionError("Expired optional work must not reach provider")

        with tempfile.TemporaryDirectory() as temp:
            root, events = Path(temp), Events()
            capture = Capture(root / "capture", events.start)
            active = True
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                chat = LiveChat(
                    client,
                    "fixture",
                    {"fixture": {"prompt": "0", "completion": "0"}},
                    root,
                    events,
                    0.1,
                    10,
                    "fixture",
                    "fixture",
                    optional_allowed=lambda episode: active,
                )
                chat.optional_semaphore = asyncio.Semaphore(0)
                task = asyncio.create_task(
                    capture.model(chat, "draft prompt", "speculative_actor", "a", 1)
                )
                await asyncio.sleep(0.005)
                active = False
                chat.optional_semaphore.release()
                with self.assertRaises(OptionalExpired):
                    await task
                self.assertFalse(called)
                self.assertEqual(chat.requests, 0)
                self.assertEqual(chat.spent, 0)
                self.assertEqual(capture.nodes[0]["status"], "skipped")
                self.assertNotIn("request_id", capture.nodes[0])


if __name__ == "__main__":
    unittest.main()
