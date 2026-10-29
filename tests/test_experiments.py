import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from quota_spec.admission import AdmissionConfig, PredictiveAdmission
from quota_spec.experiments import batches, bootstrap_ci
from quota_spec.models import load_tasks
from quota_spec.prediction import HistoryPredictor
from quota_spec.replay import Replay
from quota_spec.search import SearchCorpus
from quota_spec.workload import synthetic_tasks


class ExperimentTests(unittest.TestCase):
    def test_predictive_quota_budget_under_bursts_and_wrong_predictions(self):
        development = tuple(replace(t, task_id="dev-" + t.task_id) for t in synthetic_tasks(8, 42))
        history = HistoryPredictor.fit(development)
        from quota_spec.prediction import PerturbedPredictor

        for agents in (1, 2, 4, 8):
            for error in (0, 1):
                policy = PredictiveAdmission(
                    PerturbedPredictor(history, error), AdmissionConfig(samples=4, horizon_s=15)
                )
                result = Replay(synthetic_tasks(agents, 7), 2, 10).run(policy)
                counts = {}
                for event in result.events:
                    if event["event"] == "call_started":
                        index = int(event["time_s"] / 10)
                        counts[index] = counts.get(index, 0) + 1
                self.assertTrue(all(n <= 2 for n in counts.values()))
                self.assertEqual(result.metrics["tasks"], agents)

    def test_corpus_tampering_is_rejected_and_ranking_repeatable(self):
        corpus = SearchCorpus(
            [
                {"title": "Ada", "text": "Ada writes algorithms"},
                {"title": "Other", "text": "Other things"},
            ]
        )
        self.assertEqual(corpus.search("Ada"), corpus.search("Ada"))
        self.assertEqual(corpus.search("Ada")[0]["title"], "Ada")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            corpus.save(path)
            self.assertEqual(SearchCorpus.load(path).digest, corpus.digest)
            data = json.loads(path.read_text())
            data["documents"][0]["text"] = "tampered"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                SearchCorpus.load(path)

    def test_bootstrap_preserves_paired_run_differences(self):
        ci = bootstrap_ci([-1, -1, -1])
        self.assertEqual((ci["mean"], ci["low"], ci["high"]), (-1, -1, -1))
        with self.assertRaises(ValueError):
            bootstrap_ci([])

    def test_batch_concurrency_limit_and_reproducibility(self):
        tasks = synthetic_tasks(8)
        groups = list(batches(tasks, 2, 7, "burst", 0.1))
        self.assertTrue(all(len(group) <= 2 for group in groups))
        self.assertEqual(len({t.task_id for group in groups for t in group}), 8)
        self.assertEqual(groups, list(batches(tasks, 2, 7, "burst", 0.1)))

    def test_frozen_data_provenance_and_no_answer_labels_in_tasks(self):
        data = Path(__file__).resolve().parents[1] / "data"
        if not (data / "manifest.json").exists():
            self.skipTest("Run quota_spec.collect for dataset checks")
        manifest = json.loads((data / "manifest.json").read_text())
        dev = set(manifest["development_ids"])
        evaluation = set(manifest["evaluation_ids"])
        self.assertFalse(dev & evaluation)
        self.assertEqual(len(dev | evaluation), 200)
        self.assertEqual(SearchCorpus.load(data / "corpus.json").digest, manifest["corpus_sha256"])
        for name in ("development", "evaluation"):
            raw = json.loads((data / f"{name}.json").read_text())
            self.assertTrue(
                all("answer" not in row and "supporting_facts" not in row for row in raw)
            )
            self.assertEqual(len(load_tasks(raw)), 100)
