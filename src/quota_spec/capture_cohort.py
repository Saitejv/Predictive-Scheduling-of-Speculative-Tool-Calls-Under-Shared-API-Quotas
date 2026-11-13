"""Select complete captured pairs and assemble disjoint completed tape shards."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from .artifacts import write_json
from .capture import CaptureStore
from .capture_bank import generation_span
from .frozen_replay import load_dataset


def select_pairs(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError("Choose a fresh selection directory")
    config = json.loads((source / "config.json").read_text())
    keep, tasks = [], []
    recorded_nodes = [
        json.loads(line) for line in (source / "capture/nodes.jsonl").read_text().splitlines()
    ]
    bad_episodes = {
        n["episode"]
        for n in recorded_nodes
        if n["status"] != "completed"
        or (
            config["backend"] == "http"
            and n["kind"] == "model"
            and n.get("usage", {}).get("cost_usd") is None
        )
    }
    for index in config["indices"]:
        pair = [source / "tasks" / f"{index}-{mode}.json" for mode in ("sequential", "speculative")]
        if all(
            p.exists()
            and json.loads(p.read_text())["failure"] is None
            and json.loads(p.read_text())["episode"] not in bad_episodes
            for p in pair
        ):
            keep.append(index)
            tasks.extend(pair)
    if not keep:
        raise ValueError("No complete question pairs")
    episodes = {json.loads(p.read_text())["episode"] for p in tasks}
    output.mkdir(parents=True)
    (output / "tasks").mkdir()
    for p in tasks:
        shutil.copyfile(p, output / "tasks" / p.name)
    shutil.copytree(source / "source-snapshot", output / "source-snapshot")
    shutil.copytree(source / "capture", output / "capture")
    captured = output / "capture"
    for name in ("nodes.jsonl", "journal.jsonl", "steps.jsonl"):
        rows = [json.loads(line) for line in (captured / name).read_text().splitlines()]
        rows = [r for r in rows if r["episode"] in episodes]
        (captured / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
    nodes = [json.loads(line) for line in (captured / "nodes.jsonl").read_text().splitlines()]
    request_ids = {n["request_id"] for n in nodes if n["kind"] == "model" and "request_id" in n}
    for name in ("inference.jsonl", "events.jsonl", "requests.jsonl"):
        if (source / name).exists():
            rows = [json.loads(line) for line in (source / name).read_text().splitlines()]
            rows = [
                r
                for r in rows
                if (
                    r.get("episode") in episodes
                    if "episode" in r
                    else r["request_id"] in request_ids
                )
            ]
            (output / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
    if (source / "pricing.json").exists():
        shutil.copyfile(source / "pricing.json", output / "pricing.json")
    config["selection_provenance"] = {
        "source": str(source.resolve()),
        "source_config_sha256": hashlib.sha256((source / "config.json").read_bytes()).hexdigest(),
        "excluded_indices": [i for i in config["indices"] if i not in keep],
        "note": "Complete pairs only; aborted attempts and their costs retained in original run",
    }
    config["indices"] = keep
    write_json(output / "config.json", config)
    manifest = json.loads((captured / "manifest.json").read_text())
    manifest.update(
        nodes=len(nodes),
        files={
            str(p.relative_to(captured)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(captured.rglob("*"))
            if p.is_file() and p.name != "manifest.json"
        },
    )
    write_json(captured / "manifest.json", manifest)
    from .hotpot_runtime import paired_summary

    records = (
        [json.loads(line) for line in (output / "inference.jsonl").read_text().splitlines()]
        if (output / "inference.jsonl").exists()
        else []
    )
    write_json(
        output / "summary.json",
        paired_summary(
            [json.loads(p.read_text()) for p in tasks],
            records,
            protocol=config.get("measurement_protocol"),
        ),
    )
    return keep


def merge_datasets(parts, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a fresh merged dataset directory")

    def flatten(paths):
        result = []
        for path in paths:
            path = Path(path)
            value = load_dataset(path)
            if "parts" in value:
                result += flatten([path / "parts" / p["shard"] for p in value["parts"]])
            else:
                result.append(path)
        return result

    parts = flatten(parts)
    data = [load_dataset(p) for p in parts]
    tasks = [t["task_id"] for d in data for t in d["tapes"]]
    if len(tasks) != len(set(tasks)):
        raise ValueError("Cohort shards overlap")
    output.mkdir(parents=True)
    tapes, cases, labels, provenance = [], [], [], []
    for index, (source, dataset) in enumerate(zip(parts, data, strict=True)):
        source = Path(source)
        shard = f"part-{index}"
        shutil.copytree(source, output / "parts" / shard)
        stores = {
            "live": CaptureStore(source / "live-capture"),
            "bank": CaptureStore(source / "completion"),
        }
        for task in dataset["tapes"]:
            task["shard"] = shard
            # Re-derive service versus collection queue consistently from the
            # immutable nodes, including shards produced by earlier exporters.
            for row in task["steps"]:
                actor = stores["live"].by_id[row["actor_node"]]
                row["actor_duration_s"] = generation_span(stores["live"], actor)
                if row["window"]:
                    window = row["window"]
                    obs_store, hyp_store = (
                        stores[window["observation_store"]],
                        stores[window["hypothetical_store"]],
                    )
                    window["observation_duration_s"] = obs_store.by_id[window["observation_node"]][
                        "service_s"
                    ]
                    window["hypothetical_duration_s"] = generation_span(
                        hyp_store, hyp_store.by_id[window["hypothetical_node"]]
                    )
            tapes.append(task)
        cases += json.loads((source / "forecast-cases.json").read_text())
        labels += json.loads((source / "forecast-labels.json").read_text())
        provenance.append(
            {
                "shard": shard,
                "source": str(source.resolve()),
                "manifest_sha256": hashlib.sha256(
                    (source / "dataset-manifest.json").read_bytes()
                ).hexdigest(),
            }
        )
    write_json(
        output / "tapes.json",
        {
            "version": 1,
            "complete": True,
            "tapes": tapes,
            "assumptions": data[0]["assumptions"]
            + [
                "Merged model durations re-derived from immutable service/parse timing; local pacing remains separate"
            ],
            "parts": provenance,
        },
    )
    write_json(output / "forecast-cases.json", cases)
    write_json(output / "forecast-labels.json", labels)
    write_json(
        output / "dataset-manifest.json",
        {
            "version": 1,
            "questions": len(tapes),
            "forecast_cases": len(cases),
            "files": {
                str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.rglob("*"))
                if p.is_file() and p != output / "dataset-manifest.json"
            },
        },
    )
    return {"questions": len(tapes), "forecast_cases": len(cases), "parts": provenance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select")
    select.add_argument("source", type=Path)
    select.add_argument("--output", type=Path, required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("parts", nargs="+", type=Path)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            select_pairs(args.source, args.output)
            if args.command == "select"
            else merge_datasets(args.parts, args.output),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
