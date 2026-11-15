import copy
import math
import socket
import unittest
from unittest.mock import patch

from quota_spec.frozen_replay import FrozenReplay
from quota_spec.policies import CurrentCapacity, NoSpeculation


def tape(identity="a"):
    return {
        "task_id": identity,
        "question": "Observed fixture",
        "answer": "answer",
        "steps": [
            {
                "action": "Search[A]",
                "tool": "search",
                "query": "A",
                "actor_duration_s": 0.1,
                "tool_duration_s": 1.0,
                "observed_excerpt": "Current result is not available before completion",
                "window": {
                    "observation_duration_s": 0.1,
                    "hypothetical_duration_s": 0.1,
                    "candidates": [
                        {
                            "rank": i,
                            "action": f"Search[{q}]",
                            "tool": "search",
                            "query": q,
                            "eligible": True,
                            "duration_s": 1.0,
                        }
                        for i, q in enumerate(("B", "wrong", "other"), 1)
                    ],
                },
            },
            {
                "action": "Search[B]",
                "tool": "search",
                "query": "B",
                "actor_duration_s": 0.5,
                "tool_duration_s": 1.0,
                "window": None,
            },
            {
                "action": "Finish[answer]",
                "tool": "finish",
                "query": "answer",
                "actor_duration_s": 0.1,
                "tool_duration_s": 0.0,
                "window": None,
            },
        ],
    }


class FrozenReplayTests(unittest.TestCase):
    def test_generation_budget_is_an_observed_step_rule_with_identical_required_work(self):
        saved = tape()
        saved["steps"][0]["window"]["candidates"] = []
        saved["steps"][1]["window"] = copy.deepcopy(saved["steps"][0]["window"])
        full = FrozenReplay([saved], 100, 100).run(CurrentCapacity())
        budgeted = FrozenReplay([saved], 100, 100, max_generation_step=1).run(CurrentCapacity())
        self.assertEqual(full["metrics"]["observation_runs"], 2)
        self.assertEqual(budgeted["metrics"]["observation_runs"], 1)
        self.assertEqual(budgeted["metrics"]["generation_windows_suppressed"], 1)
        self.assertEqual(full["metrics"]["answers"], budgeted["metrics"]["answers"])
        self.assertEqual(
            full["metrics"]["mean_completion_s"], budgeted["metrics"]["mean_completion_s"]
        )
        self.assertEqual(full["metrics"]["search_calls"], budgeted["metrics"]["search_calls"])

    def test_worker_pool_preserves_one_quota_across_successive_questions(self):
        result = FrozenReplay([tape(str(i)) for i in range(4)], 2, 10, max_active_agents=1).run(
            NoSpeculation()
        )
        self.assertGreater(result["metrics"]["resource_makespan_s"], 30)
        active = peak = 0
        for event in result["events"]:
            active += event["event"] == "task_started"
            active -= event["event"] == "task_drained"
            peak = max(peak, active)
        self.assertEqual(peak, 1)
        self.assertEqual(active, 0)
        self.assertEqual(len(result["metrics"]["answers"]), 4)

    def test_socket_blocked_matched_schedules_preserve_three_candidates_and_answers(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            sequential = FrozenReplay([tape()], 100, 100).run(NoSpeculation())
            speculative = FrozenReplay([tape()], 100, 100).run(CurrentCapacity())
        self.assertAlmostEqual(sequential["metrics"]["mean_completion_s"], 2.7)
        self.assertAlmostEqual(speculative["metrics"]["mean_completion_s"], 1.7)
        self.assertEqual(speculative["metrics"]["speculative_calls"], 3)
        self.assertEqual(speculative["metrics"]["unused_speculative_calls"], 2)
        self.assertEqual(speculative["metrics"]["answers"], sequential["metrics"]["answers"])
        self.assertEqual([d["rank"] for d in speculative["decisions"]], [1, 2, 3])

    def test_inflight_join_and_resource_drain_are_distinct_from_answer_latency(self):
        fixture = tape()
        fixture["steps"][0]["window"]["candidates"][0]["duration_s"] = 3.0
        fixture["steps"][0]["window"]["candidates"][1]["duration_s"] = 8.0
        fixture["steps"][1]["tool_duration_s"] = 3.0
        result = FrozenReplay([fixture], 100, 100).run(CurrentCapacity())["metrics"]
        self.assertEqual(result["inflight_hits"], 1)
        self.assertAlmostEqual(result["mean_completion_s"], 3.4)
        self.assertAlmostEqual(result["resource_makespan_s"], 8.3)

    def test_shared_quota_never_refunds_and_required_calls_keep_fifo_priority(self):
        result = FrozenReplay([tape("a"), tape("b")], 2, 10).run(CurrentCapacity())
        windows = {}
        for event in result["events"]:
            if event["event"] == "search_started":
                window = math.floor(event["time_s"] / 10)
                windows[window] = windows.get(window, 0) + 1
        self.assertTrue(all(count <= 2 for count in windows.values()))
        self.assertEqual(result["metrics"]["speculative_calls"], 0)
        self.assertGreater(result["metrics"]["mean_required_wait_s"], 0)
        started = [e["task_id"] for e in result["events"] if e["event"] == "search_started"]
        self.assertEqual(started, ["a", "b", "a", "b"])

    def test_case_sensitive_cache_and_late_prediction_does_not_launch(self):
        fixture = tape()
        fixture["steps"][1]["query"] = "b"
        fixture["steps"][1]["action"] = "Search[b]"
        self.assertEqual(
            FrozenReplay([fixture], 100, 100).run(CurrentCapacity())["metrics"]["cache_hits"], 0
        )
        fixture["steps"][0]["window"]["observation_duration_s"] = 10
        result = FrozenReplay([fixture], 100, 100).run(CurrentCapacity())["metrics"]
        self.assertEqual(result["speculative_calls"], 0)
        self.assertEqual(result["hypothetical_runs"], 0)

    def test_policy_receives_only_observed_context_and_stale_decision_is_rejected(self):
        class InspectPolicy:
            overhead_s = 1.5

            def admit(self, state):
                self_context = next(a for a in state.snapshot.agents if a.task_id == state.task_id)
                self.assertion = (
                    self_context.result_excerpt == "" and len(self_context.history) == 1
                )
                return True

        policy = InspectPolicy()
        result = FrozenReplay([copy.deepcopy(tape())], 100, 100).run(policy)
        self.assertTrue(policy.assertion)
        self.assertEqual(result["metrics"]["speculative_calls"], 0)


if __name__ == "__main__":
    unittest.main()
