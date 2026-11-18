"""Independent schedule, provenance, and observed-only LLM context checks."""

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, deque
from pathlib import Path

from quota_spec.artifacts import write_json
from quota_spec.frozen_replay import load_dataset
from quota_spec.hotpot_runtime import split_action
from quota_spec.models import Call
from quota_spec.quota_speculation import parse_queries
from quota_spec.team_context import admission_response_format, gate_prompt


def audit(root):
    protocol = json.loads((root / "protocol.json").read_text())
    tapes = {t["task_id"]: t for t in load_dataset(protocol["dataset"])["tapes"]}
    for name, sha in protocol["source_sha256"].items():
        archived = root / "source-snapshot" / name
        if not archived.exists() or hashlib.sha256(archived.read_bytes()).hexdigest() != sha:
            raise AssertionError(f"Missing or changed source: {name}")
    rows = json.loads((root / "rows.json").read_text())
    receipts = {}
    if (root / "requests.jsonl").exists():
        receipts = {
            r["request_id"]: r
            for r in map(json.loads, (root / "requests.jsonl").read_text().splitlines())
        }
    checked_contexts = 0
    for row in rows:
        run = json.loads(gzip.decompress((root / row["schedule"]).read_bytes()))
        events, metrics = run["events"], run["metrics"]
        answers = {tid: tapes[tid]["answer"] for tid in protocol["evaluation_ids"]}
        assert metrics["answers"] == answers
        times = metrics["per_agent_completion_s"]
        assert abs(sum(times.values()) / len(times) - row["mean_completion_s"]) < 1e-9
        assert metrics["resource_makespan_s"] >= metrics["answer_makespan_s"]
        queue, cached, counts, active = deque(), set(), Counter(), set()
        for event in events:
            kind, tid = event["event"], event.get("task_id")
            if kind == "task_started":
                active.add(tid)
                assert len(active) <= row["agents"]
            elif kind == "worker_released":
                active.remove(tid)
            elif kind == "required_ready":
                expected = tapes[tid]["steps"][event["step"] - 1]
                assert event["action"] == expected["action"]
                tool, query = split_action(event["action"])
                if tool == "search" and (tid, query) not in cached:
                    queue.append((tid, query))
            elif kind == "search_started":
                key = (tid, event["query"])
                window = math.floor(event["time_s"] / row["window_s"])
                counts[window] += 1
                assert counts[window] <= row["capacity"]
                if event["speculative"]:
                    assert not queue, "Optional dispatch jumped required FIFO"
                    cached.add(key)
                else:
                    assert queue.popleft() == key, "Required FIFO changed"
        assert not queue and not active
        for decision in run["decisions"]:
            forecast = decision["forecast"]
            if "context" not in forecast:
                continue
            context, when = forecast["context"], decision["requested_at_s"]
            assert context["configured_search_response_s"] == row["search_s"]
            record = receipts[forecast["receipt"]]
            prompt = gate_prompt(context)
            assert record["request"]["messages"][-1]["content"] == prompt
            assert record["request"]["response_format"] == admission_response_format(prompt)
            query = json.loads(context["owner"]["candidate"]["arguments_json"])["query"]
            content = record["response"]["choices"][0]["message"]["content"]
            assert parse_queries(content, 1) in ([], [f"Search[{query}]"])
            observed = context.get("observed_peers", {}).get("workers", [])
            registry = [(decision["task_id"], context["owner"], False)]
            registry += [(peer["worker"], peer, True) for peer in observed]
            for tid, agent, peer in registry:
                tape = tapes[tid]
                if "task" in agent:
                    assert agent["task"] == tape["question"][:2048]
                k = agent["completed_calls"]
                returned = k + int(agent["phase"] != "thinking")
                prefix = [
                    e for e in events if e.get("task_id") == tid and e["time_s"] <= when + 1e-10
                ]
                assert any(e["event"] == "actor_started" and e["step"] == k + 1 for e in prefix)
                returned_events = [e for e in prefix if e["event"] == "required_ready"]
                assert max([e["step"] for e in returned_events], default=0) >= returned
                expected_history = []
                for step in tape["steps"][:returned][-8:]:
                    call = (
                        Call.search(step["query"])
                        if step["tool"] == "search"
                        else Call(step["tool"], json.dumps({"value": step["query"]}))
                    )
                    expected_history.append(
                        dict(tool=call.tool, arguments_json=call.arguments_json)
                    )
                if "history" in agent:
                    assert agent["history"] == expected_history
                    excerpt = tape["steps"][k - 1].get("observed_excerpt", "")[:1024] if k else ""
                    assert agent["last_result" if peer else "excerpt"] == excerpt
                    intent = (
                        (tape["steps"][returned - 1].get("thought") or "")[:1024]
                        if returned
                        else ""
                    )
                    assert agent["last_returned_actor_intent" if peer else "actor_intent"] == intent
                assert agent["elapsed_s"] >= 0
            checked_contexts += 1
    return dict(
        passed=True,
        runs=len(rows),
        answers_preserved=True,
        required_fifo=True,
        shared_quota_valid=True,
        observed_contexts_checked=checked_contexts,
        source_files_checked=len(protocol["source_sha256"]),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    args = p.parse_args()
    result = audit(args.root)
    write_json(args.root / "independent-audit.json", result)
    print(json.dumps(result))
