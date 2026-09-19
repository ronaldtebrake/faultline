# Shared catalogs and native mapping

Use this workflow when the repository has `faultline.json`, or when setting up shared test descriptions for the TIA engine. For CodeGraph artifacts, selection, execution, and reports, follow [the graph workflow](graph-workflow.md). These commands make no Jev requests. Default discovery lists configured source files without invoking runners or application code. Only explicit `discover --native` / `select --native` enrichment and execution-time validation invoke runner bootstraps and data providers.

Run the installed `faultline` command or the equivalent `python3 "<this-skill>/scripts/run.py"`. Optional native discovery and execution-time validation currently check PHPUnit 9.6 and Behat 3.29. Other versions and frameworks can supply the generic inventory contract below. An unsupported version, empty native inventory, missing identity, or runner failure is retained as incomplete native evidence. It does not erase source targets or block source analysis. At execution, run fully and mark the assessment incomplete. Discovery never authorizes skipping tests.

## Configuration and descriptions

Commit `faultline.json` and `faultline/catalog/*.json`. Keep `.faultline/` ignored; it holds credentials and immutable native evidence. A minimal example:

```json
{
  "schema_version": 2,
  "repository": "example",
  "suites": [
    {
      "id": "unit",
      "runner": "phpunit",
      "command": ["vendor/bin/phpunit", "--testsuite", "unit"],
      "sources": ["tests/**/*.php"],
      "shared_inputs": ["composer.lock", "phpunit.xml"],
      "description_inputs": ["tests/bootstrap.php"],
      "variants": [{"id": "default", "args": []}]
    },
    {
      "id": "acceptance",
      "runner": "behat",
      "command": ["vendor/bin/behat", "--profile", "default"],
      "sources": ["features/**/*.feature"],
      "shared_inputs": ["behat.yml"],
      "description_inputs": ["features/bootstrap/**/*.php"]
    }
  ]
}
```

Commands are argument arrays, never shell fragments. They run relative to each suite's `cwd` (default `.`); source globs are always relative to the repository. Variant arguments extend the runner command. Declare every actual CI variant, including install/update profiles and tags. Configuration is reviewed executable input, like a test script.

During optional enrichment or execution validation, PHPUnit uses `--list-tests-xml` for native identities and Composer's `composer/class-map-generator` for class-to-source mapping. That library must be accessible through the suite's `autoload` file (default `vendor/autoload.php`, relative to `cwd`). Reuse it if already installed; otherwise add it as a development dependency or supply a generic inventory bridge. Faultline does not tokenize PHP or install dependencies automatically. Every file unit retains all discovered classes and datasets.

At the same boundary, Behat uses dry-run JUnit output for feature-file identities and scenario enumeration. Outline rows and identically named scenarios remain separate members of their feature unit. These enumeration IDs are not yet matched to scenario-line coverage IDs. HTTP application coverage must be collected in the process serving the application; CLI coverage alone does not establish that mapping.

For containers, `path_map` can translate output paths, for example `{"/app": "applications/service"}`. The native command must write to the supplied output path in the Faultline process's filesystem. A wrapper or generic bridge is needed when mounts differ; path mapping alone does not arrange mounts or services.

```bash
faultline discover
faultline catalog sync
faultline catalog show
```

`discover` lists files matching each suite's `sources` globs. These are provisional file targets, not a claim that every match is executable. It saves a sealed inventory under `.faultline/inventories/`. `catalog sync` creates deterministic, **unreviewed** drafts using source paths, preserves current reviewed records, and removes records absent from a complete source inventory. Empty configured source sets are reported as `no_configured_source_targets` and cannot replace a catalog. Migrate existing descriptions with `catalog sync --legacy .faultline/index.jsonl`; migrated descriptions still need review because execution-unit granularity may differ.

Read tests and required setup, then import only the changed descriptions:

```json
[
  {
    "id": "unit:default:tests/AccountTest.php",
    "description_hash": "copy the current hash from catalog show",
    "description": "Describes the behavior demonstrated by the test file.",
    "context_sources": ["tests/helpers/AccountFactory.php"]
  }
]
```

```bash
faultline catalog import --input reviewed.json --reviewer maintainer
faultline catalog check
```

Each catalog command enumerates source paths before modifying/checking records, without invoking runners. Import checks the provisional file identity and freshness, records the reviewer, and hashes declared context sources. It validates the record structure, not the truth of its prose. `catalog check` exits 2 when any record is missing, stale, unreviewed, or discovery is incomplete. CI should surface that condition and run fully, never generate descriptions automatically.

Production-only changes do not invalidate descriptions. Changes to the test file, `description_inputs`, or declared context sources do. Shared execution inputs are recorded separately. Commit descriptions with their tests; a second checkout can reuse them without agent indexing or Jev calls.

## Optional native enrichment and whole checks

`discover --native` or `select --native` adds runtime members to matching source targets. This can load application bootstrap code, so use it only in a prepared environment. Source targets remain present even if a runner excludes them or discovery fails. The inventory distinguishes source enumeration (`complete`) from runner evidence (`native_complete` and `native_evidence`). The default inventory has empty `members` arrays; agents must not invent them.

Source globs define the provisional scope and can include helpers or miss generated tests. `run --execute` resolves the requested suite's native inventory and compares file identities before executing. Differences force full execution and make the proposal unvalidated; reports cannot claim complete recall or savings from that case. Shadow mode only writes proposals. Explicit execution runs the full suite.

Represent static analysis, linting, or another indivisible command as a whole check:

```json
{
  "id": "static-analysis",
  "kind": "check",
  "runner": "generic",
  "command": ["vendor/bin/phpstan", "analyse"]
}
```

A whole check is always proposed in full and only executes with `run --execute`; it needs no source catalog or discovery command, and preserves its process exit status. `record` can report its receipt without per-test results. A failed check is an unclassified failure, not an automatically confirmed regression. Ordinary suites default to `kind: "tests"`.

## Import existing coverage

For PHPUnit 9.6, obtain native XML from the existing full-suite invocation by adding `--coverage-xml <directory>`, using Xdebug or PCOV and the project's normal coverage filter. Preserve the exact tested revision, variant, complete report directory, and collection context. Coverage adds overhead, so measure it separately and start with a bounded pilot.

```bash
faultline mapping import-phpunit \
  --input artifacts/coverage-xml \
  --source-prefix src \
  --revision <tested-revision> \
  --suite unit --variant default
```

`source-prefix` is the repository directory corresponding to the report's `<project source="…">`, **not necessarily the repository root**. The command resolves the supplied Git revision, imports native `<covered by="test-id">` relationships and line numbers, and saves an immutable JSON document under `.faultline/relationships/`. It records hashes of the imported reports. It does not run PHP from serialized coverage files. JUnit, Clover, and Cobertura summaries are insufficient for this importer because they do not provide its required test attribution.

The supplied revision and path prefix are workflow attestations; the report cannot independently prove them. Producer trust, age, and current-source validity must be checked before using a mapping in selection. A positive match can require execution. An absent edge never establishes irrelevance. Unknown native IDs remain unmatched; no fuzzy matching or negative selection is implemented. This importer does not convert a coverage percentage into a test-selection safety claim.

## Generic discovery contract

Use `runner: "generic"` and an optional `discovery_command` when native discovery is unsupported or a repository already has a suitable inventory tool. Keep `command` as the normal full-suite invocation. Without a discovery bridge, analysis still works from `sources`; execution runs fully and reports native validation as incomplete. Faultline never calls the generic full command to obtain a test listing. The bridge writes this JSON to stdout or to the path substituted for `{output}`:

```json
{
  "schema_version": 2,
  "complete": true,
  "units": [
    {
      "source": "tests/example.test",
      "members": ["native-case-id#dataset-1", "native-case-id#dataset-2"],
      "locator": {"file": "tests/example.test"},
      "title": "Native readable test labels"
    }
  ]
}
```

Use repository-relative source paths and exact native members, grouped by executable file unit. Do not invent identities with an agent. One invocation covers one suite variant. `{variant}` expands to its ID and an argument equal to `{variant_args}` expands to its configured arguments. Discovery checks local sources, duplicate identities, completeness, and hashes. A generic bridge attests completeness; Faultline cannot infer missing tests from code alone.

The configuration also reserves `scope`, `must_run`, `prerequisites`, `relationships`, `mode`, `irrelevant_threshold`, `selection_command`, evaluator budgets/pricing, and trusted-state age for subsequent engine stages. These fields do not currently enable execution or selection. Shadow mode only writes reports. Configuration alone cannot enable execution; `run --execute` is required.
