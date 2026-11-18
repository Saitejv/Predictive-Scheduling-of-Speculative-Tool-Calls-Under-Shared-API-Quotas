"""Independent audit of fresh query-planner comparisons and observed contexts."""

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, deque
from dataclasses import asdict
from pathlib import Path

from test_quota_team import prefixes_for

from quota_spec.artifacts import write_json
from quota_spec.frozen_replay import load_dataset
from quota_spec.live_context_audit import frozen_prompt_builder
from quota_spec.models import Call
from quota_spec.quota_speculation import parse_queries


def audit(root):
    config = json.loads((root / "protocol.json").read_text())
    data = load_dataset(config["dataset"])["tapes"]
    tapes = {t["task_id"]: t for t in data}
    selected = [tapes[tid] for tid in config["evaluation_ids"]]
    prefixes = prefixes_for(selected)
    for name, sha in config["source_sha256"].items():
        assert hashlib.sha256((root / "source-snapshot" / name).read_bytes()).hexdigest() == sha
    _, build = frozen_prompt_builder((root / "source-snapshot/quota_speculation.py").read_text())
    requests = {
        r["request_id"]: r
        for r in map(json.loads, (root / "requests.jsonl").read_text().splitlines())
    }
    inference = {
        r["request_id"]: r
        for r in map(json.loads, (root / "inference.jsonl").read_text().splitlines())
    }
    rows = (
        json.loads((root / "rows.json").read_text())
        if (root / "rows.json").exists()
        else [json.loads(line) for line in (root / "rows.jsonl").read_text().splitlines()]
    )
    generations, charged_retry_calls = 0, 0
    for row in rows:
        schedule = json.loads(gzip.decompress((root / row["schedule"]).read_bytes()))
        metrics = schedule["metrics"]
        assert metrics["answers"] == {t["task_id"]: t["answer"] for t in selected}
        assert (
            abs(
                sum(metrics["per_agent_completion_s"].values()) / len(selected)
                - row["mean_completion_s"]
            )
            < 1e-9
        )
        assert metrics["actor_runs"] == sum(len(t["steps"]) for t in selected)
        registry, action_counts, window_calls, queue, cached, required_times = (
            {},
            Counter(),
            Counter(),
            deque(),
            set(),
            [],
        )
        available_queries = {}
        for event in schedule["events"]:
            kind, tid, now = event["event"], event.get("task_id"), event["time_s"]
            if kind == "task_started":
                registry[tid] = dict(
                    worker=tid,
                    task=tapes[tid]["question"][:2048],
                    completed_calls=0,
                    phase="thinking",
                    since=now,
                    history=[],
                    last_result="",
                    last_returned_actor_intent="",
                )
                assert len(registry) <= row["agents"]
            elif kind == "actor_started":
                k = event["step"] - 1
                registry[tid].update(
                    phase="thinking",
                    since=now,
                    completed_calls=k,
                    last_result=tapes[tid]["steps"][k - 1].get("observed_excerpt", "")[:1024]
                    if k
                    else "",
                )
            elif kind == "required_ready":
                index = action_counts[tid]
                source = tapes[tid]["steps"][index]
                assert event["step"] == index + 1 and event["action"] == source["action"]
                action_counts[tid] += 1
                call = (
                    Call.search(source["query"])
                    if source["tool"] == "search"
                    else Call(source["tool"], json.dumps({"value": source["query"]}))
                )
                peer = registry[tid]
                peer["history"] = [*peer["history"][-7:], asdict(call)]
                peer.update(
                    phase="queued" if source["tool"] == "search" else "running",
                    since=now,
                    last_returned_actor_intent=(source.get("thought") or "")[:1024],
                )
                if source["tool"] == "search":
                    required_times.append(now)
                    if (tid, source["query"]) not in cached:
                        queue.append((tid, source["query"]))
            elif kind == "search_started":
                window = math.floor(now / row["window_s"])
                window_calls[window] += 1
                assert window_calls[window] <= row["capacity"]
                assert event["quota_remaining"] == row["capacity"] - window_calls[window]
                key = (tid, event["query"])
                if event["speculative"]:
                    assert any(ready <= now + 1e-9 for ready in available_queries.get(key, [])), (
                        "Query launched before planner response"
                    )
                    assert not queue
                    cached.add(key)
                else:
                    assert queue.popleft() == key
                    registry[tid].update(phase="running", since=now)
            elif kind == "inflight_joined":
                registry[tid].update(phase="running", since=now)
            elif kind == "answer_ready":
                registry.pop(tid)
            elif kind == "planner_generation_requested":
                generations += 1
                for query in event["queries"]:
                    available_queries.setdefault((tid, query), []).append(now + event["latency_s"])
                meta = event["provenance"]
                assert meta["planner"] == row["policy"]
                context = meta["quota"]
                if row["policy"] == "all":
                    assert context is None
                else:
                    index = math.floor(now / row["window_s"])
                    assert context["capacity"] == row["capacity"]
                    assert context["refill_period_s"] == row["window_s"]
                    assert context["observed_at_s"] == now
                    assert context["window_index"] == index
                    assert context["remaining_calls"] == row["capacity"] - window_calls[index]
                    assert (
                        abs(context["seconds_to_refill"] - ((index + 1) * row["window_s"] - now))
                        < 1e-9
                    )
                    assert context["active_workers"] == len(registry)
                    assert context["other_active_workers"] == len(registry) - 1
                    assert context["queued_required_calls"] == len(queue)
                    assert context["running_required_workers"] == sum(
                        p["phase"] == "running" for p in registry.values()
                    )
                    assert context["required_calls_in_current_window"] == sum(
                        t >= index * row["window_s"] for t in required_times
                    )
                    if row["policy"] == "quota_team":
                        peers = []
                        for other in sorted(set(registry) - {tid})[:16]:
                            peer = dict(registry[other])
                            since = peer.pop("since")
                            peer["elapsed_s"] = now - since
                            peers.append(peer)
                        assert context["observed_peers"] == dict(
                            workers=peers, omitted_workers=max(0, len(registry) - 1 - 16)
                        )
                    else:
                        assert "observed_peers" not in context
                prefix = prefixes[tid, event["step"]]
                assert meta["prefix_sha256"] == hashlib.sha256(prefix.encode()).hexdigest()
                assert config["prefix_sha256"][f"{tid}:{event['step']}"] == meta["prefix_sha256"]
                assert meta["hypothetical_step"] == event["step"] + 1
                expected = build(prefix, meta["hypothetical_step"], 3, context)
                ids = meta["receipts"]
                for identity in ids:
                    assert requests[identity]["request"]["messages"][-1]["content"] == expected
                final = requests[ids[-1]]
                schema = final["request"]["response_format"]["json_schema"]["schema"]
                assert schema["properties"]["queries"]["items"] == {"type": "string"}
                assert final["http_status"] == 200
                actions = parse_queries(final["response"]["choices"][0]["message"]["content"], 3)
                assert event["queries"] == [a[7:-1] for a in actions]
                assert event["latency_s"] >= sum(inference[i]["latency_s"] for i in ids)
                assert meta["collection_pacing_s"] >= 0
                charged_retry_calls += len(ids) - 1
        assert not registry and not queue
        assert action_counts == Counter({t["task_id"]: len(t["steps"]) for t in selected})
    return dict(
        passed=True,
        schedules=len(rows),
        fresh_generations_checked=generations,
        retries_with_delay_charged=charged_retry_calls,
        source_files_checked=len(config["source_sha256"]),
        authoritative_actions_answers_and_observations_preserved=True,
        quota_and_required_fifo_valid=True,
        exact_prompt_context_and_outputs_verified=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    args = p.parse_args()
    result = audit(args.root)
    write_json(args.root / "independent-audit.json", result)
    print(json.dumps(result))
