"""Quota waiting is useful prediction time; ready candidates survive resets."""

import copy
import unittest

from quota_spec.forecast_study import validate
from quota_spec.frozen_replay import FrozenReplay
from quota_spec.perfect_gate import exact_gates, useful_keys
from quota_spec.policies import CurrentCapacity, NoSpeculation
from tests.baseline.test_frozen_replay import tape


def queued_source():
    a, b = tape("a"), tape("b")
    a["steps"] = [a["steps"][0], a["steps"][-1]]
    a["steps"][0].update(tool_duration_s=0.1, window=None)
    b["steps"][0].update(actor_duration_s=0.2, tool_duration_s=1)
    window = b["steps"][0]["window"]
    window.update(observation_duration_s=6, hypothetical_duration_s=6)
    window["candidates"] = window["candidates"][:1]
    b["steps"][1]["actor_duration_s"] = 10
    return [a, b]


class QuotaOverlapTests(unittest.TestCase):
    def run_case(self, tapes, **options):
        result = FrozenReplay(
            tapes,
            1,
            10,
            max_active_agents=2,
            max_candidate_age=999,
            suppress_known_calls=True,
            **options,
        ).run(CurrentCapacity())
        validate(result, tapes, 1, 10, 2)
        return result

    def test_generation_runs_while_its_required_source_waits_for_quota(self):
        tapes = queued_source()
        old = self.run_case(tapes, retry_candidates=True)
        new = self.run_case(tapes, generation_trigger="request", retry_candidates=True)
        self.assertAlmostEqual(old["metrics"]["resource_makespan_s"], 22.1)
        self.assertAlmostEqual(new["metrics"]["resource_makespan_s"], 21.1)
        generation = next(
            e for e in new["events"] if e["event"] == "generation_started" and e["task_id"] == "b"
        )
        self.assertAlmostEqual(generation["time_s"], 0.2)
        self.assertEqual(new["metrics"]["speculative_calls"], 1)
        self.assertEqual(new["metrics"]["cache_hits"], 1)

    def test_ready_candidate_is_reconsidered_at_reset_without_regeneration(self):
        tapes = queued_source()
        once = self.run_case(tapes, generation_trigger="request")
        retry = self.run_case(tapes, generation_trigger="request", retry_candidates=True)
        self.assertAlmostEqual(once["metrics"]["resource_makespan_s"], 22.1)
        self.assertAlmostEqual(retry["metrics"]["resource_makespan_s"], 21.1)
        self.assertEqual(retry["metrics"]["observation_runs"], 1)
        self.assertEqual(retry["metrics"]["hypothetical_runs"], 1)
        launch = next(
            e for e in retry["events"] if e["event"] == "search_started" and e["speculative"]
        )
        self.assertEqual(launch["time_s"], 20)
        self.assertEqual(retry["metrics"]["candidates_deferred"], 1)

    def test_unused_retry_timer_cannot_extend_resource_time_after_answer(self):
        t = tape()
        t["steps"] = [t["steps"][0], t["steps"][-1]]
        t["steps"][0]["tool_duration_s"] = 0.1
        t["steps"][-1]["actor_duration_s"] = 0.5
        result = self.run_case([t], generation_trigger="request", retry_candidates=True)
        self.assertAlmostEqual(result["metrics"]["answer_makespan_s"], 0.7)
        self.assertAlmostEqual(result["metrics"]["resource_makespan_s"], 0.7)
        self.assertEqual(result["metrics"]["speculative_calls"], 0)

    def test_required_call_has_priority_and_invalidates_duplicate_deferred_candidate(self):
        t = tape()
        t["steps"][0]["tool_duration_s"] = 0.1
        t["steps"][1]["actor_duration_s"] = 1
        result = self.run_case([t], generation_trigger="request", retry_candidates=True)
        self.assertAlmostEqual(result["metrics"]["resource_makespan_s"], 11.1)
        self.assertEqual(result["metrics"]["search_calls"], 2)
        self.assertEqual(result["metrics"]["speculative_calls"], 0)
        at_reset = [
            e for e in result["events"] if e["event"] == "search_started" and e["time_s"] == 10
        ]
        self.assertEqual(len(at_reset), 1)
        self.assertFalse(at_reset[0]["speculative"])

    def test_old_lateness_pruning_is_invalid_when_generation_overlaps_source_queue(self):
        tapes = queued_source()
        options = {"max_candidate_age": 999, "suppress_known_calls": True}
        self.assertEqual(useful_keys(tapes, **options), ())
        self.assertEqual(
            useful_keys(tapes, generation_trigger="request", **options), (("b", 1, 1),)
        )
        solved = exact_gates(
            tapes,
            1,
            10,
            agents=2,
            generation_trigger="request",
            retry_candidates=True,
            **options,
        )
        self.assertEqual(solved["subsets"], 2)
        self.assertAlmostEqual(
            solved["winners"]["pipeline_throughput"]["metrics"]["resource_makespan_s"], 21.1
        )

    def test_no_speculation_is_identical_under_both_generation_schedulers(self):
        tapes = queued_source()
        old = FrozenReplay(tapes, 1, 10).run(NoSpeculation())["metrics"]
        new = FrozenReplay(tapes, 1, 10, generation_trigger="request", retry_candidates=True).run(
            NoSpeculation()
        )["metrics"]
        self.assertEqual(old, new)

    def test_candidate_and_background_cost_are_preserved_across_worker_release(self):
        tapes = queued_source()
        for release in [False, True]:
            result = self.run_case(
                copy.deepcopy(tapes),
                generation_trigger="request",
                retry_candidates=True,
                release_on_answer=release,
            )
            self.assertEqual(result["metrics"]["search_calls"], 3)
            self.assertAlmostEqual(result["metrics"]["resource_makespan_s"], 21.1)


if __name__ == "__main__":
    unittest.main()
