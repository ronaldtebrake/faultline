"""Validate and incrementally persist an agent-authored generic test catalog."""
from __future__ import annotations

import json
from pathlib import Path

from .core import VERSION, FaultlineError, digest, relative_source, required_string, write_text, reject_constant


def load_profiles(path: Path) -> list[dict]:
    try:
        text = path.read_text()
        if text.lstrip().startswith("["):
            profiles = json.loads(text, parse_constant=reject_constant)
        else:
            profiles = [json.loads(line, parse_constant=reject_constant) for line in text.splitlines() if line.strip()]
    except (ValueError, OSError):
        raise FaultlineError(f"Cannot read test catalog: {path}; expected JSONL or a JSON array") from None
    if not isinstance(profiles, list):
        raise FaultlineError("Expected a list of profiles")
    ids = set()
    for profile in profiles:
        for key in ("id", "source", "description"):
            required_string(profile, key)
        if profile["id"] in ids:
            raise FaultlineError(f"Duplicate test ID: {profile['id']}")
        ids.add(profile["id"])
        for key in ("metadata", "locator", "generated_by"):
            if key in profile and not isinstance(profile[key], dict):
                raise FaultlineError(f"{key} must be an object")
        if "source_hash" in profile and not isinstance(profile["source_hash"], str):
            raise FaultlineError("source_hash must be a string")
    return profiles


def source_hash(root: Path, source: str, context_sources=None):
    sources = [source, *(context_sources or [])]
    if not all(isinstance(p, str) for p in sources):
        raise FaultlineError("context_sources must be a list of source paths")
    hashed = []
    for item in sorted(set(sources)):
        path = relative_source(root, item)
        import hashlib
        hashed.append([item, hashlib.sha256(path.read_bytes()).hexdigest()])
    return "sha256:" + digest(hashed)


def context_sources(profile):
    paths = profile.get("context_sources", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise FaultlineError("context_sources must be an array of repository-relative paths")
    return paths


def profile_hash(profile):
    return digest(profile)


def index_status(store):
    path = store.path / "index.jsonl"
    if not path.exists():
        return {"tests": 0, "unchanged": [], "changed": [], "missing": []}
    result = {"tests": 0, "unchanged": [], "changed": [], "missing": []}
    for profile in load_profiles(path):
        result["tests"] += 1
        try:
            current = source_hash(store.root, profile["source"], context_sources(profile))
        except FaultlineError:
            result["missing"].append(profile["id"])
            continue
        bucket = "unchanged" if current == profile.get("source_hash") else "changed"
        result[bucket].append(profile["id"])
    return result


def build_index(store, input_path: Path, agent: str, rewrite=False):
    """Input is a complete discovered inventory; omission explicitly removes a test."""
    profiles = load_profiles(input_path)
    previous_path = store.path / "index.jsonl"
    old = {p["id"]: p for p in load_profiles(previous_path)} if previous_path.exists() else {}
    output, unchanged = [], 0
    for draft in profiles:
        current_hash = source_hash(store.root, draft["source"], context_sources(draft))
        if draft.get("source_hash") and draft["source_hash"] != current_hash:
            raise FaultlineError(f"Stale draft source_hash for {draft['id']}; inspect the changed source before regenerating.")
        previous = old.get(draft["id"])
        if previous and previous.get("source_hash") == current_hash and not rewrite:
            output.append(previous)
            unchanged += 1
        else:
            profile = {**draft, "source_hash": current_hash,
                       "generated_by": {"faultline_skill_version": VERSION, "agent": agent}}
            output.append(profile)
    output.sort(key=lambda p: p["id"])
    store.initialize()
    write_text(previous_path, "".join(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n" for p in output))
    ids = {p["id"] for p in output}
    return {"total": len(output), "unchanged": unchanged, "added": len(ids - old.keys()),
            "removed": len(old.keys() - ids), "changed": len(ids & old.keys()) - unchanged,
            "index_hash": digest(output), "path": str(previous_path)}
