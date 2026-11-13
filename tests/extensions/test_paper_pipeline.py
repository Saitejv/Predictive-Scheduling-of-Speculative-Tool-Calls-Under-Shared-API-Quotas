import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.forecast_bank import bank_cases
from quota_spec.models import AgentState, Call, Observation, Snapshot, Step, Task, load_tasks
from quota_spec.paper_collect import normalize, parse_paper_action
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.prediction import HistoryPredictor, bounded_context
from quota_spec.replay import Replay
from quota_spec.workload import dump_tasks


def lookahead(delay=1):
    return Task(
        "a",
        0,
        (
            Step(0, Call.search("first"), 10, result_excerpt="SECRET AFTER FIRST SEARCH"),
            Step(
                2,
                Call.search("second"),
                8,
                Call.search("second"),
                8,
                candidate_delay_s=delay,
                candidate_trigger="previous_tool_start",
            ),
            Step(1, Call("finish", '{"answer":"done"}'), 0, quota_required=False),
        ),
        task_context="question",
    )


class PaperReplayTests(unittest.TestCase):
    def test_lookup_is_not_charged_or_cached_and_finish_costs_no_quota(self):
        lookup = Call("lookup", '{"keyword":"same"}')
        task = Task(
            "a",
            0,
            (
                Step(1, Call.search("entity"), 2),
                Step(1, lookup, 3, quota_required=False),
                Step(1, lookup, 3, quota_required=False),
                Step(1, Call("finish", '{"answer":"done"}'), 0, quota_required=False),
            ),
        )
        result = Replay((task,), 1, 100).run(NoSpeculation())
        self.assertEqual(result.metrics["mean_completion_s"], 12)
        self.assertEqual(result.metrics["calls_started"], 1)
        self.assertEqual(result.metrics["local_actions_started"], 3)
        self.assertEqual(result.metrics["reuse_hits"], 0)

    def test_prediction_can_prefetch_while_preceding_real_search_runs(self):
        observed = []

        class Inspect(CurrentCapacity):
            def admit(self, state):
                observed.append(state)
                return super().admit(state)

        task = lookahead()
        baseline = Replay((task,), 3, 100).run(NoSpeculation())
        result = Replay((task,), 3, 100).run(Inspect())
        self.assertEqual(baseline.metrics["mean_completion_s"], 21)
        self.assertEqual(result.metrics["mean_completion_s"], 13)
        optional = next(
            e for e in result.events if e["event"] == "call_started" and e["speculative"]
        )
        self.assertEqual(optional["time_s"], 1)
        self.assertEqual(observed[0].snapshot.agents[0].phase, "running")
        self.assertEqual(observed[0].completed_calls, 0)
        context = json.dumps(bounded_context(observed[0], observed[0].snapshot.agents[0]))
        self.assertNotIn("SECRET AFTER FIRST SEARCH", context)

    def test_late_and_tied_proposals_do_not_delay_or_duplicate_required_work(self):
        for delay in (12, 13, 30):
            with self.subTest(delay=delay):
                result = Replay((lookahead(delay),), 3, 100).run(CurrentCapacity())
                self.assertEqual(result.metrics["mean_completion_s"], 21)
                self.assertEqual(result.metrics["speculative_calls"], 0)
                self.assertEqual(result.metrics["calls_started"], 2)

    def test_preceding_search_quota_wait_shifts_proposal_release(self):
        blocker = Task("blocker", 0, (Step(0, Call.search("block"), 1),))
        result = Replay((blocker, lookahead()), 1, 100).run(CurrentCapacity())
        decision = next(e for e in result.events if e["event"] == "candidate_decided")
        self.assertEqual(decision["time_s"], 101)

    def test_mixed_action_roundtrip_retains_tool_semantics_and_trigger(self):
        task = lookahead()
        self.assertEqual(load_tasks(dump_tasks((task,))), (task,))
        self.assertEqual(parse_paper_action("Lookup[key]"), Call("lookup", '{"keyword":"key"}'))
        self.assertEqual(parse_paper_action("Finish[]"), Call("finish", '{"answer":""}'))

    def test_forecast_bank_has_pending_owner_case_without_future_response(self):
        identity, state, agent, labels = next(
            row for row in bank_cases((lookahead(),)) if row[0] == ("a", 0, "running", True)
        )
        self.assertEqual(state.candidate, Call.search("second"))
        self.assertNotIn("SECRET", json.dumps(bounded_context(state, agent)))
        self.assertEqual(labels, {"reuse": True, "next": True, "continues": False})

    def test_history_forecasts_only_search_demand_and_counts_intervening_local_time(self):
        task = Task(
            "dev",
            0,
            (
                Step(1, Call("lookup", '{"keyword":"x"}'), 3, quota_required=False),
                Step(2, Call.search("entity"), 5),
                Step(1, Call("finish", '{"answer":"done"}'), 0, quota_required=False),
            ),
        )
        predictor = HistoryPredictor.fit((task,))
        agent = AgentState("a", 0, 0, "thinking", 0)
        state = Observation(0, "a", 0, Call.search("entity"), 3, 0, Snapshot(3, 10, (agent,)))
        forecast = predictor.predict(state, agent)
        self.assertEqual(forecast.delays_s, (6,))
        self.assertEqual(forecast.durations_s, (5,))

    def test_normalization_uses_observation_then_actor_latency_not_serial_wall_time(self):
        normal = {
            "actions": ["Search[first]", "Search[second]", "Finish[done]"],
            "time_taken": [10, 8, 0],
            "observations": ["one", "two", "done"],
        }
        simulated = {
            "actions": [["Search[first]"], ["Search[second]"], ["Finish[done]"]],
            "time_taken": [0.4, 0.5, 0],
        }
        timings = [
            {"actor": 2, "speculative_actor": 0.3},
            {"actor": 3, "speculative_actor": 0.6},
            {"actor": 4, "speculative_actor": 0.7},
        ]
        task = normalize("a", "q", normal, simulated, timings, {"second": 8})
        self.assertIsNone(task.steps[0].candidate)
        self.assertAlmostEqual(task.steps[1].candidate_delay_s, 1)
        self.assertEqual(task.steps[1].think_s, 3)
        self.assertFalse(task.steps[2].quota_required)


class CanonicalPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util

        from quota_spec.paper import REVISION

        cls.root = Path(__file__).resolve().parents[2] / "data/raw/speculative-action" / REVISION
        if not (cls.root / "upstream.json").exists():
            raise unittest.SkipTest("Run quota_spec.paper --prepare-only")
        if any(
            importlib.util.find_spec(m) is None
            for m in ("gymnasium", "requests", "bs4", "pandas", "httpx")
        ):
            raise unittest.SkipTest("Install .[paper] for canonical integration checks")

    def test_end_to_end_frozen_comparison_and_resume_without_network_or_credentials(self):
        from quota_spec.paper_pipeline import run

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "study"
            args = argparse.Namespace(
                source=self.root,
                output=output,
                count=4,
                backend="mock",
                actor="mock-actor",
                speculator="mock-speculator",
                predictors=["mock"],
                contexts=["progress"],
                seeds=[7],
                samples=2,
                window_s=0.1,
                predictor_timeout_s=2,
                max_requests=128,
                max_forecast_requests=200,
                no_plots=True,
                resume=False,
            )
            with (
                patch.dict("os.environ", {}, clear=True),
                patch("socket.socket.connect", side_effect=AssertionError("network")),
                patch("builtins.print"),
            ):
                result = run(args)
            self.assertEqual(result["completed"], ["collection", "forecasts", "study", "report"])
            self.assertFalse((output / "traces/corpus.json").exists())
            tasks = load_tasks(json.loads((output / "traces/evaluation.json").read_text()))
            self.assertEqual(
                [s.required.tool for s in tasks[0].steps], ["search", "lookup", "search", "finish"]
            )
            rows = json.loads((output / "study/runs.json").read_text())
            names = {r["policy"] for r in rows}
            self.assertTrue({"mock_progress_full", "mock_progress_own"} <= names)
            self.assertTrue(all(r["max_active_agents"] <= 2 for r in rows))
            self.assertEqual(sum(r["prediction_fallbacks"] for r in rows), 0)
            outcomes = json.loads((output / "qa_outcomes.json").read_text())
            self.assertTrue(all(r["em"] is None for r in outcomes))
            before = (output / "traces/inference.jsonl").read_bytes()
            args.resume = True
            with (
                patch("quota_spec.paper.text_client", side_effect=AssertionError("paid call")),
                patch("socket.socket.connect", side_effect=AssertionError("network")),
                patch("builtins.print"),
            ):
                run(args)
            self.assertEqual((output / "traces/inference.jsonl").read_bytes(), before)

    def test_failed_generation_stops_before_upstream_can_skip_and_misalign_steps(self):
        from quota_spec.paper_collect import collect

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "collection"
            with patch("quota_spec.paper_collect.normalize") as normalization:
                # Loading upstream replaces its module; inject at that boundary.
                from quota_spec.paper_collect import load_upstream

                def failing_load(*args):
                    module = load_upstream(*args)

                    def fail(*args, **kwargs):
                        raise ValueError("fixture")

                    module.HotPotQARun.generate_thought_actions = fail
                    return module

                with patch("quota_spec.paper_collect.load_upstream", side_effect=failing_load):
                    with self.assertRaisesRegex(ValueError, "partial inference retained"):
                        collect(self.root, output, count=2, backend="mock")
                normalization.assert_not_called()
            failure = json.loads((output / "tasks/7107.json").read_text())
            self.assertEqual(failure["failure"], "RuntimeError")
            self.assertIn("actor", failure["timings"]["1"])
            self.assertEqual(failure["normal"]["actions"], [])

    def test_real_tool_retry_time_survives_normalization(self):
        import time

        import requests

        from quota_spec.paper_collect import collect, mock_transports

        transport, wiki = mock_transports()
        attempts = 0

        def retrying_wiki(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                time.sleep(0.02)
                raise requests.exceptions.Timeout("fixture")
            return wiki(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "collection"
            with (
                patch(
                    "quota_spec.paper_collect.mock_transports",
                    return_value=(transport, retrying_wiki),
                ),
                patch("builtins.print"),
            ):
                collect(self.root, output, count=2, backend="mock")
            task = json.loads((output / "tasks/7107.json").read_text())
            self.assertGreaterEqual(task["normal"]["time_taken"][0], 0.02)
            self.assertEqual(task["question_index"], 7107)

    def test_hypothetical_observation_reaches_only_speculative_actor_prompt(self):
        import httpx

        from quota_spec.paper import INFERENCE_CONTEXT
        from quota_spec.paper_collect import collect, mock_transports

        original, wiki = mock_transports()
        prompts = []

        def handler(request):
            role = INFERENCE_CONTEXT.get()["role"]
            payload = json.loads(request.content)
            prompts.append((role, payload["messages"][-1]["content"]))
            response = original.handle_request(request)
            if role == "observation_speculator":
                body = response.json()
                body["choices"][0]["message"]["content"] = "HYPOTHETICAL_ONLY entity."
                return httpx.Response(200, json=body)
            return response

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "quota_spec.paper_collect.mock_transports",
                    return_value=(httpx.MockTransport(handler), wiki),
                ),
                patch("builtins.print"),
            ):
                collect(self.root, Path(directory) / "collection", count=2, backend="mock")
        self.assertTrue(
            any("HYPOTHETICAL_ONLY" in p for r, p in prompts if r == "speculative_actor")
        )
        self.assertTrue(all("HYPOTHETICAL_ONLY" not in p for r, p in prompts if r == "actor"))
