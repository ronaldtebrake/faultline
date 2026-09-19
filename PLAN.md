# Faultline implementation and validation plan

## Goal and architecture

Build a language-agnostic test impact analysis engine for CI and coding agents. Combine deterministic positive impact evidence with Jev relevance judgments to reduce CI work while preserving observed regression detection. Semantic relevance, regression recall, and measured code coverage are separate metrics. No policy guarantees preservation of all coverage.

The Python engine owns discovery validation, scoring, selection, caching, execution, and reporting. CodeGraph 1.6.0 owns structural parsing/resolution and its embedded SQLite graph. Faultline snapshots both base and head, reuses immutable artifacts, and joins reverse file relationships to provisional targets from configured source paths. Analysis never invokes native runners by default; native enrichment is explicit, and mandatory runner validation occurs only for the suite being executed. Existing coverage tooling is optional positive enrichment; do not build a language parser stack. The skill supports setup, reviewed descriptions, local use, and explanations. CI requires the engine and test environment, not a coding-agent session.

Git shares `faultline.json` and `faultline/catalog/`. Ignored `.faultline/` holds credentials, native evidence, predictions, caches, and reports. Bootstrap descriptions once from readable test names/steps; use an agent only where enrichment helps. Developers review changed descriptions with their tests. Production changes affect execution without necessarily invalidating descriptions. Missing descriptions require execution, never automatic AI generation in CI.

## Flow and integrations

```mermaid
flowchart TD
    DEV["Developer + coding agent: maintain descriptions"] --> GIT["Git: code, suite configuration, catalog"]
    GIT --> CI["CI checks out tested revision"]
    CI --> GRAPH["CodeGraph: exact base/head graph artifacts"]
    GRAPH --> DISC["Source discovery + catalog check (no runners)"]
    DEV --> LOCAL["Optional local engine use"]
    DISC --> SELECT["select: mandatory rules + semantic judgments"]
    LOCAL --> SELECT
    SELECT <-->|"Selected change context and test evidence"| JEV["Jev API"]
    STORE["Trusted CI cache artifacts"] --> SELECT
    STORE --> GRAPH
    SELECT --> FROZEN["Frozen selection.json"]
    FROZEN --> RUN["run: validate requested runner, then full suite"]
    RUN --> RUNNERS["PHPUnit / Behat; Playwright next"]
    RUNNERS --> REPORT["record + shadow-report: outcomes, misses, time, costs"]
    REPORT --> STORE
    REPORT --> DEV
```

`graph build/inspect`, `discover`, `catalog`, `select`, `run`, `record`, `shadow-report`, and optional `mapping import-phpunit` are implemented for full-suite shadow use. Existing CI artifact tooling transports immutable graph and Jev caches; producer authentication remains a CI responsibility. Existing `rank`, `evaluate`, and `report` retain their legacy ranking contracts.

Git/hosting tooling supplies cumulative PR/MR changes, tested revisions, and outcome artifacts. CI retains containers, services, isolation, matrices, and scheduling. Faultline does not replace hosting platforms or the CI scheduler.

## Stage 1 — Shared catalog and native runner contracts

Implemented:

- Source-only `discover`, catalog maintenance, and `select`; explicit `--native` enrichment. Whole checks use `kind: "check"` and need no individual test inventory.
- Versioned configuration and generic JSON discovery; native PHPUnit 9.6 list XML plus Composer class-map discovery, and Behat 3.29 dry-run JUnit discovery.
- Execution receipts retain PHPUnit classes/datasets, Behat scenario/outline members, and configured matrix variants. Runner identity is authoritative; agents cannot invent it. Unverified runner versions require a generic bridge or full execution.
- `discover`, `catalog show/check/sync/import`, explicit review provenance, source/context hashing, additions/removals, and migration from the legacy local catalog. Incomplete discovery cannot replace a catalog.
- Shared descriptions can be reused across checkouts without inference. Description freshness and shared execution inputs are recorded separately.
- `mapping import-phpunit` reads native test-attributed XML and hashes source reports. It imports positive relationships; no custom PHP parser or coverage instrumentation. Unknown identities remain visible and absent relationships do not imply irrelevance.

Validation completed: offline reuse, freshness, incomplete discovery, migration, variant identities, malformed inputs, native parser fixtures, and mapping tests. Isolated smoke tests used installed PHPUnit 9.6.34, Behat 3.29.0, and php-code-coverage 9.2.32; Xdebug produced per-test line mappings. These were synthetic tests, not a real application pilot.

Remaining acceptance: validate a complete real suite inventory and reviewed descriptions at the chosen PR revision, verify native IDs against actual execution/results, bound discovery/indexing effort, and qualify remote-process coverage before using it. Extend the verified runner-version range through conformance fixtures. Behat HTTP coverage requires evidence from the application-serving process; local CLI coverage is insufficient. See [the command and data contracts](skills/faultline/references/shared-catalog.md).

## Stage 2 — CodeGraph selection engine and shadow execution

Implemented shadow path: exact Git source export into isolated snapshots; pinned producer/schema validation; portable closed SQLite artifacts; compatible incremental reuse; base/head reverse dependency evidence; source-gap and traversal-limit fallbacks; graph-context Jev batching and immutable answer caches; full execution receipts; JUnit/generic outcome recording; per-case and aggregate reports.

Validated with offline contract tests and the actual CodeGraph 1.6.0 executable on synthetic PHP dependencies. Live Jev evaluation and real CI recall remain unverified. See [the working workflow](skills/faultline/references/graph-workflow.md).

The requirements below span the implemented shadow path and future selective execution. Exact filtering, trusted suspension state, automatic audits, broader native runner versions, and production CI trust configuration are not enabled by this stage.


- Normalize the cumulative PR/MR diff and exact tested snapshot, including synthetic merge revisions. Freeze base/head, configuration/catalog/policy versions, evidence hashes, selected/omitted units, reasons, fallbacks, prerequisites, timings, and usage in immutable `selection.json`.
- Expose `select`, `run --selection … --suite …`, and `record`. Reject revision/configuration/catalog mismatches before execution. Validate native identities only for the requested suite at execution; inventory disagreement or failure requires full execution and an incomplete assessment. Preserve runner exit status. Never interpret missing, empty, invalid, or interrupted decisions as permission to run zero tests.
- Mandatory execution includes changed/new tests, must-run rules, positive dependency/coverage matches, relevant setup changes, unresolved failures, and uncertain units. Missing relationships are not negative evidence. Bound unknown changes by explicit scope; unbounded unknowns execute every suite.
- Use native filtering at file/class granularity, including all associated datasets, scenarios, and variants. Validate exact selectors against discovery; unsupported filters or unresolved prerequisites widen execution. CI supplies services, containers, and scheduling.
- Default to shadow mode: freeze the proposal, then run everything. Reviewed experimental opt-in may omit only complete/current units with `P(irrelevant) >= 0.95`. This is an experimental threshold, not a calibrated safety guarantee.
- On missing credentials, Jev errors, invalid responses/selectors, insufficient evidence, expired/unavailable trusted state, or exhausted budgets, execute the affected suite fully and record why.
- Retain the five-level evaluator (`irrelevant`, `weak`, `plausible`, `strong`, `direct`), probabilities, expected 0–4 score, deterministic identity tie-breaks, and pinned model/evaluator versions. Benchmark evaluator changes separately.
- The official multi-question HTTP contract is verified; validate live model behavior and batch several judgments against shared change context. Bound batch bytes/units, requests including retries, and elapsed time; validate each answer independently. Keep existing serial pacing, bounded retry/backoff, interruption recovery, and credential-safe errors.
- Cache actual complete inference inputs: selected change text, test evidence, full batch context, question/schema, and model/evaluator versions. PR numbers, timestamps, and run metadata are provenance outside inference identity. Similar descriptions do not justify reuse across changed inputs.
- Share immutable caches using existing CI artifacts. Only trusted jobs publish reusable evidence; PR jobs cannot overwrite trusted caches. Missing artifacts are cache misses. Integrity hashes detect modification, not malicious producers; enforce producer trust outside those hashes.
- Keep `TYPESAFE_API_KEY` resolution from environment, `.faultline/.env`, then root `.env`. No credentials in evidence; read them only for live evaluation. No embeddings, lexical top-K exclusion, vector database, or hosted service initially.

**Milestone 1:** inspectable indexing and cached ranking of a real cumulative change, with reproducible native identities, shared descriptions, frozen decisions, visible fallbacks, and verified execution behavior. A second checkout reuses descriptions, compatible graph artifacts, and identical inference inputs without repeated full indexing or calls.

## Stage 3 — Prospective shadow pilot

Next validation: run the complete graph-backed workflow on a representative PR/MR, using its actual diff base and tested head. Audit graph relationships against native inventory, including custom PHP extensions, YAML service wiring, Gherkin steps, and remote boundaries. Keep outcomes hidden until proposals are frozen. Validate Linux artifact reuse, indexing resources, and graph-only versus hybrid evidence before considering selective execution.

The implemented reports group retries and suites by compatible change snapshot, retain exact observations, and publish denominators and descriptive uncertainty. Baselines currently compare equal execution-unit counts; equal-runtime budgets, setup/job savings, audit costs, and externally incurred agent costs need further measurement.


- Start with one ordinary PR/MR. Preserve existing full execution; do not scan a hundred PRs or trigger historical reruns by default. Resolve exact tested revisions/attempts with bounded, cached hosting calls.
- Freeze decisions before outcomes exist. Collect green runs, regressions, flakes, infrastructure failures, and incomplete/expired runs. Passing retries are not automatically flakes; CI downtime is not a product regression.
- Use the existing test runner's result/coverage producers. Qualify coverage-driver overhead and remote application attribution separately. Importer provenance must include source revision, runner variant, scope, and collection completeness.
- Match outcome identities exactly. A known failure missing from the catalog excludes the corresponding recall claim. Unexecuted tests are unknown, never passing. Current-catalog retrospective cases disclose suite drift; retain each exact catalog snapshot.
- Compare full execution, deterministic dependency/path rules, lexical selection, Jev, and the hybrid at equal execution budgets or observed recall. Preserve existing seeded-random and verified historical-order ranking baselines. Keep tuning cases apart from later assessment cases.
- Produce Markdown and JSON reports after a single case; subsequent cases accumulate without repeated downloads/inference. Publish denominators, exclusions, and uncertainty. Repeated attempts are not independent regression cases.
- Failing-change recall measures whether any regression is detected in a change. Failing-test recall measures the fraction of known failing tests included. Coverage is reported only from instrumentation. Savings subtract selection, setup, and audit overhead from avoided execution.
- Report Jev usage, description/indexing effort, selection latency, execution minutes, jobs/setup avoided, and audit overhead separately. Use dated configurable pricing; external agent costs remain unknown unless supplied. Serial duration sums are estimates, not parallel CI wall-clock measurements.
- Aggregate compatible policies across ordinary catalog evolution while preserving per-case evidence. Investigate misses after freezing and evaluating; do not rewrite evidence or retroactively tune the original prediction.

**Milestone 2:** reproducible evaluation of real cases with baselines, traceable classifications, reports, and limitations. One PR should yield an understandable report; a second case should join the aggregate without repeating unchanged work. A green run cannot establish regression recall or safe omission.

## Stage 4 — Experimental selection

- Require per-suite reviewed configuration and explicit maintainer opt-in. No automatic promotion, including when evidence remains limited.
- Preserve full post-merge runs and a deterministic, outcome-independent 10% sample of PR snapshots. Include audit cost in savings.
- An observed missed regression suspends that suite's selection through trusted CI state until reviewed. Missing suspension state means full execution. Post-merge detection does not establish pre-merge safety.
- Validate setup dependencies, exact selectors, additions/removals, stale evidence, failure-state persistence, budgets, credentials, cache trust, and interruptions. Every incomplete decision must produce a visible full-execution fallback.

## Stage 5 — Extension and distribution

Publish versioned CLI/plugin releases, native conformance fixtures, and extension contracts. Add Playwright through the same contract; browser-only coverage does not imply backend coverage. Qualify existing producers before writing new instrumentation. Agent installations and CI use the same Python implementation; scripts and references remain self-contained inside the skill.

Keep local agent support alongside CI validation. Consider additional runner versions, native dependency/coverage producers, and better cost models after measuring the initial pipeline. Embeddings, hosted services, retrieval exclusions, and alternative evaluators remain deferred experiments with independent benchmarks.

## Existing ranking and historical contracts to preserve

The legacy engine and skill already implement the following. Their offline tests remain regressions for the shared-engine work; they do not establish that the new selection pipeline is complete.

### Existing Jev ranking — Fixed Jev evaluation and reproducible ranking

Implemented:

- The ranking workflow gathers cumulative PR/MR context and the actual tested revision. Revision IDs are provenance, not a standalone commit-ranking UX.
- Versioned evaluator `relevance-v1`, using a fixed Choice question and five definitions: irrelevant, weak, plausible, strong, direct. Initial model: `jev-1.13.0`, configurable only as a pinned version.
- Probability validation, expected relevance scoring with values 0–4, and deterministic test-ID tie-breaking. The agent never modifies scores or order.
- `rank` / `jev-evaluate` accept structured change/catalog files, expose a network-free dry run, cache each test judgment, and save full probabilities plus a readable ranking. Cache identity includes relevant change input, snapshot, profile, question/schema, and model configuration.
- Complete predictions are frozen with an integrity hash and full source inputs. Partial attempts remain inspectable and resume from completed pair predictions. Integrity checks detect accidental edits, not dishonest agent attestations.
- Jev transport uses serial paced calls, an explicit request ceiling including retries, bounded backoff for rate limiting/overload, persisted cooldowns, and no automatic retry of ambiguous connection failures. Oversized context is rejected rather than silently truncated. Credentials come from the environment or local `.env` files, are loaded only for live evaluation, and never enter saved evidence.

Acceptance: inspect rankings for several real changes; verify unrelated tests score low and relevant cross-behavior tests appear high. Live service access and ranking quality remain unverified. Offline tests exercise the HTTP contract, invalid probabilities, interruption/reuse, request limits, model versions, and credential-safe errors.

**Legacy ranking milestone:** an installable self-contained skill, inspectable incremental catalogs, one-change semantic ranking, probability evidence, deterministic order, and local caches. Code and skill packaging are implemented; real-change validation is the next experiment.

### Existing historical collection — Historical evidence without hindsight

Implemented as skill workflow and structured contracts:

1. Select a PR/MR and snapshots independently of failures. Read only outcome-blind intent/diff and run identity/revision metadata.
2. Build/freeze each complete prediction before reading conclusions, artifacts, debugging comments, or test outcomes.
3. Retrieve existing results through the agent's available tools, without triggering workflows. Preserve run IDs, attempts, tested snapshots, collection completeness, and evidence locations.
4. Normalize outcomes into the generic schema. Require explicit test identities and evidence for non-unknown failure labels. Keep ambiguous matching and missing tests visible.
5. Classify confirmed regressions, likely flakes, infrastructure, baseline, and unknowns. Do not equate a red workflow with a regression or a passing retry with proof of flakiness.

Historical context must match the tested snapshot, including synthetic merge revisions when applicable. Omit edited PR text if its pre-outcome form is unavailable. Do not substitute a final fixed diff. A current test index is explicitly exploratory because of suite drift.

The script validates declared outcome-blind provenance and requires an outcome-collection timestamp after the completed prediction. It cannot independently prove what an agent has seen. A contaminated agent context must not claim blindness; use a genuinely fresh allowed context or disclose that the experiment is invalid.

Hosting calls are the agent's responsibility: serial authenticated requests, local reuse, explicit refresh, a finite collection budget (default 100 calls), pagination accounting, and honoring provider backoff/reset instructions. Jev's request ceiling is independently enforced by code.

Acceptance: one real PR/MR with multiple commits and attempts produces separate applicable predictions and traceable outcome records. Missing/expired artifacts, CI downtime, and incorrect revision mappings remain exclusions or limitations, not false successes.

### Existing evaluation — Evaluation and reports in the same interaction

Implemented:

- An agent request to analyze one PR/MR runs the complete skill workflow. Users need not manually invoke indexing, ranking, comparison, and report commands.
- `evaluate` compares a complete frozen prediction with subsequently collected outcomes and automatically saves `findings.json`, `report.json`, and `report.md`. Updating classifications recalculates measurements without repeating unchanged Jev calls.
- Baselines use identical catalogs: lexical cosine similarity over words, shared-path proximity, deterministic seeded random order, and verified historical execution order when available.
- Metrics distinguish hit rate from failing-test recall at 1, 5, 10, 20, 50, plus first-failure positions. A confirmed failure missing from the catalog excludes that run's metrics to avoid optimistic recall.
- Time to Semantic Failure is a serial duration sum, available only with every needed duration. Queueing and infrastructure downtime are excluded. Parallel/unknown scheduling is not presented as observed wall-clock improvement.
- Per-case reports expose coverage, classifications, exclusions, complete rankings, and worst misses. Green/unknown-only evidence says regression-detection performance cannot be assessed.
- Offline `report --prediction` regenerates a case report. Unscoped `report` aggregates saved evidence, counting one earliest eligible case per PR/MR and separating repositories/evaluator configurations/index hashes/random seeds. Repeated attempts do not increase denominators. Recall is macro-averaged; p90 is omitted below ten cases.
- The agent adds evidence-based narrative and investigates misses without changing the authoritative JSON measurements. Improvements after inspecting outcomes belong to a new experiment, preserving the original frozen result.

Acceptance: a real single-PR request ends with an understandable case report and its evidence; a second case joins the aggregate without repeated downloads or inference. Offline tests cover this pipeline and report generation, including no eligible regressions, reruns, wrong revisions, missing durations, multiple PRs, and evaluator separation.

**Legacy evaluation milestone:** reproducible historical evaluation with evidence-based labels, baselines, and local reports. The deterministic pipeline is implemented and tested with synthetic fixtures. Real-history usefulness remains to be established.
