import math
import unittest
from dataclasses import fields

from quota_spec.models import Call, Observation, Step, Task, load_tasks
from quota_spec.policies import CurrentCapacity, FixedReserve, NoSpeculation
from quota_spec.quota import FixedWindowQuota
from quota_spec.replay import Replay, offline_reference
from quota_spec.workload import dump_tasks, synthetic_tasks


def task(tid="a", *, think=2, duration=1, candidate="q", query="q", arrival=0):
    return Task(
        tid,
        arrival,
        (
            Step(
                think,
                Call.search(query),
                duration,
                Call.search(candidate) if candidate else None,
                duration,
            ),
        ),
    )


class QuotaTests(unittest.TestCase):
    def test_fractional_refill_boundaries_do_not_stall(self):
        for window in (0.01, 0.1, 0.3):
            quota = FixedWindowQuota(1, window)
            self.assertTrue(quota.consume(0))
            for index in range(1, 100):
                boundary = index * window
                self.assertFalse(quota.consume(math.nextafter(boundary, 0)))
                self.assertTrue(quota.consume(boundary))
                self.assertGreater(quota.next_refill(boundary), boundary)

    def test_spending_is_not_refunded_by_time_before_boundary(self):
        quota = FixedWindowQuota(1, 10)
        self.assertTrue(quota.consume(0))
        self.assertFalse(quota.consume(9.999))
        self.assertTrue(quota.consume(10))
        self.assertEqual(quota.remaining(10), 0)
        self.assertEqual(quota.remaining(40), 1)

    def test_invalid_config_and_backward_clock(self):
        for capacity, window in [(0, 1), (1, 0), (1, float("nan")), (1.5, 2)]:
            with self.assertRaises(ValueError):
                FixedWindowQuota(capacity, window)
        quota = FixedWindowQuota(1, 1)
        quota.consume(3)
        with self.assertRaises(ValueError):
            quota.remaining(1)


class ReplayTests(unittest.TestCase):
    def test_completed_reuse_saves_time_and_charges_once(self):
        replay = Replay((task(),), 1, 10)
        baseline = replay.run(NoSpeculation()).metrics
        spec = replay.run(CurrentCapacity()).metrics
        self.assertEqual(baseline["mean_completion_s"], 3)
        self.assertEqual(spec["mean_completion_s"], 2)
        self.assertEqual(spec["calls_started"], 1)
        self.assertEqual(spec["reuse_hits"], 1)
        self.assertEqual(spec["unused_speculative_calls"], 0)

    def test_inflight_join_uses_remaining_execution(self):
        result = Replay((task(think=1, duration=3),), 1, 10).run(CurrentCapacity())
        self.assertEqual(result.metrics["mean_completion_s"], 3)
        self.assertEqual(result.metrics["calls_started"], 1)
        self.assertTrue(any(e["event"] == "inflight_joined" for e in result.events))

    def test_unused_call_does_not_restore_quota(self):
        result = Replay((task(candidate="wrong"),), 1, 10).run(CurrentCapacity()).metrics
        self.assertEqual(result["mean_completion_s"], 11)
        self.assertEqual(result["mean_required_wait_s"], 8)
        self.assertEqual(result["unused_speculative_calls"], 1)

    def test_exact_arguments_and_agent_scoping(self):
        tasks = (task(candidate="Q"), task("b", candidate=None))
        result = Replay(tasks, 3, 10).run(CurrentCapacity()).metrics
        self.assertEqual(result["calls_started"], 3)
        self.assertEqual(result["reuse_hits"], 0)

    def test_reserve_protects_capacity(self):
        result = Replay((task(candidate="wrong"),), 1, 10).run(FixedReserve(1)).metrics
        self.assertEqual(result["mean_completion_s"], 3)
        self.assertEqual(result["speculative_calls"], 0)

    def test_dependency_readiness_moves_with_reuse(self):
        steps = (
            Step(2, Call.search("first"), 1, Call.search("first"), 1),
            Step(2, Call.search("second"), 1),
        )
        replay = Replay((Task("a", 0, steps),), 3, 10)
        self.assertEqual(replay.run().metrics["mean_completion_s"], 6)
        self.assertEqual(replay.run(CurrentCapacity()).metrics["mean_completion_s"], 5)

    def test_required_work_wins_same_timestamp(self):
        result = Replay((task("a"), task("b", think=0, candidate=None)), 1, 10).run(
            CurrentCapacity()
        )
        starts = [e for e in result.events if e["event"] == "call_started"]
        self.assertEqual(starts[0]["task_id"], "b")
        self.assertFalse(starts[0]["speculative"])

    def test_offline_reference_rejects_cross_agent_harm(self):
        # A can save 1s but would make B wait 8s for the next window.
        replay = Replay((task("a", think=4), task("b", think=2, candidate=None)), 1, 10)
        baseline = replay.run().metrics
        greedy = replay.run(CurrentCapacity()).metrics
        reference = offline_reference(replay)
        self.assertGreater(greedy["mean_completion_s"], baseline["mean_completion_s"])
        self.assertFalse(reference.decisions[("a", 0)])
        self.assertEqual(reference.metrics["mean_completion_s"], baseline["mean_completion_s"])

    def test_offline_reference_accepts_useful_call(self):
        result = offline_reference(Replay((task(),), 1, 10))
        self.assertTrue(result.decisions[("a", 0)])

    def test_deadline_is_inclusive_and_wait_is_quota_queue_time(self):
        t = Task("a", 0, (Step(2, Call.search("q"), 1),), deadline_s=3)
        metrics = Replay((t,), 1, 10).run().metrics
        self.assertEqual(metrics["deadline_completion_rate"], 1)
        self.assertEqual(metrics["mean_required_wait_s"], 0)

    def test_online_input_does_not_contain_future_trace(self):
        self.assertEqual(
            {f.name for f in fields(Observation)},
            {
                "now_s",
                "task_id",
                "completed_calls",
                "candidate",
                "quota_remaining",
                "queued_required",
                "snapshot",
            },
        )

    def test_synthetic_roundtrip_and_repeatability(self):
        tasks = synthetic_tasks(8, 42)
        self.assertEqual(load_tasks(dump_tasks(tasks)), tasks)
        a = Replay(tasks, 3, 10).run(CurrentCapacity())
        b = Replay(tasks, 3, 10).run(CurrentCapacity())
        self.assertEqual(a.events, b.events)
        for key in a.metrics.keys() - {"replay_wall_s"}:
            self.assertEqual(a.metrics[key], b.metrics[key])

    def test_quota_never_exceeded_across_agent_sweep(self):
        for agents in (1, 2, 4, 8):
            result = Replay(synthetic_tasks(agents), 2, 10).run(CurrentCapacity())
            counts = {}
            for event in result.events:
                if event["event"] == "call_started":
                    window = int(event["time_s"] // 10)
                    counts[window] = counts.get(window, 0) + 1
            self.assertTrue(all(count <= 2 for count in counts.values()))
            self.assertEqual(result.metrics["tasks"], agents)

    def test_zero_duration_and_zero_think_terminate(self):
        result = Replay((task(think=0, duration=0),), 1, 0.1).run(CurrentCapacity())
        self.assertEqual(result.metrics["mean_completion_s"], 0)
        self.assertEqual(result.metrics["calls_started"], 1)


if __name__ == "__main__":
    unittest.main()
