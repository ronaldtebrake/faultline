"""Freeze predictions before outcome collection; all identities are content addressed."""
from __future__ import annotations

from pathlib import Path

from .core import SCHEMA, FaultlineError, digest, now, read_json, required_string, write_json, write_text
from .index import load_profiles, source_hash, context_sources
from .jev import JevEvaluator, evaluator_config, rank_snapshot
from .network import Budget


def load_change(path: Path):
    change = read_json(path)
    if not isinstance(change, dict):
        raise FaultlineError("Change input must be a JSON object")
    for key in ("repository", "id", "snapshot", "diff"):
        required_string(change, key)
    for key in ("title", "description"):
        if not isinstance(change.get(key, ""), str):
            raise FaultlineError(f"{key} must be a string")
    if not isinstance(change.get("changed_files"), list) or not all(isinstance(f, str) for f in change["changed_files"]):
        raise FaultlineError("changed_files must be an array of paths")
    provenance = change.get("provenance", {})
    if not isinstance(provenance, dict):
        raise FaultlineError("provenance must be an object")
    if provenance.get("historical") is True and provenance.get("outcomes_seen") is not False:
        raise FaultlineError("Historical ranking requires outcomes_seen: false. Use a fresh, outcome-blind context; do not relabel contaminated inputs.")
    if provenance.get("historical") is True and provenance.get("context_verified") is not True:
        raise FaultlineError("Historical ranking requires context_verified: true for the tested revision; do not substitute the final PR diff.")
    # Outcomes and unrelated fields cannot silently enter either Jev or the frozen change.
    clean = {key: change.get(key, "") for key in ("repository", "id", "snapshot", "title", "description", "diff", "changed_files")}
    clean["provenance"] = provenance
    return clean


def prediction_identity(change, profiles, config):
    return digest({"schema_version": SCHEMA, "change": change, "profiles": profiles,
                   "evaluator": evaluator_config(config)})


def load_prediction(path: Path):
    prediction = read_json(path)
    if not isinstance(prediction, dict) or prediction.get("schema_version") != SCHEMA:
        raise FaultlineError("Missing or unsupported prediction document")
    payload = {k: v for k, v in prediction.items() if k != "integrity"}
    if prediction.get("integrity") != digest(payload):
        raise FaultlineError("Prediction integrity mismatch; do not edit frozen predictions")
    return prediction


def prediction_path(store, identifier):
    path = Path(identifier)
    if path.is_file():
        return path.resolve()
    if len(identifier) == 64 and all(c in '0123456789abcdef' for c in identifier):
        return store.path / "predictions" / identifier / "prediction.json"
    raise FaultlineError("Supply a prediction file or its 64-character ID")


def ranking_markdown(prediction):
    from .report import md
    lines = [f"# Faultline ranking: {md(prediction['change']['id'])}", "",
             f"Snapshot: {md(prediction['change']['snapshot'])}", "",
             f"Status: {'complete' if prediction['complete'] else 'partial — not a complete-suite ranking'}",
             f"Model: {md(prediction['evaluator']['model'])}", "",
             "| Rank | Score | Test |", "| ---: | ---: | --- |"]
    lines += [f"| {i} | {row['score']:.4f} | {md(row['id'])} |" for i, row in enumerate(prediction['ranking'], 1)]
    if prediction['errors']:
        lines += ["", "## Incomplete work", "", *[f"- {md(e)}" for e in prediction['errors']]]
    lines += ["", "Scores measure semantic relevance, not calibrated failure probabilities.",
              "The catalog is agent-authored; inspect source hashes and provenance in the JSON."]
    return "\n".join(lines) + "\n"


def rank(store, change_path, tests_path=None, *, dry_run=False, evaluator=None, config=None):
    config = config or store.config()
    change = load_change(Path(change_path))
    profiles = load_profiles(Path(tests_path) if tests_path else store.path / "index.jsonl")
    if not profiles:
        raise FaultlineError("Test catalog is empty; index tests before ranking")
    stale = []
    for profile in profiles:
        if not profile.get("source_hash"):
            stale.append(profile["id"])
            continue
        try:
            if source_hash(store.root, profile['source'], context_sources(profile)) != profile['source_hash']:
                stale.append(profile['id'])
        except FaultlineError:
            stale.append(profile['id'])
    if stale:
        raise FaultlineError(f"{len(stale)} profiles have missing/stale source hashes; run index-status and update the catalog first.")
    profiles.sort(key=lambda p: p['id'])
    identifier = prediction_identity(change, profiles, config)
    output = store.path / 'predictions' / identifier / 'prediction.json'
    if output.exists():
        frozen = load_prediction(output)
        if frozen['complete']:
            return {"prediction_id": identifier, "path": str(output), "complete": True,
                    "cache_hits": len(profiles), "uncached_requests": 0, "frozen": True}
    budget = Budget(config['jev_requests'])
    evaluator = evaluator or JevEvaluator(store, config, budget)
    context = {**change, "id": digest(change)}
    estimate = rank_snapshot(store, change['repository'], context, profiles, config, evaluator, dry_run=True)
    estimate.update({"prediction_id": identifier, "request_ceiling": budget.limit, "source_bytes": len(change['diff'].encode()),
                     "over_ceiling": estimate['uncached_requests'] > budget.limit})
    if dry_run:
        return estimate
    store.initialize()
    if estimate['over_ceiling']:
        result = {"rows": [], "complete": False,
                  "errors": [f"{estimate['uncached_requests']} uncached judgments exceed the {budget.limit}-request ceiling. Review the dry run and configure an explicit ceiling; no Jev calls were made."]}
    else:
        result = rank_snapshot(store, change['repository'], context, profiles, config, evaluator)
    prediction = {"schema_version": SCHEMA, "prediction_id": identifier,
                  "created_at": now(), "change": change, "profiles": profiles,
                  "index_hash": digest(profiles), "evaluator": evaluator_config(config),
                  "ranking": result['rows'], "complete": result['complete'], "errors": result['errors'],
                  "requests_this_run": budget.used, "cache_hits": estimate['cache_hits'],
                  "limitations": ["Agent-authored catalog and change provenance are attestations, not independently verified facts.",
                                   "Current-index historical comparisons are exploratory and may contain suite drift."]}
    prediction['integrity'] = digest(prediction)
    # Completed predictions are never rewritten. Partial attempts remain inspectable.
    if output.exists():
        prior = load_prediction(output)
        write_json(output.parent / 'attempts' / (prior['integrity'] + '.json'), prior)
    write_json(output, prediction)
    write_text(output.parent / 'ranking.md', ranking_markdown(prediction))
    return {"prediction_id": identifier, "path": str(output), "report": str(output.parent / 'ranking.md'),
            "complete": prediction['complete'], "requests": budget.used, "cache_hits": estimate['cache_hits'],
            "errors": prediction['errors']}
