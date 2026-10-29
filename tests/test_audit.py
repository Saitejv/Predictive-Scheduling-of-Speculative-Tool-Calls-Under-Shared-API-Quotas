"""Regressions for collection readiness and proposal experiment controls."""

import asyncio
import json
import tempfile
import unittest
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from quota_spec.collect_qa import collect
from quota_spec.forecast_bank import BankPredictor, bank_cases, prepare
from quota_spec.gateway import Gateway
from quota_spec.models import AgentState, Call, Step, Task
from quota_spec.pipeline import run
from quota_spec.prediction import HistoryPredictor, bounded_context
from quota_spec.qa import MockQA
from quota_spec.search import SearchCorpus
from quota_spec.workload import dump_tasks


def source(root):
    root.mkdir()
    corpus = SearchCorpus([{"title": "Ada", "text": "Ada wrote algorithms."}])
    corpus.save(root / "corpus.json")
    task = Task(
        "dev",
        0,
        (Step(0.01, Call.search("Ada"), 0.01, Call.search("Ada"), 0.01),),
        task_context="Who wrote algorithms?",
        final_think_s=0.01,
    )
    dev, evaluation = (task,), (replace(task, task_id="eval"),)
    for name, rows in (("development", dev), ("evaluation", evaluation)):
        (root / f"{name}.json").write_text(json.dumps(dump_tasks(rows)))
    (root / "labels.json").write_text(
        json.dumps([{"task_id": t.task_id, "answer": "Ada"} for t in (*dev, *evaluation)])
    )
    (root / "manifest.json").write_text(json.dumps({"corpus_sha256": corpus.digest}))
    return dev, evaluation


class ContextAuditTests(unittest.TestCase):
    def test_usage_reserve_observes_fractional_refill_boundary(self):
        from quota_spec.models import Observation, Snapshot
        from quota_spec.policies import UsageForecastReserve

        policy = UsageForecastReserve()
        state = Observation(
            4.3, "a", 0, Call.search("x"), 1, 0, Snapshot(1, 0.1, (), recent_required_s=(4.25,))
        )
        self.assertFalse(policy.admit(state))
        self.assertGreaterEqual(policy.last_decision["forecast_reserve"], 1)

    def test_unknown_inference_cost_is_not_reported_as_free(self):
        from quota_spec.telemetry import summarize_inference

        result = summarize_inference(
            [
                {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01, "failure": None},
                {"failure": "TimeoutError"},
            ]
        )
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["failures"], 1)
        self.assertIsNone(result["cost_usd"])
        self.assertEqual(result["known_cost_usd"], 0.01)
        self.assertEqual(result["unknown_cost_usd_requests"], 1)

    def test_progress_ablation_retains_evidence_and_other_candidate_is_omitted(self):
        task = Task("a", 0, (Step(1, Call.search("x"), 1, Call.search("hint"), 1),))
        _, state, agent, _ = next(row for row in bank_cases((task,)) if row[0][-1])
        agent = replace(agent, result_excerpt="observed evidence", history=(Call.search("old"),))
        full = bounded_context(state, agent, "progress")
        no_progress = bounded_context(state, agent, "no_progress")
        self.assertEqual(
            no_progress,
            {k: v for k, v in full.items() if k not in ("completed_calls", "phase", "elapsed_s")},
        )
        self.assertNotEqual(no_progress, bounded_context(state, agent, "history"))
        other = replace(agent, task_id="b")
        self.assertIsNone(bounded_context(state, other)["candidate"])
        self.assertEqual(
            bounded_context(state, other),
            bounded_context(replace(state, candidate=Call.search("different owner's call")), other),
        )


class GatewayAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_unused_speculation_is_counted_and_not_refunded(self):
        async def tool(call):
            raise OSError("fixture failure")

        gateway = Gateway(tool)
        try:
            self.assertTrue(await gateway.speculate("a", Call.search("x")))
            entry = next(iter(gateway.registry.values()))
            await entry.worker
            await gateway.finish_task("a")
            self.assertEqual(sum(e["event"] == "unused_speculation" for e in gateway.events), 1)
            self.assertEqual(gateway.quota.used, 1)
        finally:
            await gateway.close()

    async def test_live_qa_exposes_deadline_to_policy_and_reports_completion(self):
        from quota_spec.qa import run_agent

        observed = []

        class Policy:
            def admit(self, state):
                observed.extend(a.deadline_s for a in state.snapshot.agents)
                return False

        async def tool(call):
            return []

        gateway = Gateway(tool, policy=Policy())
        try:
            result = await run_agent(
                {"task_id": "a", "task_context": "Who?"}, gateway, MockQA(), deadline_s=10
            )
            self.assertEqual(observed, [10])
            self.assertTrue(result["deadline_met"])
        finally:
            await gateway.close()

    async def test_each_cached_required_request_contributes_zero_wait(self):
        async def tool(call):
            return "result"

        gateway = Gateway(tool)
        try:
            for _ in range(3):
                await gateway.required("a", Call.search("same"))
            waits = [e for e in gateway.events if e["event"] == "required_wait"]
            self.assertEqual(len(waits), 3)
            self.assertEqual([e["wait_s"] for e in waits[1:]], [0, 0])
            self.assertEqual(gateway.quota.used, 1)
        finally:
            await gateway.close()

    async def test_progress_queue_prioritizes_observed_completed_calls(self):
        async def tool(call):
            return "result"

        gateway = Gateway(tool, capacity=1, window_s=0.05, required_order="progress")
        try:
            await gateway.required("consume", Call.search("first"))
            now = gateway.now()
            for tid, completed in (("early", 0), ("advanced", 2)):
                await gateway.observe(AgentState(tid, now, completed, "thinking", now))
            await asyncio.gather(
                gateway.required("early", Call.search("a")),
                gateway.required("advanced", Call.search("b")),
            )
            starts = [e["task_id"] for e in gateway.events if e["event"] == "call_started"]
            self.assertEqual(starts, ["consume", "advanced", "early"])
        finally:
            await gateway.close()


class CollectionAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_labels_fail_before_inference_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source(root / "data")
            (root / "data/labels.json").write_text("[]")
            with patch.object(MockQA, "decide", side_effect=AssertionError("inference")):
                with self.assertRaisesRegex(ValueError, "Labels"):
                    await collect(root / "data", root / "output", count=2)
            self.assertFalse((root / "output").exists())

    async def test_failed_attempt_telemetry_survives_successful_resume(self):
        class Failing(MockQA):
            async def decide(self, *args, **kwargs):
                self.records.append({"failure": "TimeoutError", "cost_usd": None})
                raise TimeoutError("offline fixture")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source(root / "data")
            with self.assertRaises(ValueError):
                await collect(root / "data", root / "output", count=2, model_factory=Failing)
            with patch("builtins.print"):
                await collect(root / "data", root / "output", count=2, resume=True)
            failures = list((root / "output/failed_attempts").glob("*.json"))
            self.assertEqual(len(failures), 1)
            self.assertEqual(
                json.loads(failures[0].read_text())["inference"][0]["failure"], "TimeoutError"
            )


class BankAuditTests(unittest.TestCase):
    def setUp(self):
        try:
            import httpx  # noqa: F401
        except ImportError:
            self.skipTest("Requires live extras")

    def test_tampered_bank_rejected_before_replay_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dev, evaluation = source(root / "data")
            with patch("builtins.print"):
                prepare(root / "data", root / "banks", contexts=("progress",), execute=True)
            path = root / "banks/mock-progress.json"
            bank = json.loads(path.read_text())
            next(iter(bank["responses"].values()))["reuse"] = 0.123
            path.write_text(json.dumps(bank))
            with self.assertRaisesRegex(ValueError, "checksum"):
                BankPredictor(HistoryPredictor.fit(dev), path, evaluation)
            with self.assertRaisesRegex(ValueError, "checksum"):
                prepare(
                    root / "data", root / "banks", contexts=("progress",), execute=True, resume=True
                )

    def test_all_resume_configs_checked_before_any_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source(root / "data")
            with patch("builtins.print"):
                prepare(root / "data", root / "banks", contexts=("task", "progress"), execute=True)
            # Earlier bank is missing (would require inference); later bank is incompatible.
            (root / "banks/mock-task.json").unlink()
            path = root / "banks/mock-progress.json"
            bank = json.loads(path.read_text())
            bank["config"]["model"] = "changed"
            path.write_text(json.dumps(bank))
            with patch(
                "quota_spec.adapters.MockSystemOnePredictor.predict",
                side_effect=AssertionError("inference before validation"),
            ):
                with self.assertRaisesRegex(ValueError, "configuration"):
                    prepare(
                        root / "data",
                        root / "banks",
                        contexts=("task", "progress"),
                        execute=True,
                        resume=True,
                    )

    def test_pipeline_resume_rejects_environment_model_change_before_stages(self):
        from quota_spec.adapters import MockSystemOnePredictor

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source(root / "data")
            args = Namespace(
                data=root / "data",
                output=root / "run",
                backend="mock",
                count=2,
                max_calls=3,
                predictors=["mock"],
                contexts=["progress"],
                window_s=0.1,
                seeds=[7],
                samples=1,
                live_count=0,
                max_requests=100,
                qa_timeout_s=30,
                predictor_timeout_s=2,
                qa_input_price=None,
                qa_output_price=None,
                predictor_input_price=None,
                predictor_output_price=None,
                no_plots=True,
                resume=False,
            )
            # Stop immediately after the configuration is checkpointed.
            with patch("quota_spec.pipeline.collect", side_effect=ValueError("fixture stop")):
                with self.assertRaisesRegex(ValueError, "fixture stop"):
                    run(args)
            args.resume = True

            def changed(*a, **kw):
                model = MockSystemOnePredictor(*a, **kw)
                model.model = "changed-model"
                return model

            with (
                patch("quota_spec.adapters.MockSystemOnePredictor", side_effect=changed),
                patch("quota_spec.pipeline.collect", side_effect=AssertionError("new collection")),
            ):
                with self.assertRaisesRegex(ValueError, "unchanged"):
                    run(args)
