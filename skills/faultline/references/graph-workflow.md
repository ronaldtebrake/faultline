# CodeGraph and Jev shadow workflow

Faultline uses CodeGraph 1.6.0 for source parsing and relationships. Python owns native test identities, provenance, Jev evaluation, frozen decisions, execution validation, and reports. Only full-suite shadow execution is enabled: proposed omissions are measured, never applied to the runner command.

## Install and configure

Install the CodeGraph CLI using its [versioned release](https://github.com/colbymchenry/codegraph/releases/tag/v1.6.0), or its npm package:

```bash
npm install -g @colbymchenry/codegraph@1.6.0
```

Faultline does not need CodeGraph's agent installer or MCP server. It invokes the CLI in temporary source snapshots with telemetry disabled. A missing or incompatible executable produces a full-execution fallback during selection. `graph build` reports the error directly.

Use the installed `faultline` executable or `python3 "<this-skill>/scripts/run.py"` for every command below. They share the same implementation. Python 3.10+, Git, CodeGraph, and the configured native runners are required. CI does not need a coding-agent session.

Create and commit `faultline.json`; discover/review descriptions as described in [shared catalogs](shared-catalog.md). For example:

```json
{
  "schema_version": 2,
  "repository": "my-monorepo",
  "graph": {
    "command": ["codegraph"],
    "version": "1.6.0",
    "extensions": {".module": "php", ".inc": "php", ".install": "php"}
  },
  "evaluator": {"jev_requests": 10, "selection_seconds": 60},
  "suites": [
    {
      "id": "unit",
      "runner": "phpunit",
      "command": ["vendor/bin/phpunit", "--testsuite", "unit"],
      "sources": ["tests/**/*.php"],
      "scope": ["src/**"],
      "shared_inputs": ["composer.json", "composer.lock", "phpunit.xml"],
      "description_inputs": ["tests/bootstrap.php"]
    }
  ]
}
```

`repository` is a stable identifier shared across checkouts. Relative input/output paths on the new commands resolve from the analyzed repository, including when using `--root` from an IDE. Suite paths are repository-relative except `command`, which runs in the configured suite `cwd`. Declare all suites, variants, shared setup, and relevant source scopes. Incomplete inventories never establish that a suite has no tests. Playwright and unsupported native versions can use the existing generic discovery/result contracts.

Graph budgets default to 300 seconds per producer invocation, 100,000 tracked files, 500 MB extracted source, 2,000,000 graph edges, traversal depth 16, 50,000 visited files, and six direct test-dependency context edges. The corresponding `graph` keys are `timeout_seconds`, `max_files`, `max_source_bytes`, `max_edges`, `max_depth`, `max_visited`, and `context_paths`. Source extraction and validation also consume time; the producer timeout is not a total end-to-end deadline. A traversal limit causes a visible full fallback. The context limit bounds prompt evidence, never the execution inventory.

The committed `codegraph.json`, when present, supplies upstream exclusions/settings. `graph.extensions` overrides its extension mappings. A changed upstream configuration forces a fresh graph rather than incrementally reusing incompatible parsing settings. Symlinks and submodule contents are recorded as unsupported; Faultline does not execute repository installation scripts while indexing.

Initialize ignored local storage with `faultline init`. Put `TYPESAFE_API_KEY` in the environment or `.faultline/.env` in the analyzed repository. The root `.env` is a final fallback. Do not read or display credentials. Graph building, discovery, dry runs, cached judgments, and reporting do not require a credential. Live requests send the selected diff, descriptions, and graph evidence to Jev.

## One PR/MR

Resolve the actual cumulative diff base and tested head using the repository's hosting tools. For stacked PRs, do not substitute the main branch. Check out the tested revision and commit the reviewed catalog before selection. Ordinary generated outputs belong under `.faultline/` or other ignored paths.

```bash
faultline select --base <actual-diff-base-sha> --head HEAD \
  --id <pr-or-mr-id> --output .faultline/selection.json
```

Selection automatically builds missing base/head graphs, reuses a compatible base graph for the head, performs native discovery, checks descriptions, obtains cached or new Jev judgments, and freezes the decision. Positive graph paths, changed tests, must-run rules, positive imported coverage, and uncertainty require proposed execution. Remaining units can be proposed for omission only with a current description, indexed test source, usable evidence, and `P(irrelevant) >= 0.95`.

Jev also scores eligible positive graph matches for inspection, but its answer cannot override mandatory execution. Unknown change scope, graph gaps in changed files, exhausted traversal budgets, incomplete inventories, stale checkout state, or incomplete semantic evaluation produce full proposals. Missing paths are not proof of irrelevance. Graphs currently traverse reverse file dependencies, retaining the producer's symbol names and resolver metadata along each path.

Use `select --dry-run` to inspect restored graph evidence and estimate uncached batches without indexing or contacting Jev. Use `--no-build` to require restored graph artifacts; missing artifacts cause fallbacks. `--base-graph` and `--head-graph` accept explicit artifact directories and validate their revisions, settings, and repository identity.

Run each suite/variant against the frozen selection:

```bash
faultline run --selection .faultline/selection.json --suite unit:default \
  --junit-output .faultline/phpunit.xml --output .faultline/unit-run.json
```

The engine revalidates the checkout, configuration, catalog, and native inventory before starting the normal full-suite command. It preserves the runner's exit code, streams its output to stderr, and writes an immutable execution receipt even when tests fail. The CLI's stdout remains JSON. PHPUnit JUnit capture uses a file; Behat capture uses a directory. Use fresh output paths for every attempt. An existing result path is refused so stale XML cannot be mistaken for the new run.

CI owns services, containers, matrix scheduling, and parallelism. For configured prerequisite suites, pass their successful receipts with repeated `--prerequisite <receipt.json>` arguments. Every prerequisite variant must have succeeded for the same selection. Configure result collection as an always-run CI step, so a failed test step still produces a report.

```bash
faultline record --selection .faultline/selection.json --run .faultline/unit-run.json
faultline shadow-report
```

`record` automatically imports captured JUnit and saves both JSON and Markdown findings. JUnit failures are initially **unknown**, not automatically regressions. For evidence-based classifications or generic runners, supply `--format json --input <file>` before freezing the observation:

```json
{
  "selection_id": "integrity value from selection.json",
  "suite_key": "unit:default",
  "complete": true,
  "tests": [
    {
      "id": "unit:default:tests/ExampleTest.php",
      "member": "ExampleTest::testBehavior",
      "status": "failed",
      "duration_seconds": 1.2,
      "classification": "confirmed_regression",
      "evidence": "Reference to reproduction or reviewed failure evidence"
    }
  ]
}
```

Every member uses the exact discovered native identity, including datasets and feature-outline enumeration. Allowed statuses: `passed`, `failed`, `error`, `skipped`, `unknown`. Failure classifications: `confirmed_regression`, `flake`, `infrastructure`, `baseline`, `unknown`. A non-unknown classification requires evidence. Missing, unmatched, duplicate, and incomplete results cannot silently become passing tests. Raw execution outcomes are immutable. Repeated identical recording regenerates the report. Reviewed classifications/evidence can be revised with another `record` call without rerunning tests or Jev: the engine saves an immutable superseding observation and the aggregate uses the latest classification revision per execution.

Suite reports show conditional recall against observed confirmed regressions. Aggregate reports require complete observations for all configured suites and group retries into one change snapshot per compatible policy. Ordinary catalog evolution does not split policy groups; configuration/evaluator changes do. A green case cannot establish recall. Reports include denominators and descriptive Wilson intervals; related changes can still be statistically dependent.

Actual test execution saved in shadow mode is zero. Potential avoided time sums omitted members' durations under a serial-execution assumption and is unavailable for incomplete timing/results. Net estimates charge full selection overhead to the suite; they are not parallel CI wall-clock savings. Coverage, external agent cost, setup/job savings, and audit overhead remain unknown unless measured elsewhere. Frozen random, path, lexical, graph, and Jev baselines use the same proposed unit count; this is not an equal-runtime-budget comparison. Unscored units rank conservatively first in the Jev baseline, which is disclosed in the evidence.

## Sharing artifacts and controlling cost

Build a graph explicitly for inspection/publication:

```bash
faultline graph build --revision <sha> --output .faultline/exported-graph
faultline graph inspect .faultline/exported-graph
```

An artifact contains `manifest.json` and `graph.sqlite`. Copy the complete closed artifact through CI artifact storage. It records repository/revision, producer contract/version, settings, source hashes, indexed/unindexed files, database hash, and reuse provenance. `graph build --reuse <artifact>` updates a compatible graph in an isolated source snapshot. Existing matching artifacts are reused without needing the executable.

Restore `.faultline/graphs/` and `.faultline/batch-cache/` from trusted jobs for transparent reuse. Alternatively supply explicit graph paths. Publish immutable artifacts under revision/settings identities; do not commit changing binary databases to Git. Trusted jobs may publish reusable caches; PR jobs should have restore-only access to shared trusted caches and publish their own evidence separately. Faultline validates hashes and input identity; your artifact service authenticates producers. Integrity hashes are not signatures. Do not restore credential files with caches.

Batch cache keys include the full transmitted state and questions, graph context, model, endpoint, and evaluator version. PR IDs/timestamps are excluded from inference identity. Partial valid answers survive interruptions and independently invalid answers do not enter the cache. Shared batch context changes invalidate affected cached answers. Inputs exceeding configured payload bounds are rejected without truncating the diff.

`evaluator.max_batch_units` defaults to 50, `max_batch_bytes` and `max_state_bytes` to 24,000, and `jev_requests` to 100 HTTP attempts including retries. Lower request limits for a pilot. `selection_seconds` bounds the live inference phase separately from graph building. The transport preserves pacing, bounded 429/529 backoff, and no automatic retry after ambiguous network failures. The official [HTTP contract](https://docs.typesafe.ai/api) uses shared state and independently keyed questions; Faultline names each target test in its question instructions.

For an input-token cost estimate, configure `evaluator.pricing` with `as_of` and `input_usd_per_million`. Reports retain that dated rate. Missing usage, retries without token accounting, or absent pricing make the estimate unknown. No current price is embedded in the engine.
