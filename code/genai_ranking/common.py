"""Small, dependency-free persistence helpers. Clinical artifacts stay on Vaipe."""
import hashlib
import json
import os
from pathlib import Path


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        f.write(dumps(value) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(dumps(row) + "\n")


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def code_hashes():
    return {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
