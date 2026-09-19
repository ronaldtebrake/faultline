# Faultline

**Faultline is a test impact analysis experiment for CI and coding agents. It combines evidence from existing test tools with Jev's semantic relevance judgments to identify which tests a change may affect.**

The goal is to reduce CI work while preserving regression detection across languages, frameworks, and monorepos. Faultline starts with full-suite shadow runs so its proposed selections can be assessed before teams enable skipping.

## Why this exists

Large suites spend time testing behavior that a change may not affect. File paths, dependencies, and measured coverage provide useful evidence, but related behavior can cross those boundaries. Faultline investigates whether semantic judgments add useful information to those existing signals.

The objective needs measurement: semantic relevance, observed regression recall, and measured code coverage are different things. Faultline does not promise that semantic selection preserves all coverage or catches every regression.

## Shared understanding, native evidence

Test descriptions live with the code and are reviewed when tests change. A coding agent can help create or improve those descriptions; teammates and CI reuse them through Git. A production change can affect whether a test should run without requiring its description to be rewritten.

Existing runner tools establish executable identities and produce results or coverage. Narrow integrations translate those outputs into common contracts. Faultline keeps its decisions language agnostic while preserving each runner's datasets, scenarios, variants, and setup requirements.

## Jev's role

Jev receives selected change context and test evidence, then judges relevance on a fixed five-level scale. Faultline retains the probability distribution and calculates deterministic scores. Relevance is not a calibrated probability that a test will fail.

The intended selection policy combines those judgments with mandatory execution rules: changed tests, positive dependency/coverage matches, and uncertain evidence all require execution. Missing evidence must widen execution. Jev complements the evidence provided by test tools.

```mermaid
flowchart LR
    G["Git: change + shared catalog"] --> F["Faultline engine"]
    T["Native runner + coverage evidence"] --> F
    F <-->|"Bounded relevance judgments"| J["Jev"]
    F --> S["Frozen proposed selection"]
    S --> C["CI: full suite in shadow mode"]
    C --> R["Reports: recall, time, cost, misses"]
```

## How we'll assess it

Compare full execution, simple dependency/path and lexical baselines, Jev, and the combined policy on the same changes. Freeze decisions before inspecting outcomes. Report failing-change recall, failing-test recall, execution savings, and inference/audit overhead separately; report coverage only where it is measured.

Start with one ordinary PR/MR at a time. Preserve incomplete runs, flakes, infrastructure failures, missing artifacts, and unknown outcomes in the evidence. Repeated attempts do not count as independent regressions. A single green run cannot show that omitted tests were unnecessary.

## Install and use

Faultline ships as one self-contained Agent Skill with native Codex and Claude Code plugin packaging. Install with the [Skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add git@github.com:ronaldtebrake/faultline.git --skill faultline
```

Choose your agent when prompted. Python 3.10+ runs the bundled engine; no third-party Python packages are required. Native discovery also needs the configured test runners and their dependencies. The optional Python package exposes the same `faultline` command for local tooling and future CI use.

See the [setup guide](docs/install.md) for installation and [API-key configuration](docs/install.md#configure-the-jev-api-key). Selected change text and test descriptions are sent to Jev. Credentials, cached predictions, and reports stay in ignored `.faultline/`; reviewed shared descriptions live in `faultline/catalog/`.

## Status

Implemented: the original semantic ranking and historical reporting workflow, shared catalog commands, native PHPUnit/Behat discovery, and import of PHPUnit test-attributed XML coverage. The [shared-catalog guide](docs/tia.md) explains setup and migration.

The new selection/execution engine, trusted shared caches, and prospective CI reports are still being built. Current catalog commands do not skip tests. Offline tests and isolated native-tool fixtures validate the foundation; real-project usefulness and regression recall remain unproven. Remaining delivery work and acceptance criteria are in [PLAN.md](PLAN.md).
