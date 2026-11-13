import copy
import unittest

from quota_spec.frozen_replay import FrozenReplay
from quota_spec.hotpot_runtime import measurement_protocol, paired_summary
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.speculation_audit import unlimited_reference
from tests.baseline.test_frozen_replay import tape


class TimingReferenceTests(unittest.TestCase):
    def test_new_runs_label_shared_model_pacing_without_rewriting_legacy_summaries(self):
        protocol = measurement_protocol("http", 1.1)
        self.assertEqual(protocol["kind"], "paced_model_submission")
        self.assertTrue(protocol["actor_and_optional_requests_share_pacing"])
        legacy = paired_summary([], [])
        labeled = paired_summary([], [], protocol=protocol)
        self.assertEqual(labeled.pop("measurement_protocol"), protocol)
        self.assertEqual(legacy, labeled)

    def test_mock_does_not_claim_to_apply_http_submission_pacing(self):
        self.assertEqual(measurement_protocol("mock", 1.1)["shared_model_submission_interval_s"], 0)
        with self.assertRaises(ValueError):
            measurement_protocol("http", -1)

    def test_reference_recovers_known_one_second_overlap(self):
        data = tape()
        baseline = unlimited_reference(data, False)
        speculative = unlimited_reference(data, True)
        self.assertAlmostEqual(baseline["completion_s"], 2.7)
        self.assertAlmostEqual(speculative["completion_s"], 1.7)
        self.assertEqual(speculative["cache_hits"], 1)

    def test_late_generation_cannot_turn_into_free_reuse(self):
        data = tape()
        data["steps"][0]["window"]["hypothetical_duration_s"] = 10
        self.assertEqual(
            unlimited_reference(data, True)["completion_s"],
            unlimited_reference(data, False)["completion_s"],
        )
        self.assertEqual(unlimited_reference(data, True)["cache_hits"], 0)

    def test_independent_recurrence_matches_heap_for_completed_and_inflight_hits(self):
        for actor_s, tool_s, guess_s in [(0, 0.3, 0.2), (0.5, 1, 0.2), (0.1, 3, 0.4), (4, 1, 0.2)]:
            data = copy.deepcopy(tape())
            data["steps"][1]["actor_duration_s"] = actor_s
            data["steps"][0]["window"]["candidates"][0]["duration_s"] = tool_s
            data["steps"][1]["tool_duration_s"] = tool_s
            data["steps"][0]["window"]["hypothetical_duration_s"] = guess_s
            for speculate, policy in [(False, NoSpeculation()), (True, CurrentCapacity())]:
                expected = unlimited_reference(data, speculate)
                actual = FrozenReplay([data], 10000, 1).run(policy)["metrics"]
                self.assertAlmostEqual(expected["completion_s"], actual["mean_completion_s"])
                self.assertEqual(expected["cache_hits"], actual["cache_hits"])


if __name__ == "__main__":
    unittest.main()
