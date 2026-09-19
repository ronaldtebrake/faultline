# CodeGraph and Jev shadow workflow

Faultline uses CodeGraph 1.6.0 for source parsing and relationships. The graph database is the primary source and test index. CodeGraph owns symbols/relationships; Faultline adds namespaced source/target records to the same SQLite database, then owns provenance, Jev evaluation, frozen decisions, execution validation, and reports. Shadow mode is report-only: it saves what Faultline would run or omit, without executing tests or changing CI. Full-suite execution is a separate explicit opt-in; selective execution is not enabled.

## Install and configure

Install the CodeGraph CLI using its [versioned release](https://github.com/colbymchenry/codegraph/releases/tag/v1.6.0), or its npm package:

```bash
npm install -g @colbymchenry/codegraph@1.6.0
```

Faultline does not need CodeGraph's agent installer or MCP server. It invokes the CLI in temporary source snapshots with telemetry disabled. A missing or incompatible executable produces a visible graph warning; Jev still scores source during selection. `graph build` reports the error directly.

Use the installed `faultline` executable or `python3 "<this-skill>/scripts/run.py"` for every command below. They share the same implementation. Source analysis requires Python 3.10+, Git, and CodeGraph. Configured runners and the application environment are required only for execution or explicit native enrichment. CI does not need a coding-agent session.

Create `faultline.json` with explicit test source patterns. Runner commands are optional for analysis; there is no separately maintained test catalog:

```json
{
  "schema_version": 2,
  "suites": [
    {"id": "unit", "sources": ["tests/**/*Test.php"]},
    {"id": "acceptance", "sources": ["features/**/*.feature"]},
    {"id": "browser", "sources": ["e2e/**/*.spec.ts"]},
    {"id": "javascript", "sources": ["test/**/*.test.js"]}
  ]
}
```

These are examples; use the repository's actual paths and conventions. The same engine reads every target as UTF-8 text. It does not infer an exhaustive executable test inventory from file extensions. Behat feature steps and examples reach Jev directly, including when CodeGraph has no Gherkin nodes. CodeGraph supplies structural context where supported. No framework parser or application bootstrap is added.

Test classification comes from the configured source patterns and is saved inside the graph artifact. This is a file-level target index, not a claim about exhaustive executable test cases. The default workflow never reads or creates `faultline/catalog/`. Empty suites remain visible and do not block other suites. The older catalog commands remain only for explicit legacy use.

`repository`, when supplied, must be the same stable identifier across checkouts. Otherwise Faultline derives a credential-free identity from the origin URL, or Git root commits for local repositories. Checkout directory names do not identify the repository. Relative input/output paths on the new commands resolve from the analyzed repository, including when using `--root` from an IDE. Suite paths are repository-relative except `command`, which runs in the configured suite `cwd`. Declare all suites, variants, shared setup, and relevant source scopes. Source inventories describe configured file targets and do not establish native test completeness. See the shared-catalog guide for `kind: "check"` commands that have no individual test inventory. Playwright and unsupported native versions can use the existing generic discovery/result contracts.

Graph budgets default to 300 seconds per producer invocation, 100,000 tracked files, 500 MB extracted source, 2,000,000 graph edges, traversal depth 16, 50,000 visited files, and six direct test-dependency context edges. The corresponding `graph` keys are `timeout_seconds`, `max_files`, `max_source_bytes`, `max_edges`, `max_depth`, `max_visited`, and `context_paths`. Source extraction and validation also consume time; the producer timeout is not a total end-to-end deadline. A traversal limit causes a visible graph warning without blocking source scoring. The context limit bounds prompt evidence, never the execution inventory.

The committed `codegraph.json`, when present, supplies upstream exclusions/settings. `graph.extensions` overrides its extension mappings. A changed upstream configuration forces a fresh graph rather than incrementally reusing incompatible parsing settings. Symlinks and submodule contents are recorded as unsupported; Faultline does not execute repository installation scripts while indexing.

After configuring suites, initialize a reusable graph with `faultline init --baseline <default-branch>`. Without configuration, `init` only prepares storage and explains the next step. Put `TYPESAFE_API_KEY` in the environment or `.faultline/.env` in the analyzed repository. The root `.env` is a final fallback. Do not read or display credentials. Graph building, discovery, dry runs, cached judgments, and reporting do not require a credential. Live requests send the selected diff, actual test source and graph evidence to Jev.

## Shared baselines and branches

```bash
# Configure faultline.json first. Use your actual default branch/ref.
faultline init --baseline main
# Inspect the returned artifact and its indexed targets.
faultline graph inspect .faultline/graphs/<hash>
faultline discover --revision main

# Export a baseline for your existing trusted artifact storage.
faultline graph export .faultline/graphs/<hash> --output /path/to/shared-baseline
# In another checkout of the same repository, with that revision fetched:
faultline graph import /path/to/shared-baseline
```

The database contains CodeGraph's `files`, `nodes`, and `edges`, plus `faultline_sources` (Git paths, blob identities, modes and sizes), `faultline_targets` (configured suite/variant targets), and `faultline_index` (snapshot metadata). Test source bytes are read from their exact Git blobs when needed; there is no second copy of every source file. A Gherkin target can exist in `faultline_targets` without any CodeGraph symbol nodes. `discover` queries the saved index without invoking the producer or native runners.

Artifacts are keyed by repository identity, exact Git revision, producer settings, and target configuration. Baseline and branch snapshots are immutable; Faultline copies a compatible database into a temporary snapshot and calls CodeGraph sync there. Added, renamed, and deleted target records are refreshed from the new Git revision. Concurrent publishers keep the first valid artifact instead of overwriting it. Exact cache hits and import/export require no CodeGraph process or Jev call.

When building a new revision, Faultline automatically chooses the nearest compatible indexed ancestor. `graph build --revision <ref> --reuse <artifact>` supplies an explicit seed. For PR analysis, `select --baseline <artifact>` supplies an optional indexing seed for the diff base. **A baseline never replaces the PR's actual diff base or head.** Branch names can move; stored snapshots always retain the resolved commit IDs. An upstream `codegraph.json` parsing/exclusion change forces fresh structural indexing.

Share complete artifact directories through existing CI storage or file transfer; no hosted cache service is required. Import verifies repository/settings, database integrity, revision availability, and source blob identities against local Git. Import only artifacts from trusted producers: hashes establish integrity, not authorship. PR jobs should not overwrite trusted published baselines. Reports, credentials, and Jev caches are not included in graph export.

If the graph is absent, incompatible, or damaged, analysis reports `index.basis: git_fallback` and still gives Jev the source targets. It does not silently publish that fallback as a structural baseline. `init`/`graph build` report producer failures directly; repair or rebuild the graph to restore primary-index operation.

## One PR/MR

Resolve the actual cumulative diff base and tested head using the repository's hosting tools. For stacked PRs, do not substitute the main branch. Analysis reads tracked files from the requested Git head without changing the checkout. Local configuration is allowed and its hash is recorded separately. Uncommitted source edits are not included. Do not create commits, reset files, or modify Git exclusion files to make analysis work. Ordinary generated outputs belong under `.faultline/` or other ignored paths.

```bash
faultline select --base <actual-diff-base-sha> --head HEAD \
  --id <pr-or-mr-id> --output .faultline/selection.json
```

Selection builds or reuses base/head graphs, queries targets from the head graph database and reads their exact Git blobs, sends every readable target to Jev, and freezes a report-only proposal. Missing graph paths, changed configuration files, and unsupported source languages do not prevent semantic scoring. Positive structural matches, changed tests, and explicit must-run/setup rules still require proposed execution regardless of Jev's score.

Whole source and diff inputs stay intact whenever they fit. Only oversized evidence is divided at UTF-8 boundaries. Small cohorts share each change window and finish before the next cohort; changed tests and positive graph matches are scheduled first, followed by smaller sources. Missing paths never exclude a target. Every source/diff fragment pair must have a valid judgment before a target can be proposed for omission, and every pair must meet `P(irrelevant) >= 0.95`. Reports show the strongest observed relevance score and the minimum fragment irrelevance probability, not an invented whole-test probability. Fragmentation can lose context; this remains an experimental proposal policy, not an execution safety guarantee.

Exact repeated evidence shares inference across variants only when execution arguments and context also match. Request identity includes model/evaluator versions, complete batch context, and hashes of full source and diff text. Defaults bound requests, elapsed inference time, payload bytes, test source bytes (`max_test_bytes`: 1,000,000), and submitted judgments per invocation (`max_evidence_pairs`: 10,000, including all questions in a retried partial batch). This ceiling no longer permanently truncates the plan: cached batches do not consume it. A separate 10,000-judgment planning guard on a single target produces a visible blocked-target error instead of spending on an unfinishable target. Missing credentials, oversized sources, invalid answers, or exhausted budgets leave affected targets visibly unscored/partial and proposed to run. Whole checks do not need Jev judgments. Cached judgments count as scoring even when no new API request is needed.

Prepare a cost/work estimate before live inference:

```bash
# Builds/reuses the exact graphs; no Jev calls or test execution.
faultline select --base <base> --head <head> --prepare --max-requests 10
# Same prepared inputs, with a hard cap including HTTP retries.
faultline select --base <base> --head <head> --max-requests 10
```

The estimate includes `uncached_requests`, `target_completion_ceiling`, `evidence_pairs`, and `pacing_floor_seconds`. The target ceiling assumes valid answers, no retries, and enough elapsed time; it is not a guarantee. A suite can legitimately require more than ten requests. The request and elapsed-time limits remain independent (`selection_seconds` defaults to 60; `--selection-seconds` explicitly overrides it for that invocation). CLI overrides do not edit `faultline.json`.

A partial run still writes its report and exits **2**. Read its fully scored/partial/unscored counts and `remaining_requests`. When another run is authorized, repeat the same base/head and input settings with a new output path (or omit `--output`); cached batches are skipped and the next batches are evaluated. Never loop to evade a user's total request limit. Repeated invocations retain the exact batch context; they do not repack only the uncached tests or change cached distributions.

`select --dry-run` estimates from existing graph artifacts only, without indexing or inference. If graphs are missing, that estimate describes the explicit Git fallback; use `--prepare` for an estimate using the final graph context. `--no-build` uses restored artifacts only. `--base-graph` and `--head-graph` validate their revisions, settings, and repository identity.

`select` automatically writes a Markdown and JSON report under `.faultline/reports/proposals/` and retains an immutable proposal under `.faultline/proposals/`. It does not require native test discovery or execution. Even with `--output`, a canonical selection is retained for later inspection.

```bash
# Regenerate one proposal without re-indexing, inference, or tests:
faultline shadow-report --selection .faultline/selection.json
# Track saved PR/MR snapshots without any runner or Jev calls:
faultline shadow-report
```

Reports list would-run/would-omit targets, graph/semantic reasons, scores, probabilities, prerequisites, full-suite fallbacks, and analysis cost. The summary uses the latest analysis for each repository/base/head/policy snapshot; repeated analysis does not inflate the snapshot count. Different revisions of one PR remain separate, related snapshots. Copy `.faultline/proposals/` and `.faultline/reports/` into your existing artifact retention if CI jobs are ephemeral. These records can contain private source identities and evidence; keep them in your project's trusted artifact storage.

Keep the existing CI test jobs unchanged. Proposed omission fractions describe file targets and whole checks; they do not measure saved execution time or regression recall. A fallback means the proposal would run fully if execution were enabled, not that Faultline starts tests now.

## Optional native enrichment and explicit execution

Native discovery is optional during analysis: add `--native` to `select` or `discover` only in a prepared runtime environment. Failures remain visible under `native_evidence` while source analysis continues. File targets are provisional; exact runtime members are collected at execution.

Only for an explicit request to execute tests, run the requested suite/variant against the frozen selection:

```bash
faultline run --execute --selection .faultline/selection.json --suite unit:default \
  --junit-output .faultline/phpunit.xml --output .faultline/unit-run.json
```

Without `--execute`, `run` only regenerates the proposal report and never invokes native discovery or runners. With `--execute`, the engine requires a clean checkout of the exact selected head and first revalidates the checkout, configuration, source inventory, and graph source inventory. It then invokes native discovery only for the requested suite/variant, after checking prerequisites, before running the normal full-suite command, and includes that inventory in the execution receipt. If discovery fails or native files differ from the proposal, it still runs the complete suite and records validation fallbacks. Such cases cannot claim a complete assessment. Whole checks skip test enumeration. It preserves the runner's exit code, streams its output to stderr, and writes an immutable execution receipt even when tests fail. The CLI's stdout remains JSON. PHPUnit JUnit capture uses a file; Behat capture uses a directory. Use fresh output paths for every attempt. An existing result path is refused so stale XML cannot be mistaken for the new run.

CI owns services, containers, matrix scheduling, and parallelism. For configured prerequisite suites, pass their successful receipts with repeated `--prerequisite <receipt.json>` arguments. Every prerequisite variant must have succeeded for the same selection. Configure result collection as an always-run CI step, so a failed test step still produces a report.

```bash
faultline record --selection .faultline/selection.json --run .faultline/unit-run.json
faultline execution-report
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

Every member uses the exact native identity saved in the execution receipt, including datasets and feature-outline enumeration. Reports join those members back to the frozen file proposal without rewriting it. Allowed statuses: `passed`, `failed`, `error`, `skipped`, `unknown`. Failure classifications: `confirmed_regression`, `flake`, `infrastructure`, `baseline`, `unknown`. A non-unknown classification requires evidence. Missing, unmatched, duplicate, and incomplete results cannot silently become passing tests. Raw execution outcomes are immutable. Repeated identical recording regenerates the report. Reviewed classifications/evidence can be revised with another `record` call without rerunning tests or Jev: the engine saves an immutable superseding observation and the aggregate uses the latest classification revision per execution.

Suite reports show conditional recall against observed confirmed regressions. Aggregate reports require complete observations for all configured suites and group retries into one change snapshot per compatible policy. Ordinary test-index evolution does not split policy groups; configuration/evaluator changes do. A green case cannot establish recall. Reports include denominators and descriptive Wilson intervals; related changes can still be statistically dependent.

Report-only shadow mode makes no execution savings claim. For an explicitly executed full-suite evaluation, actual test execution avoided is zero. Potential avoided time sums omitted members' durations under a serial-execution assumption and is unavailable for incomplete timing/results. Net estimates charge full selection and runner-validation overhead to the suite; they are not parallel CI wall-clock savings. Coverage, external agent cost, setup/job savings, and audit overhead remain unknown unless measured elsewhere. Frozen random, path, lexical, graph, and Jev baselines use the same proposed unit count; this is not an equal-runtime-budget comparison. Unscored units rank conservatively first in the Jev baseline, which is disclosed in the evidence.

## Sharing artifacts and controlling cost

Build a graph explicitly for inspection/publication:

```bash
faultline graph build --revision <sha> --output .faultline/exported-graph
faultline graph inspect .faultline/exported-graph
```

An artifact contains `manifest.json` and `graph.sqlite`. Copy the complete closed artifact through CI artifact storage. It records repository/revision, producer contract/version, settings, source hashes, indexed/unindexed files, database hash, and reuse provenance. `graph build --reuse <artifact>` updates a compatible graph in an isolated source snapshot. Existing matching artifacts are reused without needing the executable.

Restore `.faultline/graphs/` and the closed `.faultline/jev-cache.sqlite` database from trusted jobs for transparent reuse. Alternatively supply explicit graph paths. Publish immutable artifacts under revision/settings identities; do not commit changing binary databases to Git. Trusted jobs may publish reusable caches; PR jobs should have restore-only access to shared trusted caches and publish their own evidence separately. Faultline validates hashes and input identity; your artifact service authenticates producers. Integrity hashes are not signatures. Do not restore credential files with caches.

Batch cache keys include the full transmitted state and questions, graph context, model, endpoint, and evaluator version. PR IDs/timestamps are excluded from inference identity. Partial valid answers survive interruptions and independently invalid answers do not enter the cache. Shared batch context changes invalidate affected cached answers. Inputs exceeding configured payload bounds are rejected without truncating the diff.

`evaluator.max_batch_units` defaults to 50, `max_batch_bytes` to 48,000 and `max_state_bytes` to 24,000, and `jev_requests` to 100 HTTP attempts including retries. Lower request limits for a pilot. `selection_seconds` bounds the live inference phase separately from graph building. The transport preserves pacing, bounded 429/529 backoff, and no automatic retry after ambiguous network failures. The official [HTTP contract](https://docs.typesafe.ai/api) uses shared state and independently keyed questions; Faultline names each target test in its question instructions.

For an input-token cost estimate, configure `evaluator.pricing` with `as_of` and `input_usd_per_million`. Reports retain that dated rate. Missing usage, retries without token accounting, or absent pricing make the estimate unknown. No current price is embedded in the engine.

The default byte limits are conservative guards, not a tokenizer or a guarantee about quality. The pinned model's [documented context limits](https://docs.typesafe.ai/models) distinguish shared state plus the longest question from total request tokens. The [fan-out pattern](https://docs.typesafe.ai/patterns/fan-out) supports independent questions against shared state. Faultline retains serial pacing and reports actual provider usage; batching does not make arbitrary input sizes fit a small request cap.

TLS uses Python's verified default context, optionally supplemented by `certifi` when installed. Explicit `SSL_CERT_FILE`/`SSL_CERT_DIR` settings take precedence. Certificate errors are surfaced separately from authentication errors; the transport never disables verification or automatically retries an ambiguous inference request.
