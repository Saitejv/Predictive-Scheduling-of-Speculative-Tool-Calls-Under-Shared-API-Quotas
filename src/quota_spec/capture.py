"""Versioned complete stage capture and immutable content-addressed JSON blobs."""

import contextvars
import copy
import hashlib
import json
import time
from pathlib import Path

from .artifacts import append_json, write_json

VERSION = 2
ACTIVE_CAPTURE = contextvars.ContextVar("active_capture", default=None)
STATE_FIELDS = (
    "page",
    "obs",
    "result_titles",
    "lookup_keyword",
    "lookup_list",
    "lookup_cnt",
    "steps",
    "answer",
    "sim_obs",
    "search_time",
    "num_searches",
)


def snapshot(env):
    # Missing attributes are distinct from attributes whose value is None.
    return {key: copy.deepcopy(getattr(env, key)) for key in STATE_FIELDS if hasattr(env, key)}


def restore(env, state):
    for key in STATE_FIELDS:
        if key in state:
            setattr(env, key, copy.deepcopy(state[key]))
        elif hasattr(env, key):
            delattr(env, key)
    return env


class Capture:
    def __init__(self, output, clock_start=None, phase="live"):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.blobs = self.output / "blobs"
        self.blobs.mkdir(exist_ok=True)
        self.clock_start = time.perf_counter() if clock_start is None else clock_start
        self.phase = phase
        self.nodes = []
        self.serial = 0
        self.overhead_s = 0.0
        write_json(
            self.output / "schema.json",
            {
                "version": VERSION,
                "phase": phase,
                "clock": "perf_counter seconds relative to events",
                "state_fields": list(STATE_FIELDS),
                "blob_format": "canonical JSON, SHA-256 filename",
                "timing": "Measured elapsed time includes capture interference; recorder CPU/I/O reported separately",
            },
        )

    def now(self):
        return time.perf_counter() - self.clock_start

    def blob(self, value):
        started = time.perf_counter()
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        digest = hashlib.sha256(data).hexdigest()
        path = self.blobs / (digest + ".json")
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Blob identity collision or corruption")
        else:
            with path.open("xb") as stream:
                stream.write(data)
        self.overhead_s += time.perf_counter() - started
        return digest

    def begin(self, kind, episode, step, branch, dependencies=(), inputs=None):
        ready = self.now()
        self.serial += 1
        node = {
            "version": VERSION,
            "id": f"{self.phase}:{self.serial}",
            "kind": kind,
            "episode": episode,
            "agent_id": episode,
            "step": step,
            "branch": branch,
            "phase": self.phase,
            "dependencies": [d for d in dependencies if d],
            "ready_s": ready,
            "input": self.blob(inputs),
            "status": "started",
        }
        node["start_s"] = self.now()
        append_json(self.output / "journal.jsonl", node)
        return node

    def finish(self, node, output=None, error=None, **fields):
        ended = self.now()
        node.update(
            end_s=ended,
            elapsed_s=ended - node["start_s"],
            queue_s=fields.pop("queue_s", 0.0),
            service_s=fields.pop("service_s", ended - node["start_s"]),
            output=self.blob(output),
            status="skipped"
            if fields.pop("skipped", False)
            else "failed"
            if error
            else "completed",
            error=error,
            **fields,
        )
        self.nodes.append(node)
        append_json(self.output / "nodes.jsonl", node)
        return node["id"]

    def instant(
        self, kind, episode, step, branch, dependencies=(), inputs=None, output=None, **fields
    ):
        node = self.begin(kind, episode, step, branch, dependencies, inputs)
        return self.finish(node, output, **fields)

    async def model(self, chat, prompt, role, episode, step, dependencies=()):
        node = self.begin(
            "model", episode, step, role, dependencies, {"prompt": prompt, "role": role}
        )
        node["attempt"] = 1 + sum(
            n["kind"] == "model"
            and n["episode"] == episode
            and n["step"] == step
            and n["branch"] == role
            for n in self.nodes
        )
        token = ACTIVE_CAPTURE.set((self, node))
        try:
            content = await chat.call(prompt, role, episode, step)
        except BaseException as exc:
            from .transport import OptionalExpired

            self.finish(node, error=type(exc).__name__, skipped=isinstance(exc, OptionalExpired))
            raise
        else:
            self.finish(
                node,
                {"content": content},
                service_s=node.get("transport_service_s", self.now() - node["start_s"]),
                queue_s=node.get("transport_queue_s", 0.0),
            )
            return content, node["id"]
        finally:
            ACTIVE_CAPTURE.reset(token)

    async def search(self, search, query, episode, step, speculative, dependencies=()):
        node = self.begin(
            "search",
            episode,
            step,
            "prefetch" if speculative else "required",
            dependencies,
            {"query": query, "speculative": speculative},
        )
        try:
            result = await search.search(query, episode, step, speculative)
        except BaseException as exc:
            self.finish(node, error=type(exc).__name__)
            raise
        else:
            self.finish(
                node,
                result,
                service_s=result.get("service_s", self.now() - node["start_s"]),
                queue_s=result.get("queue_s", 0.0),
            )
            return {**result, "capture_node": node["id"]}

    def seal(self):
        write_json(
            self.output / "manifest.json",
            {
                "version": VERSION,
                "phase": self.phase,
                "nodes": len(self.nodes),
                "recorder_blob_io_s": self.overhead_s,
                "files": {
                    str(p.relative_to(self.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(self.output.rglob("*"))
                    if p.is_file() and p.name != "manifest.json"
                },
            },
        )


class CaptureStore:
    """Read-only verified store. It has no HTTP client or missing-data fallback."""

    def __init__(self, root):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        if self.manifest["version"] != VERSION:
            raise ValueError("Unsupported capture version")
        for name, expected in self.manifest["files"].items():
            path = self.root / name
            if not path.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("Capture path escapes store")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Capture integrity failure: {name}")
        self.nodes = [
            json.loads(line) for line in (self.root / "nodes.jsonl").read_text().splitlines()
        ]
        self.by_id = {n["id"]: n for n in self.nodes}
        if len(self.by_id) != len(self.nodes) or len(self.nodes) != self.manifest["nodes"]:
            raise ValueError("Capture node inventory mismatch")

    def blob(self, identity):
        if (
            not isinstance(identity, str)
            or len(identity) != 64
            or any(c not in "0123456789abcdef" for c in identity)
        ):
            raise ValueError("Invalid blob identity")
        data = (self.root / "blobs" / (identity + ".json")).read_bytes()
        if hashlib.sha256(data).hexdigest() != identity:
            raise ValueError("Corrupt capture blob")
        return json.loads(data)
