import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.paper import REVISION
from quota_spec.paper_reproduction import action_scores, agreement_summary, single_agent_timing


def timing_row(delay=1, candidate="Search[second]"):
    return {
        "normal": {"actions": ["Search[first]", "Search[second]"]},
        "simulated": {"actions": [["Search[first]"], [candidate]], "time_taken": [delay, 0]},
        "timings": [{"actor": 1}, {"actor": 2, "speculative_actor": 1}],
        "trace": {"steps": [{"think_s": 1, "duration_s": 10}, {"think_s": 2, "duration_s": 8}]},
    }


class ReproductionMetricsTests(unittest.TestCase):
    def test_strict_top_three_does_not_credit_upstream_over_width_candidate(self):
        actual = {"actions": ["Search[first]", "Search[target]"]}
        predicted = {
            "actions": ["Search[first]", ["Search[a]", "Search[b]", "Search[c]", "Search[target]"]]
        }
        result = action_scores(actual, predicted, 3)
        self.assertEqual(result["accuracy"], 0)
        self.assertEqual(result["upstream_accuracy"], 1)
        self.assertEqual(result["over_width_scored_actions"], 1)

    def test_published_macro_and_action_weighted_micro_are_distinct(self):
        rows = [
            {
                "normal": {"actions": ["Search[first]", "Finish[x]"]},
                "simulated": {"actions": ["Search[first]", "finish[X]"]},
            },
            {
                "normal": {"actions": ["Search[first]", "Search[x]", "Search[y]", "Finish[z]"]},
                "simulated": {"actions": [[], [], [], []]},
            },
        ]
        result = agreement_summary(rows)["top1"]
        self.assertEqual(result["macro_accuracy"], 0.5)
        self.assertEqual(result["micro_accuracy"], 0.25)
        self.assertAlmostEqual(result["task_sem"], 0.5)

    def test_top_one_and_three_are_prefixes_of_the_same_branch_list(self):
        actual = {"actions": ["Search[first]", "Search[target]"]}
        predicted = {"actions": [[], ["Search[a]", "Search[b]", "Search[target]"]]}
        self.assertEqual(action_scores(actual, predicted, 1)["accuracy"], 0)
        self.assertEqual(action_scores(actual, predicted, 3)["accuracy"], 1)

    def test_shape_mismatch_is_not_a_successful_partial_score(self):
        with self.assertRaises(ValueError):
            action_scores({"actions": ["Search[a]"]}, {"actions": []}, 1)

    def test_no_quota_overlap_reuses_only_exact_on_time_search(self):
        result = single_agent_timing(timing_row(), 1)
        self.assertEqual(result["sequential_s"], 21)
        self.assertEqual(result["speculative_s"], 13)
        self.assertEqual(result["exact_prefetch_hits"], 1)
        for delay in (11, 50):  # Ties and late proposals yield no improvement.
            late = single_agent_timing(timing_row(delay), 1)
            self.assertEqual(late["speculative_s"], 21)
            self.assertEqual(late["exact_prefetch_hits"], 0)

    def test_casefolded_agreement_does_not_authorize_case_insensitive_cache_reuse(self):
        row = timing_row(candidate="Search[SECOND]")
        self.assertEqual(action_scores(row["normal"], row["simulated"], 1)["accuracy"], 1)
        self.assertEqual(single_agent_timing(row, 1)["exact_prefetch_hits"], 0)

    def test_stateful_lookup_is_always_executed_on_authoritative_state(self):
        row = timing_row(candidate="Lookup[word]")
        row["normal"]["actions"][1] = "Lookup[word]"
        result = single_agent_timing(row, 1)
        self.assertEqual(result["speculative_s"], result["sequential_s"])
        self.assertEqual(result["prefetched_searches"], 0)

    def test_third_candidate_can_prefetch_without_changing_first_candidate_result(self):
        row = timing_row(candidate="Search[wrong]")
        row["simulated"]["actions"][1] += ["Search[other]", "Search[second]"]
        self.assertEqual(single_agent_timing(row, 1)["exact_prefetch_hits"], 0)
        self.assertEqual(single_agent_timing(row, 3)["exact_prefetch_hits"], 1)

    def test_algorithm_one_does_not_speculate_from_a_cached_step(self):
        row = timing_row()
        row["normal"]["actions"].append("Search[third]")
        row["simulated"]["actions"].append(["Search[third]"])
        row["simulated"]["time_taken"].append(0)
        row["timings"].append({"actor": 2, "speculative_actor": 0})
        row["trace"]["steps"].append({"think_s": 2, "duration_s": 5})
        result = single_agent_timing(row, 3)
        self.assertEqual(result["exact_prefetch_hits"], 1)
        self.assertEqual(result["sequential_s"], 28)
        self.assertEqual(result["speculative_s"], 20)


class ReproductionIntegrationTests(unittest.TestCase):
    def test_mock_single_agent_entrypoint_never_invokes_jev_or_quota_study(self):
        import importlib.util

        from quota_spec.paper import run

        root = Path(__file__).resolve().parents[2] / "data/raw/speculative-action" / REVISION
        if not (root / "upstream.json").exists():
            self.skipTest("Prepare upstream source first")
        if any(
            importlib.util.find_spec(name) is None
            for name in ("gymnasium", "requests", "bs4", "pandas")
        ):
            self.skipTest("Install .[paper] for upstream integration")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline"
            args = argparse.Namespace(
                source=root,
                output=output,
                count=2,
                width=3,
                actor="mock",
                speculator="mock",
                max_requests=64,
                backend="mock",
                prepare_only=False,
            )
            with (
                patch("socket.socket.connect", side_effect=AssertionError("network")),
                patch(
                    "quota_spec.experiments.run_study", side_effect=AssertionError("quota study")
                ),
                patch("quota_spec.adapters.JevPredictor", side_effect=AssertionError("Jev")),
                patch("builtins.print"),
            ):
                result = run(args)
            self.assertTrue(result["complete"])
            self.assertTrue(result["actual_reset_indices_match"])
            self.assertEqual(result["qa"], {"em": None, "f1": None})
            self.assertFalse(result["reproduction_established"])
            self.assertFalse(result["comparable_to_figure4"])
            self.assertFalse((output / "forecasts").exists())
            summary = json.loads((output / "summary.json").read_text())
            self.assertIsNone(summary["paper_hotpotqa_latency_target"])
            self.assertEqual(summary["candidate_count_audit"]["under_width"], 0)
            self.assertEqual(summary["candidate_count_audit"]["over_width"], 0)
            path = output / "traces/tasks/7107.json"
            row = json.loads(path.read_text())
            row["normal"]["actions"][0] = "Search[tampered]"
            path.write_text(json.dumps(row))
            from quota_spec.paper_reproduction import report_collection

            with self.assertRaisesRegex(ValueError, "checksum"):
                report_collection(output / "traces", Path(directory) / "tampered-report")


if __name__ == "__main__":
    unittest.main()
