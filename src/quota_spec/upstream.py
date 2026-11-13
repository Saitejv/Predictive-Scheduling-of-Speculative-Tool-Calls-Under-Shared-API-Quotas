"""Pinned upstream source, workload order and isolated transport import adapter.

No experiment driver is imported here. Authors' prompts/parser/tools stay unchanged.
"""

import argparse
import hashlib
import importlib
import json
import os
import random
import sys
import types
from contextlib import contextmanager
from pathlib import Path

from .artifacts import write_json

REVISION = "dc938b9ef7474caf07fe4ad16549c1fa8c7d268c"
REPOSITORY = "https://github.com/naimengye/speculative-action"
FILES = (
    "LICENSE",
    "hotpotqa/README.md",
    "hotpotqa/src/__init__.py",
    "hotpotqa/src/constants.py",
    "hotpotqa/src/environment.py",
    "hotpotqa/src/llm_client.py",
    "hotpotqa/src/metrics.py",
    "hotpotqa/src/prompts.py",
    "hotpotqa/src/runner.py",
    "hotpotqa/src/utils.py",
    "hotpotqa/src/wrappers.py",
    "hotpotqa/prompts/prompts_naive.json",
    "hotpotqa/data/hotpot_dev_v1_simplified.json",
)


def paper_indices(count=20):
    if type(count) is not int or not 1 <= count <= 20:
        raise ValueError("Use 1..20 tasks from the upstream seeded task order")
    indices = list(range(7405))
    random.Random(248).shuffle(indices)
    return indices[:count]


def workload_indices(count=20, offset=0):
    """Extend the same seeded order without changing the 20-task reference API."""
    if (
        type(count) is not int
        or type(offset) is not int
        or count < 1
        or offset < 0
        or offset + count > 7405
    ):
        raise ValueError("Use a nonempty slice of the 7405-question seeded workload")
    indices = list(range(7405))
    random.Random(248).shuffle(indices)
    return indices[offset : offset + count]


def prepare(root):
    """Fetch immutable upstream files and verify their Git blob hashes."""
    import httpx

    root = root.resolve()
    manifest_path = root / "upstream.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["revision"] != REVISION or set(manifest["files"]) != set(FILES):
            raise ValueError("Upstream manifest identity mismatch")
        for path, identity in manifest["files"].items():
            if hashlib.sha256((root / path).read_bytes()).hexdigest() != identity["sha256"]:
                raise ValueError(f"Upstream source/data changed: {path}")
        return root
    manifest = {"repository": REPOSITORY, "revision": REVISION, "files": {}}
    with httpx.Client(timeout=60) as client:
        response = client.get(
            f"https://api.github.com/repos/naimengye/speculative-action/git/trees/{REVISION}?recursive=1"
        )
        response.raise_for_status()
        blobs = {item["path"]: item["sha"] for item in response.json()["tree"]}
        for path in FILES:
            response = client.get(
                f"https://raw.githubusercontent.com/naimengye/speculative-action/{REVISION}/{path}"
            )
            response.raise_for_status()
            data = response.content
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if blob != blobs[path]:
                raise ValueError(f"Git blob mismatch: {path}")
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest["files"][path] = {"git_blob": blob, "sha256": hashlib.sha256(data).hexdigest()}
    write_json(manifest_path, manifest)
    return root


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def load_upstream(root, client_class):
    """Use original source unchanged; replace only its LLM transport module."""
    name = "quota_spec_paper_upstream"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]
    package = types.ModuleType(name)
    package.__path__ = [str(root / "hotpotqa/src")]
    sys.modules[name] = package
    transport = types.ModuleType(name + ".llm_client")
    transport.LLMClient = client_class
    sys.modules[transport.__name__] = transport
    return importlib.import_module(name + ".runner")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("data/raw/speculative-action") / REVISION
    )
    args = parser.parse_args()
    print(json.dumps({"source": str(prepare(args.source)), "revision": REVISION}))


if __name__ == "__main__":
    main()
