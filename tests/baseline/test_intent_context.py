import copy
import unittest

from quota_spec.tape_forecasts import cases
from tests.baseline.test_frozen_replay import tape


class IntentContextTests(unittest.TestCase):
    def test_intent_is_available_only_after_its_authoritative_action_is_returned(self):
        saved = copy.deepcopy(tape())
        saved["steps"][0]["thought"] = "Observed plan before first Search"
        saved["steps"][1]["thought"] = "Future unreturned actor output"
        rows = list(cases([saved], mode="progress_intent", max_candidate_age=7))
        first = next(c for c, _, _, _ in rows if c["index"] == 0 and c["phase"] == "thinking")
        running = next(c for c, _, _, _ in rows if c["index"] == 0 and c["phase"] == "running")
        next_thinking = next(
            c for c, _, _, _ in rows if c["index"] == 1 and c["phase"] == "thinking"
        )
        self.assertEqual(first["context"]["actor_intent"], "")
        self.assertEqual(running["context"]["actor_intent"], "Observed plan before first Search")
        self.assertEqual(
            next_thinking["context"]["actor_intent"], "Observed plan before first Search"
        )
        self.assertNotIn("Future unreturned actor output", str(next_thinking["context"]))
        old = list(cases([saved], mode="progress", max_candidate_age=7))
        for previous, current in zip(old, rows, strict=True):
            context = dict(current[0]["context"])
            context.pop("actor_intent")
            self.assertEqual(context, previous[0]["context"])


if __name__ == "__main__":
    unittest.main()
