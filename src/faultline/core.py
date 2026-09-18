"""Shared, provider-independent storage and validated configuration."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

SCHEMA = 1
DEFAULTS = {
    "feature_paths": ["**/*.feature"],
    "exclude_paths": ["**/vendor/**", "**/node_modules/**", ".git/**", ".faultline/**"],
    "exclude_tags": ["@disabled"],
    "profiles_file": None,
    "repository": None,
    "model": "jev-1.13.0",
    "github_requests": 100,
    "jev_requests": 100,
    "request_interval": 1.0,
    "retries": 2,
    "max_wait": 60,
    "max_artifact_bytes": 20_000_000,
    "max_state_bytes": 24_000,
    "artifact_patterns": ["*junit*", "*test-results*", "*test-reports*", "*behat*"],
    "path_prefixes": {},
    "test_aliases": {},
    "random_seed": 1729,
}


class FaultlineError(Exception):
    """An actionable, credential-free error suitable for terminal output."""


class Discovery(Protocol):
    def discover(self, root: Path, config: dict) -> list[dict]: ...


class Evaluator(Protocol):
    model: str
    def evaluate(self, context: dict, profile: dict) -> dict: ...


class HistorySource(Protocol):
    def collect(self, pr: int) -> dict: ...


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


def git(root: Path, *args: str, check=True) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise FaultlineError(f"Git could not {' '.join(args[:2])}; check the repository and available objects.")
    return result.stdout.strip() if result.returncode == 0 else ""


def repo_root(path: str | Path) -> Path:
    candidate = Path(path).resolve()
    result = git(candidate, "rev-parse", "--show-toplevel", check=False)
    return Path(result).resolve() if result else candidate


def positive_number(value, label, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise FaultlineError(f"{label} must be a finite number")
    if value < 0 or (not allow_zero and value == 0):
        raise FaultlineError(f"{label} must be {'nonnegative' if allow_zero else 'positive'}")
    return value


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
            raise FaultlineError("config.json must be an object containing only documented configuration keys")
        config.update(custom)
        for key in ("github_requests", "jev_requests", "request_interval", "retries", "max_wait",
                    "max_artifact_bytes", "max_state_bytes", "random_seed"):
            positive_number(config[key], key, allow_zero=key not in ("max_artifact_bytes", "max_state_bytes"))
            if key != "request_interval" and not isinstance(config[key], int):
                raise FaultlineError(f"{key} must be an integer")
        for key in ("feature_paths", "exclude_paths", "exclude_tags", "artifact_patterns"):
            if not isinstance(config[key], list) or not all(isinstance(s, str) for s in config[key]):
                raise FaultlineError(f"{key} must be a list of strings")
        for key in ("path_prefixes", "test_aliases"):
            if not isinstance(config[key], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in config[key].items()):
                raise FaultlineError(f"{key} must map strings to strings")
        for key in ("model", "repository", "profiles_file"):
            if not isinstance(config[key], str) and not (key != "model" and config[key] is None):
                raise FaultlineError(f"{key} must be a string")
        return config

    def index(self):
        index = read_json(self.path / "test-index.json")
        if not index or not index.get("tests"):
            raise FaultlineError("No test profiles. Run faultline index, or configure profiles_file.")
        return index

    def change_dir(self, repository: str, pr: int):
        return self.path / "changes" / (digest(repository)[:16] + f"-pr-{pr}")

    def change(self, repository: str, pr: int):
        data = read_json(self.change_dir(repository, pr) / "change.json")
        if data is None:
            raise FaultlineError(f"No cached PR #{pr}. Run faultline collect-history --pr {pr}.")
        return data
