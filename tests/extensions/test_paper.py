import importlib.util
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from quota_spec.paper import (
    REVISION,
    compatibility_fixes,
    load_upstream,
    paper_indices,
    prepare,
    text_client,
    working_directory,
)


class PaperSelectionTests(unittest.TestCase):
    def test_author_sample_order_and_count_bounds(self):
        self.assertEqual(paper_indices(4), [7107, 5619, 373, 6904])
        self.assertEqual(len(set(paper_indices(20))), 20)
        for count in (0, 21, True):
            with self.assertRaises(ValueError):
                paper_indices(count)

    def test_malformed_paid_response_keeps_usage_before_choices_validation(self):
        import httpx

        records = []
        with tempfile.TemporaryDirectory() as directory:
            client = text_client(
                records,
                2,
                Path(directory) / "inference.jsonl",
                api_key="fixture",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"usage": {"cost": 0.012}})
                ),
            )("fixture", 0, 1000, 1)
            with self.assertRaises(ValueError):
                client.call("fixture prompt")
        self.assertEqual(records[0]["cost_usd"], 0.012)
        self.assertEqual(records[0]["failure"], "KeyError")

    def test_paper_transport_preserves_pinned_openrouter_parameters(self):
        import httpx

        payloads = []

        def handler(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "fixture"}, "finish_reason": "stop"}],
                    "usage": {"cost": 0},
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            client = text_client(
                [],
                4,
                Path(directory) / "inference.jsonl",
                api_key="fixture",
                transport=httpx.MockTransport(handler),
            )
            client("google/gemini-2.5-flash", 1, 1000, 1).call("actor prompt")
            client("google/gemini-2.5-flash", 0.1, 100, 0.9).call("observation prompt")
        self.assertEqual(
            [(p["temperature"], p["max_tokens"], p["top_p"]) for p in payloads],
            [(1, 1000, 1), (0.1, 100, 0.9)],
        )
        self.assertTrue(
            all(p["messages"][0]["content"] == "You are a helpful assistant." for p in payloads)
        )
        self.assertTrue(all("reasoning" not in p and "response_format" not in p for p in payloads))

    def test_reasoning_only_truncation_is_explicit_and_keeps_billed_cost(self):
        import httpx

        records = []
        with tempfile.TemporaryDirectory() as directory:
            client = text_client(
                records,
                2,
                Path(directory) / "inference.jsonl",
                api_key="fixture",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        json={
                            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
                            "usage": {
                                "completion_tokens": 64,
                                "cost": 0.0000285,
                                "completion_tokens_details": {"reasoning_tokens": 64},
                            },
                        },
                    )
                ),
            )("openai/gpt-5-nano", 0.1, 100, 0.9)
            with self.assertRaises(ValueError):
                client.call("fixture")
        self.assertEqual(records[0]["failure_reason"], "empty_visible_response")
        self.assertEqual(records[0]["visible_output_chars"], 0)
        self.assertEqual(records[0]["reasoning_tokens"], 64)
        self.assertEqual(records[0]["cost_usd"], 0.0000285)


class UpstreamWorkloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2] / "data/raw/speculative-action" / REVISION
        if not (cls.root / "upstream.json").exists():
            raise unittest.SkipTest(
                "Run quota_spec.paper --prepare-only to test pinned upstream code"
            )
        for dependency in ("gymnasium", "pandas", "requests", "bs4"):
            if importlib.util.find_spec(dependency) is None:
                raise unittest.SkipTest("Install .[paper] for upstream integration tests")

    def setUp(self):
        self.warnings = warnings.catch_warnings()
        self.warnings.__enter__()
        warnings.simplefilter("ignore", UserWarning)

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def call(self, *args, **kwargs):
                return "A hypothetical Wikipedia page about a different entity."

        self.module = load_upstream(self.root, FakeClient)
        self.module.wrappers.DATA_DIR = str(self.root / "hotpotqa/data")

    def tearDown(self):
        self.warnings.__exit__(None, None, None)

    def test_pristine_upstream_files_revalidate_without_network(self):
        with patch("httpx.Client", side_effect=AssertionError("Unexpected network")):
            self.assertEqual(prepare(self.root), self.root)

    def test_reset_reproduces_selected_question_instead_of_numpy_random_question(self):
        with tempfile.TemporaryDirectory() as directory, working_directory(directory):
            runner = self.module.HotPotQARun("actor", "speculator", False)
            with patch("numpy.random.randint", return_value=6):
                runner.env.reset(idx=7107)
                self.assertEqual(runner.env.data_idx, 6)  # Reproduce the upstream bug.
                compatibility_fixes(self.module)
                question = runner.env.reset(idx=7107)
                self.assertEqual(runner.env.data_idx, 7107)
            data = json.loads(
                (self.root / "hotpotqa/data/hotpot_dev_v1_simplified.json").read_text()
            )
            self.assertEqual(question, "Question: " + data[7107]["question"])

    def test_speculative_search_cannot_overwrite_authoritative_page(self):
        compatibility_fixes(self.module)
        env = self.module.environment.WikiEnv("speculator")
        env.page, env.obs = "Authoritative Mars page.", "Observed Mars."
        env.steps = 4
        env.step("search[Venus]", step_type="simulate")
        self.assertIn("hypothetical", env.sim_obs)
        self.assertEqual(env.page, "Authoritative Mars page.")
        self.assertEqual(env.obs, "Observed Mars.")
        self.assertEqual(env.steps, 4)

    def test_speculative_lookup_does_not_consume_real_lookup_cursor(self):
        compatibility_fixes(self.module)
        env = self.module.environment.WikiEnv("speculator")
        env.page = "Mars is red. Mars is a planet."
        env.step("lookup[Mars]", step_type="simulate")
        observation, *_ = env.step("lookup[Mars]")
        self.assertTrue(observation.startswith("(Result 1 /"))

    def test_real_tool_observation_is_unchanged_by_adapter(self):
        import requests

        html = "<html><body><p>Mars is a planet. It has two moons.</p></body></html>"
        response = requests.Response()
        response.status_code = 200
        response._content = html.encode()
        before = self.module.environment.WikiEnv("speculator")
        with patch("requests.get", return_value=response):
            original, *_ = before.step("search[Mars]")
            compatibility_fixes(self.module)
            after = self.module.environment.WikiEnv("speculator")
            adapted, *_ = after.step("search[Mars]")
        self.assertEqual(original, adapted)
        self.assertIn("two moons", adapted)
