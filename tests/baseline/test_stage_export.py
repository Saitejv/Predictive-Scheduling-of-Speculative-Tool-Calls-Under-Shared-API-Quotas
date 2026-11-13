import copy
import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quota_spec.stage_export import build_graph, export


def fixture():
    events, records, requests, episodes = [], [], [], []

    def event(kind, t, episode, **fields):
        events.append({"event": kind, "time_s": t, "episode": episode, **fields})

    def model(number, start, end, episode, step, role):
        context = {"request_id": number, "episode": episode, "step": step, "role": role}
        record = {**context, "latency_s": end - start, "failure": None, "cost_usd": 0.001}
        records.append(record)
        requests.append(
            {
                "request_id": number,
                "http_status": 200,
                "request": {
                    "model": "fixture",
                    "messages": [{"role": "user", "content": episode + role}],
                },
                "response": {"choices": [{"message": {"content": "saved output"}}]},
            }
        )
        event(
            "inference_started",
            start,
            episode,
            **{k: v for k, v in context.items() if k != "episode"},
        )
        event(
            "inference_finished",
            end,
            episode,
            **{k: v for k, v in record.items() if k != "episode"},
        )

    def search(start, end, episode, step, query, speculative=False):
        fields = {"step": step, "query": query, "speculative": speculative}
        event("search_started", start, episode, **fields)
        event("search_finished", end, episode, duration_s=end - start, **fields)

    for mode, offset, first, second in (("sequential", 0, 1, 2), ("speculative", 1, 3, 6)):
        episode = "7:" + mode
        event("episode_started", offset, episode)
        model(first, offset + 0.01, offset + 0.1, episode, 1, "actor")
        event("required_action", offset + 0.11, episode, step=1, action="Search[A]")
        search(offset + 0.12, offset + 0.5, episode, 1, "A")
        model(second, offset + 0.51, offset + 0.6, episode, 2, "actor")
        event("required_action", offset + 0.61, episode, step=2, action="Search[B]")
        if mode == "sequential":
            search(offset + 0.62, offset + 0.7, episode, 2, "B")
        event("answer_ready", offset + 0.71, episode)
        event("episode_drained", offset + 0.72, episode)
        episodes.append(
            {
                "episode": episode,
                "question_index": 7,
                "mode": mode,
                "answer": "",
                "cache_hits": int(mode == "speculative"),
                "trajectory": [
                    {
                        "step": step,
                        "thought": "saved",
                        "action": f"Search[{query}]",
                        "observation": query + " observation",
                        "tool_wait_s": 0.1,
                        "prefetch_hit": mode == "speculative" and step == 2,
                    }
                    for step, query in ((1, "A"), (2, "B"))
                ],
            }
        )
    model(4, 1.13, 1.2, "7:speculative", 1, "observation_speculator")
    model(5, 1.21, 1.3, "7:speculative", 2, "speculative_actor")
    event(
        "candidates_ready",
        1.31,
        "7:speculative",
        step=2,
        on_time=True,
        actions=["Search[B]", "Search[b]", "Finish[unused]"],
    )
    event("prefetch_launched", 1.32, "7:speculative", step=2, query="B")
    search(1.33, 1.45, "7:speculative", 2, "B", True)
    events.sort(key=lambda e: e["time_s"])
    return (
        {"indices": [7], "max_steps": 7, "upstream": {}, "source_sha256": {}},
        episodes,
        records,
        requests,
        events,
    )


class StageExportTests(unittest.TestCase):
    def test_graph_preserves_branches_ranked_candidates_and_exact_reuse(self):
        graph, coverage = build_graph(*fixture())
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertEqual(coverage["requests_accounted_for"], 6)
        self.assertEqual(coverage["canonical_speculative_tapes"], ["7:speculative"])
        self.assertFalse(coverage["replay_ready"])
        applied = nodes["apply:7:speculative:2"]
        reused = [nodes[n] for n in applied["dependencies"] if nodes[n]["kind"] == "search"]
        self.assertEqual(len(reused), 1)
        self.assertTrue(reused[0]["speculative"])
        self.assertEqual(nodes["request:5"]["dependencies"], ["request:4"])
        self.assertEqual(nodes["request:6"]["dependencies"], ["apply:7:speculative:1"])
        self.assertNotEqual(
            nodes["request:1"]["request_sha256"], nodes["request:3"]["request_sha256"]
        )
        candidates = coverage["candidate_coverage"]
        self.assertEqual([c["rank"] for c in candidates], [1, 2, 3])
        self.assertEqual(len(candidates[0]["execution_nodes"]), 1)
        self.assertEqual(candidates[1]["execution_nodes"], [])
        self.assertIn("recorded_tool_execution", candidates[1]["missing"])
        self.assertFalse(candidates[2]["eligible_search"])
        self.assertIsNone(reused[0]["result"])
        self.assertTrue(coverage["missing_window_fields"])

    def test_rejects_duplicate_missing_and_cross_branch_request_records(self):
        for corruption in ("duplicate", "missing", "branch"):
            args = copy.deepcopy(fixture())
            if corruption == "duplicate":
                args[3].append(args[3][0])
            elif corruption == "missing":
                args[3].pop()
            else:
                args[2][0]["episode"] = "7:speculative"
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                build_graph(*args)

    def test_rejects_dependency_that_finishes_after_its_consumer(self):
        args = copy.deepcopy(fixture())
        for event in args[4]:
            if event["event"] == "inference_finished" and event["request_id"] == 4:
                event["time_s"] = 1.4
        with self.assertRaisesRegex(ValueError, "Dependency completes"):
            build_graph(*args)

    def test_export_is_network_blocked_self_contained_and_does_not_modify_source(self):
        config, episodes, records, requests, events = fixture()
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / "source", Path(temp) / "export"
            (source / "tasks").mkdir(parents=True)
            for name, value in (("config", config), ("summary", {})):
                (source / f"{name}.json").write_text(json.dumps(value))
            for name, rows in (("inference", records), ("requests", requests), ("events", events)):
                (source / f"{name}.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n")
            for task in episodes:
                (source / "tasks" / f"7-{task['mode']}.json").write_text(json.dumps(task))
            before = {
                p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
            }
            with (
                patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
                patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network")),
            ):
                coverage = export(source, output)
            self.assertEqual(coverage["events_accounted_for"], len(events))
            for path, data in before.items():
                self.assertEqual((source / path).read_bytes(), data)
                self.assertEqual((output / "evidence" / path).read_bytes(), data)
            manifest = json.loads((output / "manifest.json").read_text())
            for path, identity in manifest["files"].items():
                self.assertEqual(
                    hashlib.sha256((output / "evidence" / path).read_bytes()).hexdigest(),
                    identity["sha256"],
                )
            with self.assertRaises(ValueError):
                export(source, source / "nested")
            with self.assertRaises(ValueError):
                export(source, output)


if __name__ == "__main__":
    unittest.main()
