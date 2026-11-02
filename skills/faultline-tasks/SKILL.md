---
name: faultline-tasks
description: Configure and maintain Faultline task inputs, dependencies and CI result caching across products. Use when setting up task-based CI reuse or when changes to files, shared dependencies, commands, fixtures or runtimes require updating faultline.json. Does not infer individual scenario coverage or require framework adapters.
---

# Faultline task dependencies

Produce a reviewable input contract for existing CI tasks. Keep commands, task
boundaries and required checks consistent with existing CI. Read
[the contract and integration guide](references/task-contract.md) before editing
configuration; check that the installed CLI supports `tasks plan`. This skill
uses the separately installed Faultline package, not a vendored engine.

## Establish the contract

Inspect repository instructions, existing `faultline.json`, CI workflows,
package/workspace manifests, lockfiles and the commands' actual configuration.
Trace scripts called by CI, working directories, generated inputs, fixtures,
container build contexts and external services. CI `needs` often describes
scheduling; it is not evidence of complete application dependencies.

For each task, identify its full command, input boundaries, transitive component
dependencies, runtime/fixture identity and evidence supporting those choices.
Use commandless input nodes for shared components. Prefer existing package
boundaries and broad directory inputs. If a task can use an entire application,
include the entire application. Do not invent a smaller boundary to improve the
cache-hit count. A filename, test title, import search, passing run or absence of
a graph edge cannot establish independence.

Use one `task_graph` block in `faultline.json`; preserve existing suite and
evaluator settings. The task model is framework-independent. No application
adapter, server instrumentation or inference service is required.

## Maintain it during changes

- Files added inside an existing input pattern need no special listing. Check
  that the resulting plan includes them and affected dependents change.
- New components or cross-component use require ownership inputs and explicit
  `depends_on` links. Manifests/imports reveal candidates; inspect indirect
  runtime/configuration dependencies before accepting a boundary.
- Changes to commands, setup, lockfiles, runtime images, fixture generation or
  environment inputs require corresponding contract updates.
- Unmapped tracked files are global inputs by default. Use `ignored_inputs` only
  with concrete evidence that no configured check consumes those files. It cannot
  subtract files from another task's declared inputs.
- Keep output-producing tasks and checks with mutable/unversioned external state
  uncached. A successful exit code does not restore build artifacts or recreate
  service/database state. An uncached executable dependency also makes its
  dependents uncacheable.

## Validate and integrate

Commit only authorized configuration changes before planning: `tasks plan` reads
Git snapshots, not working-tree drafts. Resolve the cumulative merge base and,
for stacked work, inspect the parent comparison separately. Examine changed
inputs, changed dependencies, unmapped files and cache-disabled reasons.

Exercise representative changes in a disposable local fixture or authorized
throwaway branch: own input, transitive shared input, new/deleted file, unknown
root configuration and an independently owned component. Check fingerprints and
reasons. Do not run expensive product tests merely to validate configuration.

When execution is authorized, use `tasks run` or `actions/tasks` in `shadow` mode
around the existing full command. Verify a cold run, a later cache restore, and
another full run that reports the match. Preserve failures and contradictions.
Cache matching measures reuse under the contract; it does not prove every
dependency is declared.

Keep full CI during validation unless the user authorized adopting reuse.
`--reuse` / action `mode: reuse` is the explicit execution change. Do not ask again
when adoption is already authorized. Keep Jev configuration unchanged; task
commands never call it.

Return changes with their evidence, commands checked, actual cache results and
remaining unknowns. Distinguish task-result reuse from parser reuse. Do not
promise perfect selection or convert summed durations into CI wall-clock savings.
Leave a concise project instruction to use this skill for future dependency
changes when maintaining project instructions is in scope.
