# Faultline implementation plan

This plan covers the remaining work for the experiment described in the [README](README.md). No features or commands are implemented yet.

The initial proof of concept ranks the complete test catalog locally. It does not skip tests, impose test budgets, modify CI, trigger workflows, post comments, change required checks, or make merge decisions.

## Step 1 — Core contracts and CLI foundation

- Choose an implementation language and packaging approach based on portability and maintainability; supported test languages remain independent of this choice.
- Select the first discovery framework and history provider based on available representative fixtures; keep these choices behind adapters. Record the Jev API and model contract as an integration question to resolve in step 3.
- Define versioned contracts for test profiles, change contexts, evaluator output, ranked results, historical runs, and failure classifications.
- Establish discovery, change-source, result-import, and evaluator interfaces.
- Add configuration, repository-scoped cache storage, ignore rules, and CLI command boundaries.

### Architecture

The core data model, ranking logic, cache, evaluation, and reporting will be independent of the repository, programming language, test framework, source-control host, and CI provider. Adapters will handle discovery, profile extraction, change collection, and historical result import.

The first semantic evaluator will target TypeSafe Jev behind a replaceable interface. Its planned task is a bounded judgment: **How much regression-detection value does this test have for this change?** Model output supplies relevance evidence; application code defines ranking policy. Integration work will first verify the supported API, model identifiers, and probability-output contract.

### Local workflow and storage

The primary user workflow is `faultline analyze --pr <number>`. It incrementally updates the local test index, collects the selected PR/MR and its available CI evidence, ranks the applicable snapshots with Jev, compares eligible outcomes and baselines, and automatically saves findings plus Markdown and JSON case reports. Print a concise result and the report paths on completion. Users do not need to run each stage separately.

Collection, indexing, evaluation, and reporting remain separate internal operations, with stage-specific commands available for inspection and troubleshooting. Collection fetches existing metadata and results for one explicitly selected PR/MR without model calls. There is no bulk history scan or automatic polling in the initial version. Evaluation uses cached repository data and calls the evaluator only for missing predictions. Reporting uses local data only.

### Primary commands

```bash
faultline analyze --pr <number>
faultline analyze --pr <number> --refresh
faultline report --pr <number>
faultline report
```

`analyze` reuses completed cached work and resumes missing work. Its first invocation collects the selected PR/MR; subsequent invocations reuse that snapshot unless `--refresh` requests newer remote evidence. Show collection time and snapshot identity so cached results are not mistaken for live CI status. Index changes invalidate affected predictions and are recorded as suite drift where relevant.

Do not block report generation on manual failure classification. Unreviewed failures remain unknown and excluded from confirmed-regression metrics; the case report identifies what needs review. Once labels are updated, rerunning analysis recomputes comparisons from saved predictions without new Jev calls when ranking inputs are unchanged. API limits or missing evidence produce a clearly marked partial report and resumable status rather than silently presenting complete results.

### Generated data

Proposed generated data layout:

```text
.faultline/
  test-index.json
  changes/
    <change-id>/
      change.json
      runs.json
      evaluations/
        <evaluation-id>/
          findings.json
          report.json
          report.md
      snapshots/
        <snapshot-id>/
          context.json
          diff.patch
          prediction.json
      runs/
        <run-id>/<attempt>/
          run.json
          test-results.json
  predictions/
  reports/
    latest.json
    latest.md
```

Each evaluation record identifies its dataset snapshots, index hash, evaluator configuration, and classification version. Preserve earlier findings when these inputs change; repeated identical analysis reuses the same record. The top-level reports are local cross-PR summaries.

Cache identity will include provider, repository, PR/MR, and revision identity. Store each run and attempt separately, with its workflow/jobs and a reference to the applicable change snapshot; retain earlier snapshots when a PR/MR changes. Prediction keys will also include hashes of all evaluator inputs, the test profile, question version, ranking schema, and evaluator/model version and configuration. Changing a question must not require downloading history again; changing one profile should invalidate only predictions involving that profile.

Generated data will be ignored by version control. Credentials will come from environment configuration and must never enter caches, reports, logs, or committed files. Local operation still involves sending selected change context and test profiles to the configured external evaluator; the data boundary must be documented before that integration is used.


### API usage controls

- Use authenticated, serial requests per provider with configurable pacing. Fetch only metadata and test-result artifacts needed for the selected PR/MR; avoid downloading unrelated job logs or repeatedly polling unfinished runs.
- Reuse cached collection data by default. An explicit `--refresh` fetches updates, using conditional requests where supported, without overwriting earlier snapshots. Resume interrupted collection from saved progress and record whether pagination and artifact retrieval are complete.
- Respect provider rate-limit responses and retry timing. For GitHub, honor `Retry-After` and exhausted-quota reset headers; otherwise wait at least a minute after a secondary-limit response. Use bounded exponential backoff with jitter for retryable failures; do not repeatedly retry authentication, permission, or validation failures.
- Give collection and evaluation separate configurable request ceilings, counting retries. Persist progress and stop with a resumable status when a ceiling is reached. These are API-use ceilings, not test-selection budgets: an unfinished ranking is incomplete, never silently a ranking of the full catalog.
- Provide a local evaluation dry run showing snapshots, candidate counts, cache hits, and estimated uncached Jev requests. Enforce the configured ceiling before sending requests. A single PR can still require many test judgments.
- Verify Jev's actual account limits, payload/question limits, retry guidance, SDK retry behavior, and any batching or idempotency support before enabling live calls. Do not assume a published quota or that an ambiguous failed inference is free to retry. Use a finite retry policy and record actual usage where returned; label unavailable cost information as unknown.
- Keep completed predictions across interruptions; reruns evaluate only missing inputs. Reports make no API calls. Surface partial collection, exhausted limits, failed predictions, and cache hits in the report.

Reference: [GitHub REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api). Resolve Jev-specific limits against [TypeSafe's official documentation](https://docs.typesafe.ai/introduction) and the configured account during integration.

Completion: a small fixture-driven workflow can exchange the generic data structures without provider or framework assumptions in the core.

## Step 2 — Incremental indexing

- Implement a generic profile import path and one test-framework discovery adapter behind the same contract.
- Extract descriptions deterministically and preserve source provenance.
- Handle stable identities, source/profile hashes, additions, edits, deletions, and extraction-version changes.
- Implement index inspection and individual-test explanation.

### Test profiles

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

Proposed commands:

```bash
faultline index
faultline index show
faultline explain-test <test-id>
```

Completion: a representative test catalog can be indexed and inspected, and repeat indexing preserves unchanged profiles correctly.

## Step 3 — PR/MR Jev ranking

- Normalize an explicitly selected PR/MR and its cumulative change context. Do not expose standalone commit ranking in the initial CLI.
- Verify Jev's integration contract and implement it behind the evaluator interface.
- Validate probability distributions, retain raw relevance evidence, calculate scores, and order the complete catalog deterministically.
- Cache predictions by their full input identity; handle service errors and incomplete responses explicitly.
- Produce readable terminal output and saved JSON.

### Change context

The user selects a PR/MR, which may contain multiple commits and multiple CI runs. The initial representation contains its title or intent, description, changed files, cumulative diff, and base/head/tested revision identifiers. Commit identifiers are provenance, not the user-facing ranking unit. Additional context, such as linked issues or changed symbols, can be evaluated later.

For historical evaluation, reconstruct the cumulative change snapshot applicable to each tested revision, including a synthetic merge revision where relevant. Do not compare an early failing run with the final PR/MR diff or collapse its commits into unrelated one-commit judgments. Reuse predictions across reruns only when evaluator inputs match. If the historical context cannot be reconstructed, mark the run ineligible for confirmed historical ranking metrics rather than substituting the current diff.

The first provider's CLI uses `--pr <number>` in the current repository; the internal change contract also supports MRs through future adapters. `rank --pr` ranks the latest locally collected snapshot and reports its revision and collection time; it does not implicitly refresh remote data. Historical evaluation selects the snapshot belonging to each run.

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

Proposed commands:

```bash
faultline rank --pr <number>
```

Completion: one real PR/MR snapshot can be ranked, every test's evidence is inspectable, and rerunning with identical inputs reuses cached predictions.

**Milestone 1:** discovery for one framework, inspectable semantic profiles, PR/MR snapshot ranking, Jev probabilities, readable output, and local caching. Review several changes manually for sensible top results, low irrelevant scores, and useful cross-behavior matches before expanding the experiment.

## Step 4 — Historical collection

- Add read-only history collection through an initial provider adapter and a portable result-import contract.
- Capture changes, tested revisions, run attempts, test identities, outcomes, order, and durations where available.
- Cache collection independently from predictions.
- Support manual failure classification and record evidence, ambiguous mappings, missing artifacts, and suite drift.
- Enforce separation between ranking inputs and historical outcomes.

### Collection and evidence controls

Collect one explicitly selected PR/MR and its associated existing test runs, including earlier runs before fixes and subsequent reruns. A merged PR is not required. Additional PRs can be added individually to the local dataset later. Preserve the exact tested revision and run attempt, rather than assuming the final merged revision represents an earlier failing run. Provider adapters normalize the data; an authenticated CLI can support an initial provider without becoming a core dependency.

Classify failures as confirmed regressions, likely flakes, infrastructure failures, known baseline failures, or unknown. Manual classification is acceptable for the first experiment. Only confirmed regressions contribute to regression-detection metrics. Record classification per test outcome with supporting evidence: one run may contain both a real regression and unrelated failures. A successful retry alone does not prove flakiness.

Keep queued, cancelled, timed-out, skipped, unavailable, and partially collected runs visible as incomplete or unavailable evidence. Missing or expired artifacts are not green results. CI downtime and queue delays must not be counted as semantic-ranking misses or as time saved by ordering tests. Keep genuine confirmed test failures from mixed runs inspectable, and state the evidence coverage before including them in a metric.

Rankings must be generated without access to known failures, subsequent debugging comments, eventual fix explanations, or incident reports. Keep outcomes separate from evaluator input. Record when title or description snapshots cannot be recovered from the time of the run.

Using the current test index is acceptable for an exploratory first experiment, but it introduces suite drift and possible hindsight. Mark missing, renamed, or substantially changed tests, report matching coverage and exclusions, and distinguish these results from a benchmark reconstructed at historical revisions.

Proposed command:

```bash
faultline collect-history --pr <number>
faultline collect-history --pr <number> --refresh
```

Completion: one PR/MR with multiple commits, runs, and attempts can be collected, resumed, and inspected locally without triggering or changing CI. Adding another PR/MR preserves the existing dataset.

## Step 5 — Retrospective evaluation

- Compose indexing, collection, evaluation, and case-report generation into `analyze --pr`, retaining separate internal stages and their cache boundaries.
- Generate predictions from cached change data without revealing outcomes to the evaluator.
- Implement existing-order, seeded-random, path/package, and lexical baselines.
- Calculate cutoff metrics, first-failure positions, and timing estimates with explicit denominators and scheduling assumptions.
- Record model/configuration versions, dataset provenance, exclusions, and evaluator cost and latency.

### Metrics and baselines

A retrospective case study can start with one PR/MR; it does not require a batch of 100. Evaluate explicitly selected cached PRs, then optionally aggregate the saved results locally. One hand-picked case cannot establish general ranking quality: record how PRs were chosen and label a small or selected dataset as exploratory.

Keep per-snapshot and per-run findings available, but do not count repeated attempts as independent regression cases. For initial PR-level metrics, use the earliest snapshot with a confirmed regression and usable context/results per PR/MR, chosen independently of ranking scores. Deduplicate the same failing test across jobs/attempts for that snapshot and disclose other confirmed failures in the case report. Count distinct PRs in PR-level denominators, and report exclusions explicitly.

For eligible confirmed regression PRs, report:

- Hit rate at 1, 5, 10, 20, and 50: the fraction of changes with at least one known failing test in the first K positions.
- Failing-test recall at the same cutoffs: the fraction of known failing tests ranked in the first K positions, with the aggregation method stated.
- Median, p90, and worst first-failing-test rank, plus prominently displayed individual misses.
- Time to Semantic Failure, when duration data supports it: cumulative test duration through the first known failure in the proposed order.

Compare semantic ranking with existing execution order, seeded random orders, a configurable path or package heuristic, and lexical similarity. Use the same candidate catalog and outcome mappings for every method. Embedding similarity is an optional later baseline.

Time estimates must state their execution assumptions. A serial sum is not directly equivalent to wall-clock time from parallel or sharded historical runs; compare like-for-like schedules or clearly label that limitation. Report dataset size, missing data, exclusions, and uncertainty alongside improvements.

Green runs can reveal score distributions, selectivity, and ranking stability. They cannot establish that low-ranked tests were unnecessary.

Proposed command:

```bash
faultline evaluate --pr <number> --dry-run
faultline evaluate --pr <number>
```

Completion: a single `analyze --pr` invocation produces saved findings and a case report. The same saved dataset supports reproducible comparisons across evaluator and question versions without repeated history downloads.

## Step 6 — Reports and hypothesis assessment

- Produce local Markdown and JSON reports with baseline comparisons, uncertainty, limitations, and detailed worst misses.
- Inspect green-run selectivity and stability separately from regression-detection performance.
- Investigate misses and measure the effect of changes to descriptions or context.
- Keep exploratory tuning separate from a held-out assessment when the dataset allows it.

### Report contents

Generate both Markdown and machine-readable JSON containing dataset provenance, run and failure classifications, metrics, baseline comparisons, timing assumptions, model usage and cache statistics, and limitations.

Start with the selected PR/MR, snapshot and run timeline, collection completeness, and evidence quality. Separate confirmed regressions, suspected flakes, infrastructure problems, and unknown outcomes; show included/excluded counts and reasons. If no eligible confirmed regression exists, report that detection performance cannot be assessed, rather than reporting zero or perfect recall. Show counts alongside percentages, and avoid broad performance claims from one PR or unstable small-sample percentiles.

Give poor rankings prominent space. Each miss should expose the change context, failing test, profile, rank, and probability distribution so a reviewer can investigate description quality, missing context, hidden dependencies, model judgment, or incorrect outcome classification.

Proposed command:

```bash
faultline report --pr <number>
faultline report
```

Analysis already generates the individual case report. `report --pr` regenerates it from the latest saved findings without indexing, collecting, or calling Jev; it is optional, not a required next step. If saved findings do not exist or their inputs are outdated, state that analysis is needed rather than starting it implicitly.

The unscoped `report` generates an aggregate across saved, compatible evaluations, using one current evaluation per PR/MR so reruns do not inflate counts. Keep different evaluator versions or configurations in separate comparison groups. Show the number of distinct PRs, exclusions, and dataset limitations; with one PR, clearly label the summary as a single case. It makes no API calls.

**Milestone 2:** a complete local retrospective experiment containing historical changes and results, reviewed failure labels, semantic and baseline rankings, and inspectable reports.

Completion: evidence supports a documented decision to continue, revise the approach, or prefer a simpler baseline. No production threshold is assumed before observing data; any later validation threshold should be declared before evaluating a fresh dataset.

## Success and future work

The experiment is promising if confirmed regression tests consistently move earlier, estimated failure discovery improves materially under comparable conditions, and semantic ranking adds value beyond path and lexical baselines. Broad, unselective scores or results comparable to simpler methods are reasons to reconsider. A negative result is useful.

Only after that evidence should execution policy change. Possible later stages are full-suite semantic ordering, a parallel fast lane backed by the complete suite, explicit time budgets, and eventually selective validation supported by production evidence.

Other deferred work includes additional adapters, historical-revision indexing, generated descriptions for poorly named tests, embedding baselines, high-recall candidate retrieval for very large suites, and combinations with coverage, failure history, runtime, and reliability. Each signal and policy must remain inspectable.

Bulk collection is deferred until the single-PR workflow, API-use controls, and report quality have been validated. The single-PR `analyze` workflow is part of the initial retrospective milestone.

## Validation scenarios

- One PR with multiple commits: an early failure and later fix use their own cumulative snapshots; no final-diff leakage occurs.
- Reruns and mixed outcomes: duplicate attempts do not inflate regression counts, and flaky/infrastructure outcomes do not erase separately confirmed regressions.
- Missing artifacts, CI downtime, or unreconstructable context: reports show exclusions and unknowns without treating missing data as passes or ranking misses.
- A green-only or single-PR dataset: produce a useful case report without implying evidence of general regression-detection performance.
- Warm-cache reruns and offline reports: unchanged completed inputs generate no additional provider or Jev requests.
- Pagination interruption, rate limiting, exhausted request ceilings, and incomplete model output: persist progress, stop or back off as appropriate, resume missing work, and label incomplete rankings.

- Primary workflow: one `analyze --pr` invocation produces findings and both case-report formats; no separate report command is required.
- Classification updates: rerunning analysis refreshes metrics without repeating unchanged Jev predictions; unknown failures never become confirmed automatically.
- Aggregate reports: two analyzed PRs appear once each, repeated analysis does not increase the denominator, and incompatible evaluator configurations remain separate.
