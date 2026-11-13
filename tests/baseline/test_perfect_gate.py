import copy
import unittest

from quota_spec.frozen_replay import FrozenReplay
from quota_spec.perfect_gate import exact_gates, useful_keys
from quota_spec.policies import NoSpeculation
from tests.baseline.test_frozen_replay import tape


class PerfectGateTests(unittest.TestCase):
    def test_exact_gate_enumerates_all_subsets_without_inventing_candidates(self):
        data = tape()
        keys = useful_keys([data])
        self.assertEqual(keys, (("a", 1, 1),))
        solved = exact_gates([data], 100, 100, agents=1)
        self.assertEqual(solved["subsets"], 2)
        self.assertEqual(solved["schedule_evaluations"], 4)
        for row in solved["winners"].values():
            self.assertAlmostEqual(row["metrics"]["mean_completion_s"], 1.7)
            self.assertEqual(row["metrics"]["unused_speculative_calls"], 0)

    def test_global_perfect_gate_can_reject_a_correct_prefetch_to_protect_other_agent(self):
        a, b = copy.deepcopy(tape("a")), copy.deepcopy(tape("b"))
        for data in [a, b]:
            data["steps"][0]["actor_duration_s"] = 0
        a["steps"][1]["actor_duration_s"] = 3
        b["steps"][1]["actor_duration_s"] = 1
        b["steps"][0]["window"] = None
        keys = useful_keys([a, b])
        self.assertEqual(keys, (("a", 1, 1),))
        correct = FrozenReplay([a, b], 3, 10).run(forced=frozenset(keys))["metrics"]
        baseline = FrozenReplay([a, b], 3, 10).run(NoSpeculation())["metrics"]
        solved = exact_gates([a, b], 3, 10, agents=2)
        self.assertAlmostEqual(correct["mean_completion_s"], 7.6)
        self.assertAlmostEqual(baseline["mean_completion_s"], 7.1)
        self.assertEqual(solved["winners"]["pipeline_latency"]["selected"], [])
        self.assertAlmostEqual(
            solved["winners"]["pipeline_latency"]["metrics"]["mean_completion_s"], 7.1
        )

    def test_perfect_tool_gate_still_pays_generation_but_pipeline_gate_can_skip_it(self):
        data = tape()
        data["steps"][0]["window"]["hypothetical_duration_s"] = 10
        self.assertEqual(useful_keys([data]), ())
        solved = exact_gates([data], 100, 100, agents=1)
        post = solved["winners"]["post_throughput"]["metrics"]
        pre = solved["winners"]["pipeline_throughput"]["metrics"]
        self.assertAlmostEqual(post["mean_completion_s"], pre["mean_completion_s"])
        self.assertGreater(post["resource_makespan_s"], pre["resource_makespan_s"])
        self.assertEqual(pre["observation_runs"], 0)

    def test_nonselected_windows_do_not_create_new_tool_calls_or_see_online_policy(self):
        class Spy:
            def admit(self, *args):
                raise AssertionError("oracle data reached online policy")

        result = FrozenReplay([tape()], 100, 100).run(
            Spy(), forced=frozenset(), generation_windows=frozenset()
        )
        self.assertEqual(result["metrics"]["search_calls"], 2)
        self.assertEqual(result["metrics"]["speculative_calls"], 0)
        self.assertEqual(result["metrics"]["answers"], {"a": "answer"})

    def test_zero_recording_mode_preserves_all_timing_metrics(self):
        replay = FrozenReplay([tape()], 100, 100)
        keys = frozenset(useful_keys([tape()]))
        recorded = replay.run(forced=keys)
        silent = replay.run(forced=keys, record_events=False, record_decisions=False)
        self.assertEqual(recorded["metrics"], silent["metrics"])
        self.assertEqual(silent["events"], [])
        self.assertEqual(silent["decisions"], [])

    def test_extended_lifetime_prunes_calls_already_requested_before_generation(self):
        data = tape()
        data["steps"][0]["window"]["hypothetical_duration_s"] = 2.0
        raw = useful_keys([data], max_candidate_age=1)
        self.assertEqual(raw, (("a", 1, 1),))
        options = {"max_candidate_age": 1, "suppress_known_calls": True}
        self.assertEqual(useful_keys([data], **options), ())
        pruned = exact_gates([data], 2, 10, agents=1, **options)
        full = exact_gates([data], 2, 10, agents=1, keys=raw, **options)
        for name in full["winners"]:
            self.assertEqual(full["winners"][name]["metrics"], pruned["winners"][name]["metrics"])

    def test_extended_lifetime_keeps_candidate_that_can_start_during_next_actor(self):
        data = tape()
        middle = copy.deepcopy(data["steps"][1])
        middle.update(action="Search[C]", query="C", actor_duration_s=0.1)
        data["steps"].insert(1, middle)
        data["steps"][0]["window"]["hypothetical_duration_s"] = 1.1
        options = {"max_candidate_age": 1, "suppress_known_calls": True}
        self.assertEqual(useful_keys([data]), ())
        self.assertEqual(useful_keys([data], **options), (("a", 1, 1),))
        baseline = FrozenReplay([data], 100, 1, **options).run(NoSpeculation())["metrics"]
        solved = exact_gates([data], 100, 1, agents=1, **options)
        self.assertLess(
            solved["winners"]["pipeline_latency"]["metrics"]["mean_completion_s"],
            baseline["mean_completion_s"],
        )


if __name__ == "__main__":
    unittest.main()
