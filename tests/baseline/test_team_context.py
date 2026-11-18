import json
import unittest
from dataclasses import replace

from quota_spec.frozen_replay import FrozenReplay, scheduling_options
from quota_spec.models import AgentState, Call, Observation, Snapshot
from quota_spec.policies import NoSpeculation
from quota_spec.team_context import (
    LanguageAdmission,
    admission_response_format,
    gate_context,
    gate_prompt,
    peer_context,
)
from tests.baseline.test_frozen_replay import tape


def observed():
    owner = AgentState("a", 2, 0, "running", 1, task_context="Owner question")
    peer = AgentState(
        "b",
        2,
        1,
        "thinking",
        1.5,
        task_context="Peer question",
        history=(Call.search("observed query"),),
        result_excerpt="Observed result",
        intent="Last returned thought",
    )
    return Observation(
        2, "a", 0, Call.search("candidate"), 5, 0, Snapshot(8, 5, (owner, peer), (), (), ())
    )


class TeamContextTests(unittest.TestCase):
    def test_ablation_changes_only_peer_information(self):
        quota = gate_context(observed(), "quota", 3)
        team = gate_context(observed(), "team", 3)
        peers = team.pop("observed_peers")
        self.assertEqual(quota, team)
        self.assertNotIn("Peer question", json.dumps(quota))
        self.assertEqual(peers["workers"][0]["last_returned_actor_intent"], "Last returned thought")
        self.assertNotIn("candidate", peers["workers"][0])
        phases = peer_context(observed(), "phases")["workers"][0]
        self.assertEqual(phases["elapsed_s"], 0.5)
        self.assertNotIn("task", phases)

    def test_future_context_rejected_and_peer_payload_bounded(self):
        state = observed()
        future = replace(state.snapshot.agents[1], observed_at_s=3, phase_since_s=3)
        with self.assertRaisesRegex(ValueError, "Future observations"):
            peer_context(replace(state, snapshot=replace(state.snapshot, agents=(future,))))
        agents = tuple(
            replace(
                state.snapshot.agents[1],
                task_id=str(i),
                task_context="X" * 3000,
                result_excerpt="Y" * 2000,
                intent="Z" * 2000,
            )
            for i in range(20)
        )
        rows = peer_context(replace(state, snapshot=replace(state.snapshot, agents=agents)))
        self.assertEqual(len(rows["workers"]), 16)
        self.assertEqual(rows["omitted_workers"], 4)
        self.assertEqual(len(rows["workers"][0]["task"]), 2048)
        self.assertEqual(len(rows["workers"][0]["last_result"]), 1024)
        self.assertEqual(len(rows["workers"][0]["last_returned_actor_intent"]), 1024)

    def test_dynamic_schema_only_permits_supplied_candidate(self):
        prompt = gate_prompt(gate_context(observed(), "team"))
        schema = admission_response_format(prompt)["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["queries"]["items"]["enum"], ["candidate"])
        self.assertEqual(schema["properties"]["queries"]["maxItems"], 1)
        self.assertFalse(schema["additionalProperties"])

    def test_invented_query_is_rejected_even_if_provider_ignores_schema(self):
        policy = LanguageAdmission(lambda *args: ('{"queries":["different"]}', 0.2, 1))
        with self.assertRaisesRegex(ValueError, "invented a candidate"):
            policy.admit(observed())

    def test_paid_latency_runs_asynchronously_and_cannot_change_answers(self):
        fixture = tape()
        fixture["steps"][0]["window"]["candidates"] = fixture["steps"][0]["window"]["candidates"][
            :1
        ]

        def callback(prompt, state):
            return '{"queries":["B"]}', 10.0, 1

        slow = FrozenReplay([fixture], 100, 30, **scheduling_options("overlap")).run(
            LanguageAdmission(callback, detail="team")
        )
        base = FrozenReplay([fixture], 100, 30, **scheduling_options("overlap")).run(
            NoSpeculation()
        )
        self.assertEqual(slow["metrics"]["answers"], base["metrics"]["answers"])
        self.assertEqual(slow["metrics"]["mean_completion_s"], base["metrics"]["mean_completion_s"])
        self.assertGreater(
            slow["metrics"]["resource_makespan_s"], base["metrics"]["resource_makespan_s"]
        )
        self.assertEqual(slow["metrics"]["speculative_calls"], 0)
        self.assertEqual(slow["metrics"]["predictor_overhead_s"], 10)


if __name__ == "__main__":
    unittest.main()
