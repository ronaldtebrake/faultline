# Source workflow

The Python engine reads tracked text from exact Git revisions. `faultline.json` describes where tests live; there is no separately built index or generated description catalog in this flow. Configuration can be shared through Git, and any checkout with the same objects can analyze a branch or historical PR without switching branches.

## Configure suites

```json
{
  "schema_version": 2,
  "scope": ["src/**", "config/**"],
  "suites": [{
    "id": "unit",
    "sources": ["tests/**/*Test.php"],
    "shared_inputs": ["phpunit.xml"],
    "description_inputs": ["tests/bootstrap.php"],
    "must_run": ["tests/SmokeTest.php"],
    "variants": [{"id": "default", "args": []}]
  }]
}
```

Use real repository-relative patterns. Source globs support `**` for nested directories. Targets have stable `suite:variant:source` identities and preserve the whole file’s datasets or scenarios. They are provisional file targets, not invented runtime selectors.

- `scope`: production/configuration paths belonging to the analysis. Unknown changes retain full suites; do not broaden scope just to hide uncertainty.
- `shared_inputs`: changes here require full suite execution, such as runner configuration or shared setup.
- `description_inputs`: existing contextual source files. A change here retains that suite’s tests. Adaptive/source mode records their identities without sending external bodies; `whole` mode supplies the bodies.
- `must_run`: source/identity patterns that remain required regardless of scores.
- `prerequisites`: other suite IDs required when this suite proposes work. The engine expands them transitively.
- `kind: "check"`: a whole check with no per-test inventory; it remains required.
- `irrelevant_threshold`: saved omission cutoff, default `0.95` (allowed `0.95`–`1`). Offline alternative policies do not edit it.

Runner names and commands are optional for source analysis. PHPUnit and Behat have native integrations for explicitly requested execution; other suites can use the generic discovery/results contract. Local configuration is hashed into evidence and identified as local, even when analyzing an older Git revision.

## Inspect and analyze

```bash
faultline init --revision HEAD
faultline discover --revision <tested-head>
faultline benchmark --base <cumulative-base> --head <tested-head> --prepare
```

Discovery only enumerates configured files. It cannot prove that configuration covers every executable test. An empty suite remains incomplete. For new analyses use [benchmark](benchmark.md), which supports adaptive windows and recovery. `select --base … --head …` remains the selection-receipt workflow used by explicit full-suite evaluations; `--prepare` and `--dry-run` estimate it offline.

For source context beyond the diff and test, the agent follows [context gathering](context.md) and supplies `benchmark --context <bundle>`. This works for ordinary edits and dependency updates. The CLI verifies and scores the supplied evidence; it does not investigate integration paths automatically.

Descriptions are not generated. The same source flow handles Gherkin and other UTF-8 text without framework parsers. Missing, binary, empty, or oversized source stays unresolved rather than being omitted.

## Storage and budgets

Committed configuration is shared; credentials, predictions, reports, and `jev-cache.sqlite` stay in ignored `.faultline/`. Only exact inference inputs can reuse an answer. PR numbers and timestamps do not change an inference identity. Complete batch context, model, evaluator, source, and diff do.

Preparation makes no Jev calls. Live runs have one request ceiling (including retries), a deadline, byte guards, and a judgment limit. Inspect readiness and eligible targets before scoring. A partial run saves evidence and exits 2. Resuming uses remaining authorization, not a silently renewed budget.

## Optional native validation and execution

Native discovery may require a working application; use `discover --native` or `select --native` only when explicitly requested in a prepared environment. It enriches file identities and never removes source candidates on failure.

```bash
faultline run --selection <selection.json> --suite <suite:variant>
```

This only previews a proposal. When the user asks to execute tests, add `--execute`; the current engine validates exact revisions/configuration and executes the **full suite**, preserving exit status. Selective execution is unavailable. Configure runner commands and explicit prerequisites before execution. `record` imports the associated results; `execution-report` aggregates them. Existing CI remains responsible for services, containers, isolation, and scheduling.

See [runner integration](execution.md) for native discovery, full-suite execution, and existing coverage imports.
