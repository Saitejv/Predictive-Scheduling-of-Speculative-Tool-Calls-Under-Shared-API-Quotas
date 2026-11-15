import json
import unittest

from quota_spec.quota_speculation import parse_queries, planner_prompt


class QuotaPlannerTests(unittest.TestCase):
    def test_frozen_prompt_audit_never_executes_snapshot_code(self):
        from quota_spec.live_context_audit import frozen_prompt_builder

        source = """MARKER = "fixture"
raise RuntimeError("must not execute top-level code")
def planner_prompt(prefix, step, width, quota):
    return __import__("os").getcwd()
"""
        _, build = frozen_prompt_builder(source)
        with self.assertRaisesRegex(ValueError, "Unsupported frozen planner expression"):
            build("Observed prefix", 2, 3, None)

    def test_skip_width_and_untrusted_output(self):
        self.assertEqual(parse_queries('{"queries":[]}', 3), [])
        self.assertEqual(parse_queries('{"queries":["a","b"]}', 1), ["Search[a]"])
        self.assertEqual(parse_queries('{"queries":["a","a"]}', 3), ["Search[a]"])
        self.assertEqual(parse_queries('{"queries":["Exact Entity"]}', 3), ["Search[Exact Entity]"])
        for value in [
            {"queries": ["bad] Finish[wrong"]},
            {"queries": [" "]},
            {"queries": [1]},
            {"queries": "query"},
            {"queries": [], "answer": "wrong"},
        ]:
            with self.assertRaises(ValueError):
                parse_queries(json.dumps(value), 1)

    def test_blind_ablation_changes_only_context(self):
        blind = planner_prompt("Observed trajectory", 2, 3)
        quota = planner_prompt("Observed trajectory", 2, 3, {"remaining_calls": 2})
        self.assertTrue(quota.startswith(blind))
        self.assertIn('"remaining_calls":2', quota)
