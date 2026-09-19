# Faultline

**Faultline is a test impact analysis experiment for CI and coding agents. It combines CodeGraph's structural relationships with Jev's semantic relevance judgments to identify which tests a change may affect.**

The goal is to reduce CI work while preserving regression detection across languages, frameworks, and monorepos. Faultline starts in report-only shadow mode: it records which tests it would run while teams keep their existing CI unchanged.

## Why this exists

Large suites spend time testing behavior that a change may not affect. File paths, dependencies, and measured coverage provide useful evidence, but related behavior can cross those boundaries. Faultline investigates whether semantic judgments add useful information to those existing signals.

The objective needs measurement: semantic relevance, observed regression recall, and measured code coverage are different things. Faultline does not promise that semantic selection preserves all coverage or catches every regression.

## One shared index

Faultline initializes a CodeGraph database for a Git revision, including production code and test sources. CodeGraph supplies symbols and relationships; Faultline stores configured test-file targets in the same database, including files such as Gherkin features that have no structural nodes. There is no separate test catalog to maintain.

Teammates and CI can share immutable baseline artifacts. Each branch reuses compatible indexing work and derives exact base/head snapshots without modifying the baseline. Jev reads test source directly from the indexed Git blobs. Framework-specific runners are only needed for explicit native discovery or execution.

## Jev's role

Jev receives bounded change context, test source and graph evidence, then judges relevance on a fixed five-level scale. Faultline retains the probability distribution and calculates deterministic scores. Relevance is not a calibrated probability that a test will fail.

The intended selection policy combines those judgments with mandatory execution rules: changed tests, positive dependency/coverage matches, and uncertain evidence all require execution. Missing evidence must widen execution. Jev complements the evidence provided by test tools.

```mermaid
flowchart LR
    B["Initialize/shared baseline: code + test index"] --> CGraph["CodeGraph: immutable branch snapshots"]
    G["Git: exact PR base + head"] --> CGraph
    CGraph --> F["Indexed tests + diff + dependency paths"]
    F <-->|"Bounded relevance judgments"| J["Jev"]
    F --> S["Frozen proposed selection"]
    S --> R["Shadow report: would run / would omit, reasons, cost"]
    R --> H["Track PR snapshots; existing CI unchanged"]
```

## How we'll assess it

Compare full execution, simple dependency/path and lexical baselines, Jev, and the combined policy on the same changes. Freeze decisions before inspecting outcomes. Report failing-change recall, failing-test recall, execution savings, and inference/audit overhead separately; report coverage only where it is measured.

Start with one ordinary PR/MR at a time. Preserve incomplete runs, flakes, infrastructure failures, missing artifacts, and unknown outcomes in the evidence. Repeated attempts do not count as independent regressions. A single green run cannot show that omitted tests were unnecessary.

## Install and use

Faultline ships as one self-contained Agent Skill with native Codex and Claude Code plugin packaging. Install with the [Skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add git@github.com:ronaldtebrake/faultline.git --skill faultline
```

Choose your agent when prompted. Python 3.10+ runs the bundled engine; no third-party Python packages are required. Structural indexing needs the pinned CodeGraph 1.6.0 CLI; execution and optional native enrichment need the configured test runners and their dependencies. The optional Python package exposes the same `faultline` command for local and CI use without an agent session.

See the [setup guide](docs/install.md) for installation and [API-key configuration](docs/install.md#5-configure-the-jev-api-key). Selected change text, test source and graph evidence are sent to Jev. Credentials, cached predictions, and reports stay in ignored `.faultline/`; source/test records and structural relationships live together in `.faultline/graphs/<hash>/graph.sqlite`.

## Status

Implemented: revision-specific CodeGraph artifacts with incremental reuse, portable baseline import/export and a primary graph source/test index, native PHPUnit/Behat discovery, batched and cached Jev evaluation, frozen proposals, validated full-suite execution, native/generic outcome import, and Markdown/JSON shadow reports. Existing semantic ranking and retrospective reports remain available.

**Shadow mode does not execute tests.** It saves proposals per PR/MR and aggregates them across snapshots. Actual execution requires `run --execute` and currently runs full suites; selective CI execution remains future work. Graph language support and framework wiring remain incomplete. Graph gaps are reported, while Jev continues scoring source, including Behat features. Unscored or partially scored targets remain proposed to run. Reports show semantic completion separately from graph limitations. Artifact producer trust is supplied by your CI storage permissions.

The [working TIA guide](docs/tia.md) explains setup and use. Tests include the actual pinned CodeGraph release against synthetic PHP fixtures; real-project regression recall and CI savings remain unproven. [PLAN.md](PLAN.md) tracks validation and future selective execution.
