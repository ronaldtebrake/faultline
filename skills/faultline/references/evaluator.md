# Fixed evaluator and change contract

The helper is `scripts/run.py`, relative to this skill. All input paths are explicit; `--root` selects where `.faultline/` is stored. Its package also installs an optional `faultline` executable.

## Change JSON

```json
{
  "repository": "host/owner/repository",
  "id": "PR-123",
  "snapshot": "exact-tested-revision",
  "title": "Intent known before test results",
  "description": "Description known before test results",
  "changed_files": ["src/authorization.php"],
  "diff": "diff --git ...",
  "provenance": {
    "historical": true,
    "outcomes_seen": false,
    "context_verified": true,
    "base_revision": "base-at-the-time",
    "head_revision": "head-at-the-time",
    "intent_source": "archived pre-run text; otherwise omitted",
    "index_revision": "current checkout: exploratory suite drift",
    "collected_at": "2026-01-01T12:00:00+00:00"
  }
}
```

Required: nonempty `repository`, `id`, `snapshot`, `diff`, and `changed_files` array. Title and description default to empty. Historical mode requires explicit `outcomes_seen: false` and `context_verified: true`. Preserve real revision identifiers; these are provenance, not separate user-facing changes. Include synthetic merge revisions when those were actually tested. If history cannot be reconstructed, do not substitute a final diff or claim a valid historical comparison.

The evaluator accepts only title, description, changed files, diff, and test identity/source/description as model state. Historical outcomes never belong in these fields. Other provenance stays local. All full input context and profiles are frozen with the prediction for inspection.

## Model and scoring

The initial model is pinned to `jev-1.13.0`. Faultline uses TypeSafe's Choice request with exactly five options, ordered `irrelevant`, `weak`, `plausible`, `strong`, `direct`. The fixed question and definitions live in `faultline/jev.py`, version `relevance-v1`.

The code checks a complete distribution, finite probabilities between zero and one, and a sum within 0.0001 of one. Expected relevance is `sum(probability × level)` for levels 0 through 4; ties use ascending test ID. Full probabilities, model identity, usage when returned, source/profile evidence, and configuration are retained. Relevance is not a calibrated probability of an actual failing test.

A prediction ID hashes the change, full catalog, and evaluator configuration. Pair cache keys additionally preserve profile identity and question/schema versions. Editing one test invalidates its pair predictions. Completed prediction files are never rewritten; incomplete attempts remain separate. The integrity hash detects accidental editing, not adversarial tampering or dishonest provenance.

The implementation uses the [official HTTP contract](https://docs.typesafe.ai/api) and [versioned model IDs](https://docs.typesafe.ai/models). Provider limits can change. There is no SDK with hidden retries or independent network client.

## Configuration and commands

`init` creates `.faultline/config.json` and an ignore-all `.faultline/.gitignore`. Default configuration:

```json
{
  "model": "jev-1.13.0",
  "jev_requests": 100,
  "request_interval": 1.0,
  "retries": 2,
  "max_wait": 60,
  "max_state_bytes": 24000,
  "random_seed": 1729
}
```

The byte limit is a conservative application bound, not a claimed model token limit. Oversized context is rejected without truncating diffs. The request ceiling counts retry attempts. If estimated uncached work exceeds it, no Jev requests start; review the estimate and explicitly configure an appropriate ceiling. `--max-requests N` overrides it for that invocation. Rate limits may still stop a job partway; rerunning reuses completed pair predictions.

```bash
python3 <helper> --root <repo> rank --change <change.json> --dry-run
python3 <helper> --root <repo> rank --change <change.json>
python3 <helper> --root <repo> explain-test '<test-id>'
```

`jev-evaluate` is an alias for `rank`. `--tests <catalog.jsonl>` selects another complete catalog; the default is `.faultline/index.jsonl`. Profiles must have current source hashes from the indexing helper. `score --input <probabilities.json>` computes the same score offline.

No API calls occur in dry runs or reports. A completed warm-cache rank also needs no API key. Exit codes: 0 success, 1 input/provider error, 2 partial ranking, 130 interrupted. The JSON result gives paths and actionable errors.

Output:

```text
.faultline/
  index.jsonl
  predictions/
    <pair-cache-key>.json
    <prediction-id>/
      prediction.json
      ranking.md
      attempts/<previous-partial-integrity>.json
  http/jev/cooldown.json
```

The API key is read from nonempty `TYPESAFE_API_KEY` in the environment, then `.faultline/.env`, then root `.env` of the analyzed repository. Files are read lazily for live requests; only that key is parsed, without interpolation or execution. The key is never logged or cached. Prefer `.faultline/.env` after initialization, which creates the local ignore rule. No live inference is needed to run the test suite.
