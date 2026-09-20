# Optional runner integration

Read this only for native discovery, explicit full-suite execution, or existing coverage imports. The [benchmark workflow](benchmark.md) needs none of these steps.

## Configure a runner

Add the actual full-suite command to the suite in `faultline.json`:

```json
{
  "id": "unit",
  "runner": "phpunit",
  "command": ["vendor/bin/phpunit", "--testsuite", "unit"],
  "sources": ["tests/**/*Test.php"],
  "shared_inputs": ["phpunit.xml"],
  "variants": [{"id": "default", "args": []}]
}
```

Commands are argument arrays, run relative to `cwd` (default `.`). Source patterns stay relative to the repository. Variant arguments extend the command. Declare prerequisites by suite ID; CI still owns services, containers, and scheduling.

- PHPUnit discovery uses `--list-tests-xml` and Composer’s `composer/class-map-generator` through `autoload` (default `vendor/autoload.php`, relative to `cwd`). Reuse an existing installation or use a generic bridge. File units retain every class and dataset.
- Behat discovery uses dry-run JUnit output. Features retain all scenario and outline members, including repeated names. This can load application bootstrap code.
- Other runners use `runner: "generic"` and an optional `discovery_command`. Without a bridge, source analysis works but native execution validation remains incomplete.

Container `path_map` entries translate returned paths, for example `{"/app": "services/api"}`. They do not create mounts. The runner must write artifacts where the Faultline process can read them.

## Prepare a receipt and execute

Only use native discovery or execution when requested, in a prepared application environment.

```bash
faultline discover --revision HEAD --native
faultline select --base <diff-base> --head HEAD --native
faultline run --selection <selection.json> --suite unit:default
# Explicit execution, when requested:
faultline run --selection <selection.json> --suite unit:default --execute
```

`select` produces a selection receipt; it does not accept the context bundles used by `benchmark`. `run` previews by default. With `--execute`, it validates the revision/configuration and runs the full suite, preserving exit status. Selective execution is unavailable. Native identity mismatches keep execution full and invalidate claims of a complete selection assessment.

Use `--prerequisite <successful-receipt.json>` for required suite receipts. `--junit-output` requests a fresh JUnit file for PHPUnit or directory for Behat. Import results with `record --selection <selection.json> --run <receipt.json> --input <results> --format json|junit`; `execution-report` aggregates saved outcomes. See each command’s `--help` for artifact paths.

A static analyzer or other indivisible command can use `kind: "check"`, `runner: "generic"`, and its full command. It remains required and executes only with `--execute`. A failed check is an unclassified failure until evidence establishes its cause.

## Generic discovery contract

The bridge writes JSON to stdout or the path substituted for `{output}`:

```json
{
  "schema_version": 2,
  "complete": true,
  "units": [{
    "source": "tests/example.test",
    "members": ["native-case#dataset-1", "native-case#dataset-2"],
    "locator": {"file": "tests/example.test"},
    "title": "Native test labels"
  }]
}
```

Use exact native identities grouped by file, with repository-relative paths. One invocation covers one variant: `{variant}` expands to its ID; an argument equal to `{variant_args}` expands to its configured arguments. Discovery checks paths, duplicates, and hashes. Declared completeness is producer evidence, not proof inferred from source. Agents must not invent members.

## Import existing coverage

`mapping import-phpunit` reads test-attributed PHPUnit XML coverage from an existing run. It does not run instrumentation or execute serialized PHP. JUnit, Clover, and Cobertura summaries lack the required attribution.

```bash
faultline mapping import-phpunit --input <coverage-directory> \
  --source-prefix src --revision <tested-revision> --suite unit --variant default
```

The prefix corresponds to the report’s source root, which may differ from the repository root. Preserve the complete report directory and exact tested revision. Coverage collection can add overhead; measure it separately.

The importer saves immutable relationships under `.faultline/relationships/`. Configure the suite’s `relationships` path to use them during selection. Revision, source identity, and native member matching limit reuse. Supplied revision and producer completeness remain attestations. Positive matches can require tests; absent or unmatched relationships never prove irrelevance. Behat scenario-line coverage is not mapped by this importer.
