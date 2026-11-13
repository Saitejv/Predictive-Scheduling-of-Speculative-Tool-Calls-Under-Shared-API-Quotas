"""Hand-derived timelines, oracle accounting, and duration consistency."""

import copy
import math
import random
import unittest

from quota_spec.admission import Demand, rollout
from quota_spec.frozen_replay import FrozenReplay
from quota_spec.latency_study import (
    aggregate,
    change_durations,
    compact_tape_state,
    overlap_savings,
    perfect_predictions,
    perfect_serial_reference,
)
from quota_spec.models import AgentState, Call, KnownExecution, Observation, Snapshot
from quota_spec.perfect_gate import exact_gates
from quota_spec.policies import CurrentCapacity, NoSpeculation
from quota_spec.prediction import bounded_context
from tests.baseline.test_frozen_replay import tape


class LatencyAuditTests(unittest.TestCase):
    def test_inactive_episode_caches_cannot_change_tape_forecasts_or_rollouts(self):
        agent = AgentState("live", 0, 0, "thinking", 0)
        call = Call.search("next")
        state = Observation(
            0,
            "live",
            0,
            call,
            2,
            0,
            Snapshot(
                2,
                10,
                (agent,),
                (
                    KnownExecution("live", call, 2),
                    KnownExecution("finished", call, 100),
                ),
            ),
        )
        compact = compact_tape_state(state)
        self.assertEqual(len(compact.snapshot.executions), 1)
        self.assertEqual(bounded_context(state, agent), bounded_context(compact, agent))
        scenario = {"live": (Demand(1, 3, call),)}
        for admit in [False, True]:
            self.assertEqual(
                rollout(state, scenario, admit, 0.1, 30), rollout(compact, scenario, admit, 0.1, 30)
            )

    def fixture(self, parent=1, actor=0.5, generation=0.2, tool=1):
        t = tape()
        t["steps"][0]["tool_duration_s"] = parent
        w = t["steps"][0]["window"]
        w["observation_duration_s"] = generation / 2
        w["hypothetical_duration_s"] = generation / 2
        w["candidates"] = w["candidates"][:1]
        w["candidates"][0]["duration_s"] = tool
        t["steps"][1].update(actor_duration_s=actor, tool_duration_s=tool)
        return t

    def test_hand_completed_reuse_and_inflight_join(self):
        for parent, actor, generation, tool, finish, inflight in [
            (4, 3, 1, 4, 7.2, 0),
            (1, 0.5, 0.2, 4, 4.4, 1),
            (1, 0.5, 1.5, 4, 5.7, 0),
        ]:
            with self.subTest(parent=parent, actor=actor, generation=generation):
                t = self.fixture(parent, actor, generation, tool)
                base = FrozenReplay([t], 100, 10).run(NoSpeculation())["metrics"]
                spec = FrozenReplay([t], 100, 10).run(CurrentCapacity())["metrics"]
                self.assertAlmostEqual(spec["mean_completion_s"], finish)
                self.assertEqual(spec["inflight_hits"], inflight)
                self.assertAlmostEqual(
                    base["mean_completion_s"] - finish,
                    overlap_savings(parent, actor, generation, tool),
                )
                if generation == parent + actor:
                    self.assertEqual(spec["speculative_calls"], 0)

    def test_two_agent_timeline_one_shared_quota_and_exact_boundary(self):
        a = self.fixture(2, 2, 1, 2)
        b = copy.deepcopy(a)
        b["task_id"] = "b"
        b["steps"][0]["window"] = None
        no = FrozenReplay([a, b], 2, 10).run(NoSpeculation())
        spec = FrozenReplay([a, b], 3, 10).run(CurrentCapacity())
        self.assertEqual(no["metrics"]["task_finish_s"], {"a": 12.1, "b": 12.1})
        self.assertAlmostEqual(spec["metrics"]["task_finish_s"]["a"], 4.2)
        self.assertAlmostEqual(spec["metrics"]["task_finish_s"]["b"], 12.1)
        # Compare speculation to the SAME quota, not the cap=2 example above.
        same = FrozenReplay([a, b], 3, 10).run(NoSpeculation())
        self.assertAlmostEqual(same["metrics"]["task_finish_s"]["a"], 6.2)
        self.assertAlmostEqual(same["metrics"]["task_finish_s"]["b"], 12.1)
        for run in [no, spec, same]:
            starts = [e for e in run["events"] if e["event"] == "search_started"]
            for k in range(3):
                cap = 2 if run is no else 3
                self.assertLessEqual(sum(10 * k <= e["time_s"] < 10 * (k + 1) for e in starts), cap)
        self.assertTrue(
            any(e["event"] == "search_started" and e["time_s"] == 10 for e in spec["events"])
        )

    def test_answer_release_preserves_long_unused_work_and_quota_consumption(self):
        a = self.fixture()
        a["steps"][0]["window"]["candidates"][0].update(query="unused", duration_s=20)
        b = tape("b")
        b["steps"] = [b["steps"][0], b["steps"][-1]]
        b["steps"][0].update(query="Z", action="Search[Z]", window=None)
        results = []
        for release in [False, True]:
            run = FrozenReplay([a, b], 2, 10, max_active_agents=1, release_on_answer=release).run(
                CurrentCapacity()
            )
            m = run["metrics"]
            self.assertEqual(m["search_calls"], 4)
            self.assertEqual(m["unused_speculative_calls"], 1)
            self.assertAlmostEqual(m["task_finish_s"]["a"], 11.1)
            self.assertAlmostEqual(m["resource_makespan_s"], 20.3 if release else 21.5)
            self.assertAlmostEqual(m["answer_makespan_s"], 12.3 if release else 21.5)
            self.assertAlmostEqual(m["task_start_s"]["b"], 11.1 if release else 20.3)
            results.append(m)
        self.assertEqual(results[0]["search_calls"], results[1]["search_calls"])

    def test_duration_transform_preserves_actor_local_and_generation_and_original(self):
        t = tape()
        original = copy.deepcopy(t)
        for scale, fixed in [(2, None), (5, None), (10, None), (1, 1), (1, 2), (1, 5), (1, 10)]:
            out = change_durations([t], scale=scale, fixed=fixed)[0]
            for before, after in zip(t["steps"], out["steps"]):
                self.assertEqual(before["actor_duration_s"], after["actor_duration_s"])
                if before["tool"] == "search":
                    self.assertEqual(
                        after["tool_duration_s"],
                        fixed if fixed is not None else before["tool_duration_s"] * scale,
                    )
                else:
                    self.assertEqual(before["tool_duration_s"], after["tool_duration_s"])
                if before["window"]:
                    self.assertEqual(
                        before["window"]["observation_duration_s"],
                        after["window"]["observation_duration_s"],
                    )
                    for c, d in zip(before["window"]["candidates"], after["window"]["candidates"]):
                        self.assertEqual(
                            d["duration_s"], fixed if fixed is not None else c["duration_s"] * scale
                        )
        self.assertEqual(t, original)

    def test_perfect_predictor_can_invent_missing_candidate_but_gate_cannot(self):
        t = self.fixture(4, 1, 1, 4)
        t["steps"][0]["window"]["candidates"][0].update(query="wrong", action="Search[wrong]")
        gate = exact_gates([t], 100, 1, agents=1)["winners"]["pipeline_latency"]["metrics"]
        f = FrozenReplay(
            perfect_predictions([t]),
            100,
            1,
            suppress_known_calls=True,
            max_candidate_age=999,
            generate_on_reuse=True,
        ).run(CurrentCapacity())["metrics"]
        self.assertAlmostEqual(gate["mean_completion_s"], 9.2)
        self.assertAlmostEqual(f["mean_completion_s"], 5.2)
        self.assertEqual(f["speculative_calls"], 1)

    def test_perfect_predictor_can_generate_after_reuse_without_recursive_predictions(self):
        t = self.fixture(4, 1, 0.2, 4)
        middle = copy.deepcopy(t["steps"][1])
        middle.update(query="C", action="Search[C]")
        middle["window"] = copy.deepcopy(t["steps"][0]["window"])
        t["steps"].insert(2, middle)
        t["steps"][1]["window"] = copy.deepcopy(t["steps"][0]["window"])
        transformed = perfect_predictions([t])
        old = FrozenReplay(
            transformed, 100, 1, suppress_known_calls=True, max_candidate_age=999
        ).run(CurrentCapacity())
        new = FrozenReplay(
            transformed,
            100,
            1,
            suppress_known_calls=True,
            max_candidate_age=999,
            generate_on_reuse=True,
        ).run(CurrentCapacity())
        self.assertEqual(new["metrics"]["speculative_calls"], 2)
        self.assertLess(new["metrics"]["mean_completion_s"], old["metrics"]["mean_completion_s"])
        self.assertEqual(new["metrics"]["observation_runs"], 2)

    def test_independent_perfect_recurrence_matches_random_tool_message_chains(self):
        rng = random.Random(7103)
        for _ in range(100):
            t = tape()
            t["steps"] = [copy.deepcopy(t["steps"][0]) for _ in range(5)] + [t["steps"][-1]]
            for i, s in enumerate(t["steps"][:-1]):
                s.update(
                    query=str(i),
                    action=f"Search[{i}]",
                    actor_duration_s=rng.uniform(0.1, 3),
                    tool_duration_s=rng.uniform(0.1, 10),
                )
                s["window"]["observation_duration_s"] = rng.uniform(0.1, 2)
                s["window"]["hypothetical_duration_s"] = rng.uniform(0.1, 2)
            for zero in [False, True]:
                reference = perfect_serial_reference(t, zero_overhead=zero)
                actual = FrozenReplay(
                    perfect_predictions([t], zero_overhead=zero),
                    10000,
                    1,
                    max_candidate_age=999,
                    suppress_known_calls=True,
                    generate_on_reuse=True,
                ).run(CurrentCapacity())["metrics"]
                self.assertAlmostEqual(reference["completion_s"], actual["mean_completion_s"])
                self.assertEqual(reference["cache_hits"], actual["cache_hits"])

    def test_exact_gate_forwards_duration_and_worker_release_options(self):
        t = self.fixture()
        solved = exact_gates([t], 100, 10, agents=1, tool_duration_s=5, release_on_answer=True)
        m = solved["winners"]["pipeline_latency"]["metrics"]
        self.assertTrue(m["release_on_answer"])
        self.assertAlmostEqual(m["mean_completion_s"], 5.7)

    def test_more_lookahead_is_a_separately_charged_architecture(self):
        t = self.fixture(4, 1, 3, 4)
        t["steps"][1]["window"] = copy.deepcopy(t["steps"][0]["window"])
        third = copy.deepcopy(t["steps"][1])
        third.update(action="Search[C]", query="C")
        t["steps"].insert(2, third)
        finish = []
        for lookahead in [1, None]:
            data = perfect_predictions([t], lookahead=lookahead)
            m = FrozenReplay(
                data,
                100,
                10,
                generate_on_reuse=True,
                max_candidate_age=999,
                suppress_known_calls=True,
            ).run(CurrentCapacity())["metrics"]
            self.assertEqual(data[0]["steps"][0]["window"]["observation_duration_s"], 1.5)
            finish.append(m["mean_completion_s"])
        self.assertAlmostEqual(finish[0], 12.2)
        self.assertAlmostEqual(finish[1], 8.2)

    def test_common_required_cache_separates_reuse_from_speculative_overlap(self):
        t = self.fixture()
        t["steps"][1].update(action="Search[A]", query="A")
        t["steps"][0]["window"]["candidates"][0].update(action="Search[A]", query="A")
        legacy = FrozenReplay([t], 100, 10).run(NoSpeculation())["metrics"]
        cache = FrozenReplay([t], 100, 10, cache_required_results=True).run(NoSpeculation())[
            "metrics"
        ]
        speculative = FrozenReplay([t], 100, 10, cache_required_results=True).run(
            CurrentCapacity()
        )["metrics"]
        self.assertAlmostEqual(legacy["mean_completion_s"], 2.7)
        self.assertAlmostEqual(cache["mean_completion_s"], 1.7)
        self.assertEqual(cache["mean_completion_s"], speculative["mean_completion_s"])
        self.assertEqual(cache["search_calls"], 1)
        self.assertEqual(speculative["search_calls"], 1)
        self.assertEqual(cache["answers"], legacy["answers"])

    def test_perfect_prediction_still_pays_terminal_generation_without_source_screen(self):
        t = self.fixture()
        t["steps"][1]["window"] = copy.deepcopy(t["steps"][0]["window"])
        t["steps"][1]["window"]["observation_duration_s"] = 4
        full = FrozenReplay(
            perfect_predictions([t], screen_empty=False),
            100,
            10,
            generate_on_reuse=True,
            max_candidate_age=999,
            suppress_known_calls=True,
        ).run(CurrentCapacity())["metrics"]
        screened = FrozenReplay(
            perfect_predictions([t]),
            100,
            10,
            generate_on_reuse=True,
            max_candidate_age=999,
            suppress_known_calls=True,
        ).run(CurrentCapacity())["metrics"]
        self.assertEqual(full["mean_completion_s"], screened["mean_completion_s"])
        self.assertGreater(full["resource_makespan_s"], screened["resource_makespan_s"])
        self.assertEqual(full["observation_runs"], screened["observation_runs"] + 1)

    def test_percentage_aggregation_keeps_scenarios_and_metrics_separate(self):
        rows = []
        for workers, baseline, speculative in [(4, 215.93, 215.03), (2, 901.64, 848.01)]:
            for policy, t in [("A_none", baseline), ("E_pipeline", speculative)]:
                rows.append(
                    {
                        "duration": "native",
                        "capacity": 12 if workers == 4 else 6,
                        "window_s": 30 if workers == 4 else 60,
                        "workers": workers,
                        "release": False,
                        "age": 0,
                        "suppress": False,
                        "policy": policy,
                        "tasks": 30,
                        **{
                            k: t
                            for k in [
                                "mean_completion_s",
                                "p95_completion_s",
                                "answer_makespan_s",
                                "resource_makespan_s",
                                "worker_makespan_s",
                            ]
                        },
                        **{
                            k: 0
                            for k in [
                                "search_calls",
                                "speculative_calls",
                                "unused_speculative_calls",
                                "cache_hits",
                                "inflight_hits",
                                "observation_runs",
                                "hypothetical_runs",
                                "predictor_overhead_s",
                                "mean_required_wait_s",
                            ]
                        },
                    }
                )
        result = [r for r in aggregate(rows) if r["policy"] == "E_pipeline"]
        self.assertAlmostEqual(
            result[0]["resource_questions_s_gain_pct"], 100 * (215.93 / 215.03 - 1)
        )
        self.assertAlmostEqual(
            result[1]["resource_questions_s_gain_pct"], 100 * (901.64 / 848.01 - 1)
        )
        self.assertFalse(
            math.isclose(
                result[1]["resource_questions_s_gain_pct"],
                result[1]["resource_makespan_s_reduction_pct"],
            )
        )


if __name__ == "__main__":
    unittest.main()
