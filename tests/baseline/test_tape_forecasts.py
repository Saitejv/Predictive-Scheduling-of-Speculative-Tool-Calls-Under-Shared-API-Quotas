import copy
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.forecast_study import execute
from quota_spec.frozen_replay import FrozenReplay
from quota_spec.tape_forecasts import TapeBankPredictor, TapeHistory, cases, collect, digest
from tests.baseline.test_frozen_replay import tape


def bank_for(tapes, root, *, latency=0.2):
    responses = {}
    for case, _, _, _ in cases(tapes):
        responses[case["key"]] = {
            "context": case["context"],
            "reuse": 0.9,
            "next": 0.8,
            "continues": 0.2,
            "latency_s": latency,
            "failure": None,
            "telemetry": {"cost_usd": 0.001},
        }
    bank = {"config": {"mode": "progress"}, "responses": responses, "complete": True}
    bank["sha256"] = digest(bank)
    path = root / "bank.json"
    path.write_text(json.dumps(bank))
    return path


class TapeForecastTests(unittest.TestCase):
    def test_persistent_contexts_keep_original_inputs_and_reuse_saved_forecasts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "dataset-manifest.json").write_text("{}")
            data = {"tapes": [tape("dev"), tape("eval")]}
            old_keys = {case["key"] for case, _, _, _ in cases(data["tapes"])}
            new_keys = {case["key"] for case, _, _, _ in cases(data["tapes"], max_candidate_age=1)}
            self.assertLess(old_keys, new_keys)
            with patch("quota_spec.tape_forecasts.load_dataset", return_value=data):
                collect(root, root / "old", backend="mock", development_count=1)
                result = collect(
                    root,
                    root / "new",
                    backend="mock",
                    development_count=1,
                    max_candidate_age=1,
                    seed_bank=root / "old/bank.json",
                )
            self.assertTrue(result["complete"])
            self.assertEqual(result["seeded_responses"], len(old_keys))
            self.assertEqual(result["new_collection_summary"]["requests"], len(new_keys - old_keys))

    def test_collector_stops_after_two_failures_and_keeps_incomplete_bank(self):
        async def invalid_response(*args):
            return {"usage": {"input_tokens": 1, "output_tokens": 0}}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "dataset-manifest.json").write_text("{}")
            data = {"tapes": [tape("dev"), tape("eval")]}
            with (
                patch("quota_spec.tape_forecasts.load_dataset", return_value=data),
                patch("quota_spec.adapters.MockSystemOnePredictor._request", invalid_response),
            ):
                result = collect(
                    root, root / "bank", backend="mock", development_count=1, workers=1
                )
            self.assertFalse(result["complete"])
            self.assertEqual(result["summary"]["failures"], 2)
            self.assertEqual(len((root / "bank/responses.jsonl").read_text().splitlines()), 2)
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                TapeBankPredictor(TapeHistory([tape("dev")]), root / "bank/bank.json")

    def test_collector_freezes_complete_inputs_and_resume_makes_no_new_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "dataset-manifest.json").write_text("{}")
            data = {"tapes": [tape("dev"), tape("eval")]}
            with patch("quota_spec.tape_forecasts.load_dataset", return_value=data):
                result = collect(root, root / "bank", backend="mock", development_count=1)
                self.assertTrue(result["complete"])
                before = (root / "bank/responses.jsonl").read_bytes()
                with patch(
                    "quota_spec.adapters.MockSystemOnePredictor.predict",
                    side_effect=AssertionError("new inference"),
                ):
                    resumed = collect(
                        root, root / "bank", backend="mock", development_count=1, resume=True
                    )
                self.assertEqual(result, resumed)
                self.assertEqual(before, (root / "bank/responses.jsonl").read_bytes())

    def test_own_running_and_thinking_contexts_do_not_leak_current_result(self):
        fixture = tape()
        values = list(cases([fixture]))
        own = [(case, agent, labels) for case, _, agent, labels in values if case["own"]]
        running = [x for x in own if x[0]["phase"] == "running"]
        thinking = [x for x in own if x[0]["phase"] == "thinking"]
        self.assertEqual(len(running), 3)
        self.assertEqual(len(thinking), 3)
        self.assertTrue(all(a.result_excerpt == "" for _, a, _ in running))
        self.assertTrue(
            all(a.result_excerpt == fixture["steps"][0]["observed_excerpt"] for _, a, _ in thinking)
        )
        self.assertEqual(sum(labels["reuse"] for _, _, labels in running), 1)
        self.assertEqual(sum(labels["reuse"] for _, _, labels in thinking), 1)
        self.assertTrue(all("labels" not in c["context"] for c, _, _, _ in values))

    def test_history_fit_uses_only_development_and_models_future_search_not_finish(self):
        history = TapeHistory([tape("development")])
        a = tape("evaluation")
        for case, state, agent, _ in cases([a]):
            if not case["own"] and case["index"] == 1 and case["phase"] == "thinking":
                forecast = history.predict(state, agent)
                self.assertEqual(forecast.delays_s, (0.5,))
                self.assertGreater(forecast.next_probability, 0.5)
            if not case["own"] and case["index"] == 2:
                self.assertLess(history.predict(state, agent).next_probability, 0.5)
        self.assertEqual(history.training_ids, ("development",))

    def test_socket_blocked_replay_covers_shifted_boundaries_and_charges_each_call(self):
        tapes = [tape("a"), tape("b")]
        with tempfile.TemporaryDirectory() as folder:
            path = bank_for(tapes, Path(folder))
            history = TapeHistory([tape("dev")])
            with patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
                for workers in [1, 2]:
                    predictor = TapeBankPredictor(history, path)
                    policy = PredictiveAdmission(
                        predictor, AdmissionConfig(samples=4, overhead_s=0.001)
                    )
                    result = FrozenReplay(tapes, 10, 10, max_active_agents=workers).run(policy)
                    self.assertFalse(
                        any(d.get("forecast", {}).get("fallback") for d in result["decisions"])
                    )
                    self.assertGreater(predictor.logical_calls, 0)
                    self.assertAlmostEqual(
                        predictor.logical_cost_usd, predictor.logical_calls * 0.001
                    )
                    self.assertGreater(result["metrics"]["predictor_overhead_s"], 0)

    def test_parallel_and_serial_overhead_match_explicit_contract(self):
        tapes = [tape("a"), tape("b")]
        with tempfile.TemporaryDirectory() as folder:
            path = bank_for(tapes, Path(folder), latency=0.25)
            history = TapeHistory([tape("dev")])
            _, state, agent, _ = next(iter(cases(tapes)))
            for parallel, expected in [(True, 0.25), (False, 0.5)]:
                p = TapeBankPredictor(history, path, parallel=parallel)
                p.begin_decision()
                p.predict(state, agent)
                p.predict(state, agent)
                self.assertEqual(p.decision_overhead_s, expected)
                self.assertEqual(p.logical_calls, 2)

    def test_missing_exact_context_is_fatal_and_checksum_is_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = bank_for([tape()], Path(folder))
            h = TapeHistory([tape("dev")])
            p = TapeBankPredictor(h, path)
            fixture = copy.deepcopy(tape())
            fixture["question"] = "uncovered task"
            with self.assertRaisesRegex(ValueError, "Uncovered exact predictor context"):
                FrozenReplay([fixture], 10, 10).run(PredictiveAdmission(p))
            bank = json.loads(path.read_text())
            bank["complete"] = False
            path.write_text(json.dumps(bank))
            with self.assertRaisesRegex(ValueError, "checksum"):
                TapeBankPredictor(h, path)

    def test_paired_own_full_one_agent_control_and_quota_validation(self):
        tapes = [tape("a"), tape("b")]
        with tempfile.TemporaryDirectory() as folder:
            path = bank_for(tapes, Path(folder))
            h = TapeHistory([tape("dev")])
            values = [
                execute(
                    tapes,
                    h,
                    path,
                    policy_name="jev_" + objective,
                    agents=1,
                    capacity=3,
                    window_s=10,
                    seed=248,
                    samples=4,
                )
                for objective in ["own", "full"]
            ]
            self.assertEqual(values[0]["speculative_calls"], values[1]["speculative_calls"])
            self.assertAlmostEqual(values[0]["mean_completion_s"], values[1]["mean_completion_s"])


if __name__ == "__main__":
    unittest.main()


class KevDemoAdapterTests(unittest.TestCase):
    def test_demo_sse_contract_retains_gpu_and_total_latency(self):
        import httpx

        from quota_spec.adapters import KevSpacePredictor

        response = {
            "model": "jaredpalmer/kev-0.8b",
            "answers": {
                key: {"type": "noul", "noul": 0.4} for key in ["reuse", "next", "continues"]
            },
            "usage": {"input_tokens": 20, "output_tokens": 5},
            "latency_ms": 12,
        }

        def handler(request):
            if request.method == "POST":
                return httpx.Response(200, json={"event_id": "fixture"})
            return httpx.Response(
                200, text="event: complete\ndata: " + json.dumps(["", response, ""]) + "\n\n"
            )

        history = TapeHistory([tape("dev")])
        _, state, agent, _ = next(iter(cases([tape()])))
        predictor = KevSpacePredictor(history, transport=httpx.MockTransport(handler))
        self.assertEqual(predictor.predict(state, agent).next_probability, 0.4)
        self.assertEqual(predictor.records[-1]["response"]["latency_ms"], 12)
        self.assertGreaterEqual(predictor.records[-1]["latency_s"], 0)

    def test_demo_quota_failure_never_becomes_a_forecast(self):
        import httpx

        from quota_spec.adapters import KevSpacePredictor

        def handler(request):
            if request.method == "POST":
                return httpx.Response(200, json={"event_id": "fixture"})
            return httpx.Response(200, text='event: error\ndata: {"error":"quota exceeded"}\n\n')

        history = TapeHistory([tape("dev")])
        _, state, agent, _ = next(iter(cases([tape()])))
        predictor = KevSpacePredictor(history, transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(ValueError, "prediction failed"):
            predictor.predict(state, agent)
        self.assertEqual(predictor.records[-1]["failure"], "ValueError")
