"""Small, dependency-free artifact helpers shared by baseline and extensions."""

import json
from pathlib import Path


def write_json(path, value):
    """Atomic checkpoint replacement; a killed process cannot truncate the prior file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def source_hashes():
    import hashlib

    root = Path(__file__).resolve().parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))}


def append_json(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(value) + "\n")
