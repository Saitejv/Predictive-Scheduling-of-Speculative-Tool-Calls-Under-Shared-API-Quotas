import copy
import socket
import unittest
from unittest.mock import patch

from quota_spec.admission import AdmissionConfig, Demand, PredictiveAdmission, rollout
from quota_spec.forecast_study import ReserveFloor, validate
from quota_spec.frozen_replay import FrozenReplay
from quota_spec.models import AgentState, Call, Observation, Snapshot
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.prediction import Forecast
from tests.baseline.test_frozen_replay import tape


class DelayedGate:
    def __init__(self, delay=0.1):
        self.overhead_s = delay
        self.states = []

    def admit(self, state):
        self.states.append(state)
        return True


def persistent_tape():
    data = copy.deepcopy(tape())
    data["steps"][0]["window"]["observation_duration_s"] = 0.9
    data["steps"][0]["window"]["hypothetical_duration_s"] = 0.9
    data["steps"][0]["window"]["candidates"] = data["steps"][0]["window"]["candidates"][:1]
    data["steps"][0]["window"]["candidates"][0].update(query="C", action="Search[C]")
    third = copy.deepcopy(data["steps"][1])
    third.update(query="C", action="Search[C]")
    data["steps"].insert(2, third)
    return data


class AsyncAdmissionTests(unittest.TestCase):
    def test_generation_budget_skips_optional_models_and_preserves_required_work(self):
        baseline = FrozenReplay([tape()], 3, 100).run(NoSpeculation())
        budgeted = FrozenReplay([tape()], 3, 100, generation_reserve=3).run(CurrentCapacity())
        self.assertEqual(budgeted["metrics"]["observation_runs"], 0)
        self.assertEqual(budgeted["metrics"]["hypothetical_runs"], 0)
        self.assertEqual(budgeted["metrics"]["generation_windows_suppressed"], 1)
        self.assertEqual(budgeted["metrics"]["search_calls"], 2)
        self.assertEqual(
            budgeted["metrics"]["mean_completion_s"], baseline["metrics"]["mean_completion_s"]
        )

    def test_cross_reset_gate_revalidates_quota_and_never_dispatches_after_finish(self):
        data = persistent_tape()
        data["steps"][0]["window"]["observation_duration_s"] = 0.1
        data["steps"][0]["window"]["hypothetical_duration_s"] = 0.1
        old = FrozenReplay([data], 100, 1).run(DelayedGate(0.9))
        new = FrozenReplay([data], 100, 1, revalidate_reset=True).run(DelayedGate(0.9))
        self.assertEqual(old["metrics"]["speculative_calls"], 0)
        self.assertEqual(new["metrics"]["speculative_calls"], 1)
        self.assertGreater(new["decisions"][0]["time_s"], 1)
        finished = FrozenReplay([data], 100, 1, revalidate_reset=True, max_candidate_age=1).run(
            DelayedGate(10)
        )
        self.assertEqual(finished["metrics"]["speculative_calls"], 0)

    def test_current_default_already_overlaps_next_actor_without_blocking_it(self):
        data = tape()
        data["steps"][0]["window"]["observation_duration_s"] = 0.55
        data["steps"][0]["window"]["hypothetical_duration_s"] = 0.55
        gate = DelayedGate(0.1)
        result = FrozenReplay([data], 100, 100).run(gate)
        own = next(a for a in gate.states[0].snapshot.agents if a.task_id == "a")
        self.assertEqual(own.phase, "thinking")
        self.assertEqual(own.completed_calls, 1)
        ready = [e for e in result["events"] if e["event"] == "required_ready" and e["step"] == 2][
            0
        ]
        self.assertAlmostEqual(ready["time_s"], 1.6)
        self.assertTrue(
            any(
                e["event"] == "search_started" and e["speculative"] and e["time_s"] > 1.1
                for e in result["events"]
            )
        )

    def test_inference_latency_is_charged_as_launch_delay_once(self):
        class Predictor:
            decision_overhead_s = 0.4

            def predict(self, state, agent):
                return Forecast(1, 1, (0.6,), (0.2,), 0)

        agent = AgentState("a", 0, 0, "thinking", 0)
        state = Observation(0, "a", 0, Call.search("C"), 10, 0, Snapshot(10, 10, (agent,)))
        old = PredictiveAdmission(Predictor(), AdmissionConfig(samples=4, overhead_s=0))
        new = PredictiveAdmission(
            Predictor(), AdmissionConfig(samples=4, overhead_s=0, nonblocking=True)
        )
        self.assertFalse(old.admit(state))
        self.assertTrue(new.admit(state))
        self.assertAlmostEqual(new.overhead_s, 0.4)
        self.assertAlmostEqual(new.last_decision["estimated_gain_s"], 0.2)

    def test_nonblocking_does_not_pause_required_work_to_invent_a_hit(self):
        agent = AgentState("a", 0, 0, "thinking", 0)
        state = Observation(0, "a", 0, Call.search("C"), 10, 0, Snapshot(10, 10, (agent,)))
        scenario = {"a": (Demand(0.1, 0.2, state.candidate),)}
        rejected = rollout(state, scenario, False, 0.4, 30, block_owner=False)
        admitted = rollout(state, scenario, True, 0.4, 30, block_owner=False)
        self.assertAlmostEqual(rejected["a"], 0.3)
        self.assertEqual(rejected, admitted)

    def test_one_step_persistence_reuses_late_candidate_without_future_inputs(self):
        data = persistent_tape()
        gate = DelayedGate(0.1)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            old = FrozenReplay([data], 100, 100).run(DelayedGate(0.1))
            new = FrozenReplay(
                [data], 100, 100, max_candidate_age=1, suppress_known_calls=True
            ).run(gate)
        self.assertEqual(old["metrics"]["speculative_calls"], 0)
        self.assertEqual(new["metrics"]["cache_hits"], 1)
        self.assertAlmostEqual(
            old["metrics"]["mean_completion_s"] - new["metrics"]["mean_completion_s"], 1
        )
        self.assertEqual(new["metrics"]["post_action_launches"], 1)
        own = gate.states[0].snapshot.agents[0]
        self.assertEqual(own.completed_calls, 1)
        self.assertEqual(own.phase, "running")
        self.assertEqual(len(own.history), 2)
        self.assertEqual(own.result_excerpt, data["steps"][0]["observed_excerpt"])

    def test_persisted_candidate_cannot_duplicate_already_running_required_call(self):
        data = persistent_tape()
        data["steps"][0]["window"]["candidates"][0].update(query="B", action="Search[B]")
        result = FrozenReplay([data], 100, 100, max_candidate_age=1, suppress_known_calls=True).run(
            CurrentCapacity()
        )
        self.assertEqual(result["metrics"]["speculative_calls"], 0)
        self.assertEqual(result["metrics"]["duplicate_candidates_suppressed"], 1)

    def test_detached_background_releases_worker_but_retains_spent_shared_quota(self):
        a, b = tape("a"), tape("b")
        for data in [a, b]:
            data["steps"][0]["window"]["candidates"][1]["duration_s"] = 8
        run = FrozenReplay([a, b], 20, 100, max_active_agents=1, release_on_answer=True).run(
            CurrentCapacity()
        )
        validate(run, [a, b], 20, 100, 1)
        finish_a = next(
            e["time_s"]
            for e in run["events"]
            if e["event"] == "answer_ready" and e["task_id"] == "a"
        )
        start_b = next(
            e["time_s"]
            for e in run["events"]
            if e["event"] == "task_started" and e["task_id"] == "b"
        )
        drain_a = next(
            e["time_s"]
            for e in run["events"]
            if e["event"] == "task_drained" and e["task_id"] == "a"
        )
        self.assertEqual(start_b, finish_a)
        self.assertLess(start_b, drain_a)
        self.assertGreater(
            run["metrics"]["resource_makespan_s"], run["metrics"]["answer_makespan_s"]
        )

    def test_reserve_is_checked_again_when_delayed_gates_finish(self):
        data = tape()
        gate = ReserveFloor(DelayedGate(0.1), 1)
        run = FrozenReplay([data], 3, 100).run(gate)
        self.assertEqual(run["metrics"]["speculative_calls"], 1)

    def test_age_and_ttl_expiration_still_stop_late_launches(self):
        data = persistent_tape()
        run = FrozenReplay([data], 100, 100, max_candidate_age=1, candidate_ttl_s=1).run(
            CurrentCapacity()
        )
        self.assertEqual(run["metrics"]["speculative_calls"], 0)


if __name__ == "__main__":
    unittest.main()
