import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.collect_qa import collect, trajectory
from quota_spec.forecast_bank import BankPredictor, bank_cases, prepare
from quota_spec.models import Call, Step, Task, load_tasks
from quota_spec.policies import CurrentCapacity
from quota_spec.prediction import Forecast, HistoryPredictor, PerturbedPredictor
from quota_spec.qa import MockQA
from quota_spec.replay import Replay
from quota_spec.search import SearchCorpus, sha256_json
from quota_spec.workload import dump_tasks


class ReplayReadinessTests(unittest.TestCase):
    def test_zero_search_and_final_generation_are_in_completion_and_deadlines(self):
        tasks = (
            Task("zero", 2, (), deadline_s=4, final_think_s=3),
            Task("one", 0, (Step(1, Call.search("x"), 2),), final_think_s=4),
        )
        result = Replay(tasks, 5, 10).run()
        self.assertEqual(result.metrics["task_finish_s"], {"zero": 5, "one": 7})
        self.assertEqual(result.metrics["deadline_misses"], 1)
        self.assertEqual(result.metrics["calls_started"], 1)
        self.assertEqual(load_tasks(dump_tasks(tasks)), tasks)

    def test_answer_only_workload_has_zero_quota_wait(self):
        result = Replay((Task("zero", 0, (), final_think_s=2),), 1, 10).run()
        self.assertEqual(result.metrics["mean_required_wait_s"], 0)
        self.assertEqual(result.metrics["calls_started"], 0)

    def test_final_candidate_is_charged_and_unused(self):
        task = Task(
            "a",
            0,
            (),
            final_think_s=2,
            final_candidate=Call.search("unused"),
            final_candidate_duration_s=1,
            final_candidate_delay_s=0.5,
        )
        result = Replay((task,), 1, 10).run(CurrentCapacity())
        self.assertEqual(result.metrics["unused_speculative_calls"], 1)
        start = next(e for e in result.events if e["event"] == "call_started")
        self.assertEqual(start["time_s"], 0.5)
        self.assertEqual(result.metrics["task_finish_s"]["a"], 2)

    def test_inference_does_not_reserve_capacity_before_dispatch(self):
        class Slow:
            overhead_s = 2
            last_decision = {"overhead_s": 2}

            def admit(self, state):
                return True

        a = Task("a", 0, (Step(3, Call.search("a"), 1, Call.search("a"), 1),))
        b = Task("b", 0.5, (Step(0, Call.search("b"), 0.1),))
        result = Replay((a, b), 1, 10).run(Slow())
        starts = [e for e in result.events if e["event"] == "call_started"]
        self.assertEqual((starts[0]["task_id"], starts[0]["time_s"]), ("b", 0.5))
        decision = next(e for e in result.events if e["event"] == "candidate_decided")
        self.assertTrue(decision["stale"])
        self.assertFalse(decision["admitted"])

    def test_prediction_crossing_refill_is_rejected_as_stale(self):
        class Slow:
            overhead_s = 2
            last_decision = {"overhead_s": 2}

            def admit(self, state):
                return True

        task = Task("a", 0, (Step(3, Call.search("a"), 1, Call.search("a"), 1),))
        result = Replay((task,), 1, 1).run(Slow())
        self.assertEqual(result.metrics["speculative_calls"], 0)
        self.assertEqual(result.metrics["task_finish_s"]["a"], 4)

    def test_forecast_bank_telemetry_survives_probability_wrapper(self):
        class Fixed:
            decision_overhead_s = 0

            def begin_decision(self):
                self.decision_overhead_s = 0

            def predict(self, state, agent):
                self.decision_overhead_s += 0.5
                return Forecast(1, 1, (2,), (1,), 0)

        predictor = PerturbedPredictor(Fixed(), 0)
        task = Task("a", 0, (Step(3, Call.search("a"), 1, Call.search("a"), 1),))
        result = Replay((task,), 1, 10).run(
            PredictiveAdmission(predictor, AdmissionConfig(samples=2, horizon_s=5, overhead_s=0.01))
        )
        self.assertAlmostEqual(result.metrics["modeled_decision_overhead_s"], 0.51)

    def test_terminal_observations_lower_next_search_forecast(self):
        training = (Task("dev", 0, (), final_think_s=2),)
        predictor = HistoryPredictor.fit(training)
        _, state, agent, _ = next(bank_cases(training))
        self.assertLess(predictor.predict(state, agent).next_probability, 0.5)

    def test_bank_inputs_never_include_current_or_future_results(self):
        task = Task(
            "a",
            0,
            (
                Step(1, Call.search("first"), 1, Call.search("hint"), 1, "FIRST-RESULT"),
                Step(1, Call.search("SECRET-FUTURE"), 1, result_excerpt="SECRET-RESULT"),
            ),
            final_think_s=1,
        )
        for identity, state, agent, _ in bank_cases((task,)):
            if identity[1] == 0:
                from quota_spec.prediction import bounded_context

                serialized = json.dumps(bounded_context(state, agent))
                self.assertNotIn("FIRST-RESULT", serialized)
                self.assertNotIn("SECRET", serialized)


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.corpus = SearchCorpus([{"title": "Ada", "text": "Ada wrote algorithms."}])

    async def test_terminal_action_without_search_is_preserved(self):
        class Answer:
            records = []

            async def decide(self, question, history, final=False):
                return {"action": "answer", "answer": "Ada"}

        result = await trajectory(
            {"task_id": "a", "task_context": "Who?"}, self.corpus, Answer(), 3
        )
        trace = load_tasks([result["trace"]])[0]
        self.assertFalse(trace.steps)
        self.assertGreater(trace.final_think_s, 0)
        self.assertEqual(trace.final_candidate, Call.search("Who?"))
        self.assertEqual(result["answer"], "Ada")

    async def test_resume_does_not_repeat_successful_model_calls_and_exports_split(self):
        with tempfile.TemporaryDirectory() as directory:
            data, output = Path(directory) / "source", Path(directory) / "collected"
            data.mkdir()
            self.corpus.save(data / "corpus.json")
            for name, tid in (("development", "dev"), ("evaluation", "eval")):
                (data / f"{name}.json").write_text(
                    json.dumps([{"task_id": tid, "task_context": "Ada?"}])
                )
            (data / "labels.json").write_text(
                json.dumps([{"task_id": tid, "answer": "SECRET-GOLD"} for tid in ("dev", "eval")])
            )
            (data / "manifest.json").write_text(json.dumps({"corpus_sha256": self.corpus.digest}))
            with patch("builtins.print"):
                await collect(data, output, count=2)
                before = (output / "evaluation.json").read_bytes()
                with patch.object(
                    MockQA, "decide", side_effect=AssertionError("repeated inference")
                ):
                    await collect(data, output, count=2, resume=True)
            self.assertEqual(before, (output / "evaluation.json").read_bytes())
            self.assertNotIn("SECRET-GOLD", before.decode())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["development_ids"], ["dev"])
            self.assertEqual(manifest["evaluation_ids"], ["eval"])
            with self.assertRaises(ValueError):
                await collect(data, output, count=2)
            with self.assertRaises(ValueError):
                await collect(data, output, count=2, max_calls=4, resume=True)


class BankTests(unittest.TestCase):
    def test_plan_makes_no_network_calls(self):
        with patch("quota_spec.forecast_bank.JevPredictor", side_effect=AssertionError("network")):
            plan = prepare(Path("data"), Path("unused"), backends=("jev",), contexts=("task",))
        self.assertFalse(plan["external_inference"])
        self.assertGreater(plan["maximum_new_requests"], 0)

    def test_mock_bank_roundtrip_resume_and_trace_integrity(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("Requires live extras")
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            output = Path(directory) / "bank"
            data.mkdir()
            dev = (Task("dev", 0, (Step(1, Call.search("x"), 1),)),)
            evaluation = (Task("eval", 0, (Step(1, Call.search("x"), 1, Call.search("x"), 1),)),)
            for name, tasks in (("development", dev), ("evaluation", evaluation)):
                (data / f"{name}.json").write_text(json.dumps(dump_tasks(tasks)))
            with patch("builtins.print"):
                prepare(data, output, contexts=("progress",), execute=True)
                with patch.object(
                    httpx.AsyncClient, "stream", side_effect=AssertionError("new HTTP")
                ):
                    prepare(data, output, contexts=("progress",), execute=True, resume=True)
            predictor = BankPredictor(
                HistoryPredictor.fit(dev), output / "mock-progress.json", evaluation
            )
            for _, state, agent, _ in bank_cases(evaluation):
                forecast = predictor.predict(state, agent)
                self.assertEqual(forecast.reuse_probability, 0.75)
            changed = (replace(evaluation[0], final_think_s=1),)
            with self.assertRaises(ValueError):
                BankPredictor(HistoryPredictor.fit(dev), output / "mock-progress.json", changed)
            bank = json.loads((output / "mock-progress.json").read_text())
            self.assertEqual(
                bank["config"]["evaluation_sha256"], sha256_json(dump_tasks(evaluation))
            )


class StudyWorkflowTests(unittest.TestCase):
    def test_paired_study_frozen_repeat_and_bank_source_validation(self):
        from quota_spec.experiments import run_study

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            corpus = SearchCorpus([{"title": "x", "text": "x"}])
            corpus.save(data / "corpus.json")
            dev = (
                Task(
                    "dev",
                    0,
                    (Step(0.02, Call.search("x"), 0.01, Call.search("x"), 0.01),),
                    final_think_s=0.01,
                ),
            )
            evaluation = tuple(replace(dev[0], task_id=f"eval-{i}") for i in range(2))
            for name, tasks in (("development", dev), ("evaluation", evaluation)):
                (data / f"{name}.json").write_text(json.dumps(dump_tasks(tasks)))
            (data / "manifest.json").write_text(json.dumps({"corpus_sha256": corpus.digest}))
            with patch("builtins.print"):
                run_study(data, root / "first", seeds=(7,), samples=1, plots=False)
                run_study(
                    data,
                    root / "second",
                    frozen_path=root / "first/frozen_config.json",
                    plots=False,
                )
            for artifact in (
                "runs.json",
                "comparisons.json",
                "metric_comparisons.json",
                "calibration.json",
            ):
                self.assertEqual(
                    (root / "first" / artifact).read_bytes(),
                    (root / "second" / artifact).read_bytes(),
                )
            rows = json.loads((root / "first/metric_comparisons.json").read_text())
            self.assertTrue(
                any(r["policy"] == "predictive" and r["baseline"] == "own_agent_only" for r in rows)
            )
            frozen = json.loads((root / "first/frozen_config.json").read_text())
            frozen["source_sha256"] = {}
            (root / "changed.json").write_text(json.dumps(frozen))
            with self.assertRaisesRegex(ValueError, "source version"):
                run_study(data, root / "invalid", frozen_path=root / "changed.json", plots=False)


class HTTPWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_backend_collector_over_mock_transport_scores_and_keeps_labels_out(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("Requires live extras")
        from quota_spec.qa import HTTPQA

        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            user = json.loads(payload["messages"][1]["content"])
            action = (
                {"action": "answer", "answer": "Ada"}
                if user["history"]
                else {"action": "search", "query": "Ada"}
            )
            return httpx.Response(
                200,
                json={
                    "model": "fixture-v1",
                    "choices": [{"message": {"content": json.dumps(action)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            data, output = Path(directory) / "data", Path(directory) / "output"
            data.mkdir()
            corpus = SearchCorpus([{"title": "Ada", "text": "Ada wrote algorithms."}])
            corpus.save(data / "corpus.json")
            for name, tid in (("development", "dev"), ("evaluation", "eval")):
                (data / f"{name}.json").write_text(
                    json.dumps([{"task_id": tid, "task_context": "Who wrote algorithms?"}])
                )
            (data / "labels.json").write_text(
                json.dumps(
                    [
                        {"task_id": tid, "answer": "Ada", "private_gold_field": "DO_NOT_SEND"}
                        for tid in ("dev", "eval")
                    ]
                )
            )
            (data / "manifest.json").write_text(json.dumps({"corpus_sha256": corpus.digest}))

            def factory():
                return HTTPQA(
                    url="http://test/v1/chat/completions",
                    model="fixture",
                    api_key="private-test-key",
                    transport=httpx.MockTransport(handler),
                    input_price=1,
                    output_price=2,
                )

            with patch("builtins.print"):
                result = await collect(data, output, count=2, backend="http", model_factory=factory)
            self.assertEqual(result["exact_match"], 1)
            self.assertEqual(len(requests), 4)
            self.assertNotIn("DO_NOT_SEND", json.dumps(requests))
            self.assertNotIn("private-test-key", (output / "inference.jsonl").read_text())
            saved = json.loads((output / "evaluation.json").read_text())[0]
            self.assertGreater(saved["final_think_s"], 0)
            self.assertEqual(len(saved["steps"]), 1)

    async def test_frozen_decision_budget_caps_inference_and_discards_labels(self):
        history_tasks = (Task("dev", 0, (Step(1, Call.search("x"), 1),)),)
        evaluation = (Task("eval", 0, (Step(1, Call.search("x"), 1, Call.search("x"), 1),)),)
        from quota_spec.forecast_bank import case_key

        cases = list(bank_cases(evaluation))
        bank = {
            "complete": True,
            "config": {
                "backend": "jev",
                "context": "progress",
                "decision_timeout_s": 0.5,
                "evaluation_sha256": sha256_json(dump_tasks(evaluation)),
            },
            "responses": {
                "r": {"reuse": 1, "next": 1, "continues": 0, "latency_s": 2, "failure": None}
            },
            "cases": {
                case_key(*identity): {"response": "r", "labels": labels}
                for identity, _, _, labels in cases
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bank.json"
            path.write_text(json.dumps(bank))
            predictor = BankPredictor(HistoryPredictor.fit(history_tasks), path, evaluation)
            self.assertNotIn('"labels"', json.dumps(predictor.bank))
            predictor.begin_decision()
            _, state, agent, _ = cases[0]
            with self.assertRaises(TimeoutError):
                predictor.predict(state, agent)
            self.assertEqual(predictor.decision_overhead_s, 0.5)
