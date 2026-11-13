"""Compare equal work and enforce the independent quota limit."""

import copy
import math
import unittest

from quota_spec.frozen_replay import FrozenReplay, scheduling_options
from quota_spec.policies import NoSpeculation
from quota_spec.throughput_audit import quota_lower_bound, reconcile_seconds, repeated_stream
from tests.baseline.test_frozen_replay import tape


class ThroughputAccountingTests(unittest.TestCase):
    def test_live_delta_reconciles_without_becoming_a_causal_claim(self):
        result = reconcile_seconds(7, 6.25, 6.4, 6.2)
        self.assertAlmostEqual(result["uncontrolled_path_and_service_difference_s"], 0.6)
        self.assertAlmostEqual(result["fixed_path_overlap_s"], 0.2)
        self.assertAlmostEqual(result["live_vs_service_playback_difference_s"], -0.05)
        self.assertAlmostEqual(result["observed_live_mean_answer_saving_s"], 0.75)
        self.assertIn("not a causal attribution", result["warning"])

    def test_nonfinite_or_negative_times_are_rejected(self):
        for value in [-1, math.nan, math.inf]:
            with self.assertRaises(ValueError):
                reconcile_seconds(value, 1, 1, 1)

    def test_quota_bound_counts_unique_queries_within_each_episode(self):
        a, b = tape("a"), tape("b")
        a["steps"].insert(2, copy.deepcopy(a["steps"][1]))
        bound = quota_lower_bound([a, b], 3, 10)
        self.assertEqual(bound["minimum_distinct_searches"], 4)
        self.assertEqual(bound["earliest_last_mandatory_dispatch_s"], 10)
        self.assertEqual(bound["batch_lower_bound_s"], 11)
        result = FrozenReplay([a, b], 3, 10, cache_required_results=True).run(NoSpeculation())
        self.assertGreaterEqual(result["metrics"]["resource_makespan_s"], 11)

    def test_bound_uses_fastest_available_speculative_service_conservatively(self):
        a = tape()
        a["steps"][0]["window"]["candidates"][0]["duration_s"] = 0.2
        bound = quota_lower_bound([a], 1, 10)
        self.assertEqual(bound["minimum_distinct_searches"], 2)
        self.assertAlmostEqual(bound["batch_lower_bound_s"], 10.2)

    def test_generation_only_predictions_cannot_inflate_mandatory_query_count(self):
        a = tape()
        bound = quota_lower_bound([a], 1, 10)
        self.assertEqual(bound["minimum_distinct_searches"], 2)
        self.assertEqual(quota_lower_bound([], 1, 10)["batch_lower_bound_s"], 0)

    def test_profiles_make_async_behavior_explicit_and_retain_historical_control(self):
        self.assertEqual(
            scheduling_options("legacy"),
            {
                "generation_trigger": "dispatch",
                "retry_candidates": False,
                "release_on_answer": False,
            },
        )
        self.assertEqual(
            scheduling_options("overlap"),
            {
                "generation_trigger": "request",
                "retry_candidates": True,
                "release_on_answer": True,
            },
        )
        with self.assertRaises(ValueError):
            scheduling_options("unknown")

    def test_repeated_stream_keeps_caches_episode_local_and_does_not_change_input(self):
        original = [tape()]
        snapshot = copy.deepcopy(original)
        result = repeated_stream(original, [], 100, 1, 2, repeats=3)
        self.assertEqual(original, snapshot)
        self.assertEqual(result["questions"], 3)
        self.assertEqual(result["baseline"]["search_calls"], 6)
        self.assertEqual(result["feasible_gate"]["search_calls"], 6)
        self.assertEqual(result["throughput_gain_percent"], 0)


if __name__ == "__main__":
    unittest.main()
