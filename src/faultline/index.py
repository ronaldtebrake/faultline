"""Deterministic Gherkin extraction through the official parser and generic import."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from .core import SCHEMA, FaultlineError, Store, digest, now, read_json, write_json

EXTRACTOR_VERSION = "gherkin-pickles-v1"


def profile_validate(profile: dict):
    if not isinstance(profile, dict):
        raise FaultlineError("Each imported test profile must be an object")
    for key in ("id", "source", "description"):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise FaultlineError(f"Test profile needs a nonempty {key}")
    if not isinstance(profile.get("metadata", {}), dict):
        raise FaultlineError("Test metadata must be an object")
    profile.setdefault("metadata", {})
    profile.setdefault("source_hash", "sha256:" + digest(profile["description"]))
    profile["profile_hash"] = digest({k: v for k, v in profile.items() if k != "profile_hash"})
    return profile


class GherkinDiscovery:
    def discover(self, root: Path, config: dict) -> list[dict]:
        from gherkin.parser import Parser
        from gherkin.pickles.compiler import Compiler

        profiles = []
        paths = set()
        for pattern in config["feature_paths"]:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise FaultlineError("feature_paths must be relative patterns within the repository")
            paths.update(root.glob(pattern))
        for path in sorted(paths):
            if not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            source = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(source, pattern) for pattern in config["exclude_paths"]):
                continue
            text = path.read_text(encoding="utf-8-sig")
            try:
                document = Parser().parse(text)
                document["uri"] = source
                pickles = Compiler().compile(document)
            except Exception as exc:
                raise FaultlineError(f"Invalid Gherkin in {source}: {type(exc).__name__}") from exc
            feature = document.get("feature", {})
            nodes = {}
            def visit(value):
                if isinstance(value, dict):
                    if "id" in value and "location" in value:
                        nodes[value["id"]] = value
                    for child in value.values():
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)
            visit(feature)
            identities = {}
            for pickle in pickles:
                tags = [tag["name"] for tag in pickle.get("tags", [])]
                if set(tags) & set(config["exclude_tags"]):
                    continue
                names = [feature.get("name", ""), pickle["name"]]
                steps = []
                for item in pickle["steps"]:
                    step = item["text"]
                    if item.get("argument"):
                        step += " " + json.dumps(item["argument"], ensure_ascii=False, sort_keys=True)
                    steps.append(step)
                behavior = {"names": names, "steps": steps, "tags": tags}
                # Stable across unrelated line insertions; distinct outline examples
                # retain expanded names and step values in their identity.
                identity = digest({"name": pickle["name"], "steps": steps})[:16]
                occurrence = identities.get(identity, 0) + 1
                identities[identity] = occurrence
                ast_nodes = [nodes[node] for node in pickle["astNodeIds"] if node in nodes]
                lines = [node["location"]["line"] for node in ast_nodes]
                description = "\n".join(filter(None, [feature.get("name"), feature.get("description"),
                    *[node.get("description", "") for node in ast_nodes], pickle["name"], *steps, " ".join(tags)]))
                profiles.append(profile_validate({
                    "id": f"{source}::{identity}:{occurrence}", "source": source,
                    "description": description, "source_hash": "sha256:" + digest(behavior),
                    "metadata": {"name": pickle["name"], "feature": feature.get("name", ""),
                                 "lines": lines, "tags": tags, "extractor": EXTRACTOR_VERSION},
                }))
        return profiles


def build_index(store: Store, config: dict) -> dict:
    store.initialize()
    profiles = GherkinDiscovery().discover(store.root, config)
    if config["profiles_file"]:
        imported = read_json(store.root / config["profiles_file"])
        if isinstance(imported, dict):
            imported = imported.get("tests")
        if not isinstance(imported, list):
            raise FaultlineError("profiles_file must contain a JSON array or an object with tests")
        profiles.extend(profile_validate(dict(item)) for item in imported)
    ids = [p["id"] for p in profiles]
    if len(set(ids)) != len(ids):
        raise FaultlineError("Duplicate test IDs in the catalog")
    previous = read_json(store.path / "test-index.json", {"tests": []})
    old = {p["id"]: p for p in previous["tests"]}
    unchanged = sum(old.get(p["id"], {}).get("profile_hash") == p["profile_hash"] for p in profiles)
    profiles.sort(key=lambda p: p["id"])
    index = {"schema_version": SCHEMA, "created_at": now(), "tests": profiles,
             "hash": digest(profiles), "statistics": {"total": len(profiles), "unchanged": unchanged,
             "added": len(set(ids) - old.keys()), "removed": len(old.keys() - set(ids)),
             "changed": len(set(ids) & old.keys()) - unchanged}}
    write_json(store.path / "test-index.json", index)
    return index
