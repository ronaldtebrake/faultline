# Faultline

Faultline is a planned, project-agnostic tool for ranking automated tests by their relevance to a software change. It aims to bring useful failure signals forward by comparing the intent and diff of a change with the behavior each test protects.

**Status: planning.** This README defines the project and its implementation plan. The commands below describe the proposed interface; they are not implemented yet.

## Hypothesis

Does the semantic meaning of tests contain enough information to rank regression-relevant tests substantially earlier than their normal execution order?

Large test suites can take a long time to reveal a regression. File paths, dependency graphs, coverage, and ownership provide useful signals, but behavior can cross those boundaries. Faultline will compare changes directly with test descriptions, without requiring a manually maintained project taxonomy.

The initial proof of concept will rank the complete test catalog and evaluate those rankings against historical results. It will not skip tests, impose test budgets, modify CI, trigger workflows, post comments, change required checks, or make merge decisions.

## Design

```text
Test sources → Discovery adapters → Semantic test profiles
                                             │
Change intent + diff ─────────────────────────┤
                                             ▼
                                     Semantic evaluator
                                             │
                                             ▼
                                    Ranked test catalog
                                             │
Historical outcomes + baseline rankings ──────┤
                                             ▼
                                     Local evaluation
                                             │
                                             ▼
                                    Markdown + JSON reports
```

The core data model, ranking logic, cache, evaluation, and reporting will be independent of the repository, programming language, test framework, source-control host, and CI provider. Adapters will handle discovery, profile extraction, change collection, and historical result import.

The first semantic evaluator will target TypeSafe Jev behind a replaceable interface. Its planned task is a bounded judgment: **How much regression-detection value does this test have for this change?** Model output supplies relevance evidence; application code defines ranking policy. Integration work will first verify the supported API, model identifiers, and probability-output contract.

### Semantic test profiles

Each test will have a stable identifier, source location, behavioral description, source hash, and optional metadata:

```json
{
  "id": "stable-test-id",
  "source": "tests/example",
  "description": "Verifies the behavior protected by this test.",
  "source_hash": "sha256:...",
  "metadata": {}
}
```

Prefer deterministic extraction from names, scenario titles, documentation, descriptive labels, steps, tags, and assertions. Poor descriptions must be visible for review. Generating descriptions with a separate model is a possible later enhancement, not a requirement for the first milestone.

Incremental indexing will preserve unchanged profiles, update changed tests, add new tests, and remove deleted tests. Users must be able to inspect each description and its provenance.

### Change context

The initial representation will contain the change title or intent, description, changed files, diff, and revision identifiers. Local commits and imported pull requests will use the same internal structure. Additional context, such as linked issues or changed symbols, can be evaluated later.

### Relevance and ranking

The evaluator will return a probability distribution over five defined levels:

| Level | Value | Meaning |
| --- | ---: | --- |
| Irrelevant | 0 | The protected behavior is unrelated to the change. |
| Weak | 1 | An indirect relationship exists, with little expected detection value. |
| Plausible | 2 | The change could reasonably affect the protected behavior. |
| Strong | 3 | A substantial semantic relationship makes the test useful regression coverage. |
| Direct | 4 | The test exercises behavior modified by the change. |

The initial score will be the expected relevance value:

```text
score = Σ(probability(level) × value(level))
```

Rank all tests by descending score, with a deterministic tie-breaker. Retain the complete probability distribution and evaluator provenance for inspection. A relevance score is not a calibrated probability that a test will fail.

### Local workflow and cache

Collection, indexing, evaluation, and reporting will be separate operations. Collection fetches existing metadata and results without model calls. Evaluation uses cached repository data and calls the evaluator only for missing predictions. Reporting uses local data only.

Proposed commands:

```bash
faultline index
faultline index show
faultline explain-test <test-id>
faultline rank --pr <number>
faultline rank --commit <revision>
faultline collect-history --limit 100
faultline evaluate
faultline report
```

An optional `faultline experiment --limit 100` command may later compose the workflow.

Proposed generated data layout:

```text
.faultline/
  test-index.json
  changes/
    <change-id>/
      change.json
      diff.patch
      runs.json
      test-results.json
      prediction.json
  predictions/
  reports/
    latest.json
    latest.md
```

Cache identity will include repository and revision identity. Prediction keys will also include hashes of all evaluator inputs, the test profile, question version, ranking schema, and evaluator/model version and configuration. Changing a question must not require downloading history again; changing one profile should invalidate only predictions involving that profile.

Generated data will be ignored by version control. Credentials will come from environment configuration and must never enter caches, reports, logs, or committed files. Local operation still involves sending selected change context and test profiles to the configured external evaluator; the data boundary must be documented before that integration is used.

## Historical evaluation

Collect a configurable sample of recent changes and their existing test runs. Preserve the exact tested revision and run attempt, rather than assuming the final merged revision represents an earlier failing run. Provider adapters normalize the data; an authenticated CLI can support an initial provider without becoming a core dependency.

Classify failures as confirmed regressions, likely flakes, infrastructure failures, known baseline failures, or unknown. Manual classification is acceptable for the first experiment. Only confirmed regressions contribute to regression-detection metrics.

Rankings must be generated without access to known failures, subsequent debugging comments, eventual fix explanations, or incident reports. Keep outcomes separate from evaluator input. Record when title or description snapshots cannot be recovered from the time of the run.

Using the current test index is acceptable for an exploratory first experiment, but it introduces suite drift and possible hindsight. Mark missing, renamed, or substantially changed tests, report matching coverage and exclusions, and distinguish these results from a benchmark reconstructed at historical revisions.

### Metrics and baselines

For confirmed regression changes, report:

- Hit rate at 1, 5, 10, 20, and 50: the fraction of changes with at least one known failing test in the first K positions.
- Failing-test recall at the same cutoffs: the fraction of known failing tests ranked in the first K positions, with the aggregation method stated.
- Median, p90, and worst first-failing-test rank, plus prominently displayed individual misses.
- Time to Semantic Failure, when duration data supports it: cumulative test duration through the first known failure in the proposed order.

Compare semantic ranking with existing execution order, seeded random orders, a configurable path or package heuristic, and lexical similarity. Use the same candidate catalog and outcome mappings for every method. Embedding similarity is an optional later baseline.

Time estimates must state their execution assumptions. A serial sum is not directly equivalent to wall-clock time from parallel or sharded historical runs; compare like-for-like schedules or clearly label that limitation. Report dataset size, missing data, exclusions, and uncertainty alongside improvements.

Green runs can reveal score distributions, selectivity, and ranking stability. They cannot establish that low-ranked tests were unnecessary.

### Reports

Generate both Markdown and machine-readable JSON containing dataset provenance, run and failure classifications, metrics, baseline comparisons, timing assumptions, model usage and cache statistics, and limitations.

Give poor rankings prominent space. Each miss should expose the change context, failing test, profile, rank, and probability distribution so a reviewer can investigate description quality, missing context, hidden dependencies, model judgment, or incorrect outcome classification.

## Implementation plan

### Step 1 — Reset the repository and establish this plan

- Remove the previous implementation, plugin files, documentation, tests, and other repository contents.
- Replace the local Git history with one new root commit containing this README.
- Adopt the Faultline name and define the new direction without project-specific assumptions.
- Use this README as the starting point for subsequent implementation work.

Completion: the repository contains only this README and Git metadata, with one initial commit. Any remote history replacement is a separate publishing action.

### Step 2 — Define the core contracts and CLI foundation

- Choose an implementation language and packaging approach based on portability and maintainability; supported test languages remain independent of this choice.
- Define versioned contracts for test profiles, change contexts, evaluator output, ranked results, historical runs, and failure classifications.
- Establish discovery, change-source, result-import, and evaluator interfaces.
- Add configuration, repository-scoped cache storage, ignore rules, and CLI command boundaries.

Completion: a small fixture-driven workflow can exchange the generic data structures without provider or framework assumptions in the core.

### Step 3 — Build incremental, inspectable indexing

- Implement a generic profile import path and one test-framework discovery adapter behind the same contract.
- Extract descriptions deterministically and preserve source provenance.
- Handle stable identities, source/profile hashes, additions, edits, deletions, and extraction-version changes.
- Implement index inspection and individual-test explanation.

Completion: a representative test catalog can be indexed and inspected, and repeat indexing preserves unchanged profiles correctly.

### Step 4 — Rank one change with Jev

- Normalize local commit and imported pull-request context.
- Verify Jev's integration contract and implement it behind the evaluator interface.
- Validate probability distributions, retain raw relevance evidence, calculate scores, and order the complete catalog deterministically.
- Cache predictions by their full input identity; handle service errors and incomplete responses explicitly.
- Produce readable terminal output and saved JSON.

Completion: one real change can be ranked, every test's evidence is inspectable, and rerunning with identical inputs reuses cached predictions.

**Milestone 1:** discovery for one framework, inspectable semantic profiles, one-change ranking, Jev probabilities, readable output, and local caching. Review several changes manually for sensible top results, low irrelevant scores, and useful cross-behavior matches before expanding the experiment.

### Step 5 — Collect and classify historical evidence

- Add read-only history collection through an initial provider adapter and a portable result-import contract.
- Capture changes, tested revisions, run attempts, test identities, outcomes, order, and durations where available.
- Cache collection independently from predictions.
- Support manual failure classification and record evidence, ambiguous mappings, missing artifacts, and suite drift.
- Enforce separation between ranking inputs and historical outcomes.

Completion: a configurable historical sample can be collected once and inspected locally without triggering or changing CI.

### Step 6 — Implement retrospective evaluation and baselines

- Generate predictions from cached change data without revealing outcomes to the evaluator.
- Implement existing-order, seeded-random, path/package, and lexical baselines.
- Calculate cutoff metrics, first-failure positions, and timing estimates with explicit denominators and scheduling assumptions.
- Record model/configuration versions, dataset provenance, exclusions, and evaluator cost and latency.

Completion: the same saved dataset supports reproducible comparisons across evaluator and question versions without repeated history downloads.

### Step 7 — Generate reports and assess the hypothesis

- Produce local Markdown and JSON reports with baseline comparisons, uncertainty, limitations, and detailed worst misses.
- Inspect green-run selectivity and stability separately from regression-detection performance.
- Investigate misses and measure the effect of changes to descriptions or context.
- Keep exploratory tuning separate from a held-out assessment when the dataset allows it.

**Milestone 2:** a complete local retrospective experiment containing historical changes and results, reviewed failure labels, semantic and baseline rankings, and inspectable reports.

Completion: evidence supports a documented decision to continue, revise the approach, or prefer a simpler baseline. No production threshold is assumed before observing data; any later validation threshold should be declared before evaluating a fresh dataset.

## Success and future scope

The experiment is promising if confirmed regression tests consistently move earlier, estimated failure discovery improves materially under comparable conditions, and semantic ranking adds value beyond path and lexical baselines. Broad, unselective scores or results comparable to simpler methods are reasons to reconsider. A negative result is useful.

Only after that evidence should execution policy change. Possible later stages are full-suite semantic ordering, a parallel fast lane backed by the complete suite, explicit time budgets, and eventually selective validation supported by production evidence.

Other deferred work includes additional adapters, historical-revision indexing, generated descriptions for poorly named tests, embedding baselines, high-recall candidate retrieval for very large suites, and combinations with coverage, failure history, runtime, and reliability. Each signal and policy must remain inspectable.
