"""Language-independent storage, hashes, and configuration."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
SCHEMA = 1
DEFAULTS = {"model": "jev-1.13.0", "jev_requests": 100, "request_interval": 1.0,
            "retries": 2, "max_wait": 60, "max_state_bytes": 24_000, "random_seed": 1729}


class FaultlineError(Exception):
    """An actionable, credential-free error suitable for terminal output."""


def digest(value) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise FaultlineError(f"Cannot read JSON: {path}") from exc


def write_json(path: Path, value):
    write_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def repo_root(path: str | Path) -> Path:
    candidate = Path(path).resolve()
    try:
        result = subprocess.run(["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True)
    except FileNotFoundError:
        return candidate
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else candidate


def number(value, label, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise FaultlineError(f"{label} must be a finite number")
    if value < 0 or (not allow_zero and value == 0):
        raise FaultlineError(f"{label} must be {'nonnegative' if allow_zero else 'positive'}")
    return value


def required_string(obj, key):
    if not isinstance(obj, dict) or not isinstance(obj.get(key), str) or not obj[key].strip():
        raise FaultlineError(f"Expected a nonempty string: {key}")
    return obj[key]


def relative_source(root, source):
    path = Path(source)
    if path.is_absolute() or ".." in path.parts or not (root / path).resolve().is_relative_to(root):
        raise FaultlineError(f"Source must be inside the repository: {source}")
    if not (root / path).is_file():
        raise FaultlineError(f"Source file missing: {source}")
    return root / path


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / ".faultline"

    def initialize(self):
        self.path.mkdir(parents=True, exist_ok=True)
        write_text(self.path / ".gitignore", "*\n")

    def config(self) -> dict:
        config = dict(DEFAULTS)
        custom = read_json(self.path / "config.json", {})
        if not isinstance(custom, dict) or set(custom) - set(DEFAULTS):
            raise FaultlineError("config.json must contain only documented configuration keys")
        config.update(custom)
        for key in set(DEFAULTS) - {"model"}:
            number(config[key], key, allow_zero=key != "max_state_bytes")
            if key != "request_interval" and not isinstance(config[key], int):
                raise FaultlineError(f"{key} must be an integer")
        required_string(config, "model")
        if config["model"] in ("jev-latest", "jev-preview"):
            raise FaultlineError("Pin a versioned Jev model for reproducible caches.")
        return config
