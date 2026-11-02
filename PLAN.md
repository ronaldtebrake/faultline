# Validation plan

## Priority: task input contracts and result reuse, 2026-11-02

Use a framework-independent task graph to reduce CI work. Read existing package
and CI declarations, then record reviewed input boundaries, transitive task
dependencies and runtime/fixture identities in `faultline.json`. Framework
adapters and per-scenario server tracing are not prerequisites. Keep source
relationships as supplementary positive evidence; retain optional Jev work off.

Implement immutable input fingerprints, new/deleted-file membership changes,
global fallback for unmapped files and successful-result reuse. Cache task
results separately from parser facts. The default runner executes full checks
even on cache matches; reuse requires an explicit option. Keep full consumer CI.

Ship a self-contained `faultline-tasks` skill for initial configuration and
maintenance when dependencies change. Integrate through the package/shared
action without consumer helpers. Validate cold/warm sharing, independent and
transitive changes, new inputs and failure invalidation. Measure eligible task
time separately from provisioning and CI wall time. Broad application inputs
may retain entire suites; do not narrow them to improve apparent savings.
Artifact restoration and pre-runner scheduling are subsequent work.

Implemented preview: task plans, full shadow execution, opt-in result reuse and
shared GitHub cache transport, plus the installable configuration skill. The
exact engine tree passes 212 tests (two optional native checks skipped).
[Fresh-runner CI](https://github.com/ronaldtebrake/faultline/actions/runs/41417169308)
restores matching successful results into a second job, executes both checks
fully, then verifies explicit reuse only in the synthetic fixture. Tracked
internal symlink targets and directory membership are covered generically.
Consumer validation uses existing inexpensive checks while full application
CI remains enabled; task-cache eligibility is not a measured application speedup.

## Current direction: graph default, Jev optional and off

The primary assessment path is the source/runtime dependency graph. `assess` and `select` run without inference; explicit `--jev` enables optional scoring, including resumes. Missing paths stay unresolved and cannot authorize omissions. Keep full consumer CI running while testing graph behavior and caching.

1. Implement and verify offline defaults, explicit paid opt-in, readable affected paths and frozen reports. Preserve mandatory rules, unknown-input fallbacks and existing execution guards.
2. Install the pinned package in a new throwaway consumer draft PR, without vendoring the engine. Restore and publish shared source baselines while normal test matrices run fully.
3. Create a stacked draft branch with controlled source/test changes. Freeze predictions before outcomes; compare incremental stack impact and cumulative main-branch impact. Verify cold/warm restoration, unchanged-fact reuse and changed-input invalidation.
4. Compare predictions against complete native CI outcomes and existing runtime observations. Classify failures as change-caused regressions, flakes, infrastructure or unknown. Keep attempt/shard identities and runtime coverage gaps visible.
5. Only consider test skipping after held-out regression evidence and a separate adoption decision. No automatic promotion from graph reachability, model relevance or cache reuse.

All consumer experiment PR titles contain `[WIP] DONT MERGE`; close them after validation. The earlier two-case probe is historical cache evidence, not permission to reduce the full test matrices in this new experiment. Private source, reports and run identifiers remain in the consumer workspace.

The completed historical with/without-Jev study did not demonstrate incremental regression-detection value from Jev. Observed unrelated failures are not automatically missed regressions. Keep Jev available for later controlled research; do not spend on it during this graph-validation milestone. Full-suite coverage, regression recall and CI savings remain unproven.

Implementation verified on 2026-11-01: the exact published engine tree passes 192 tests (two optional native checks skipped). New checks cover zero inference with credentials present, explicit paid opt-in and resume, transitive/deleted paths, mandatory rules, warm parsing, and rejection of graph reports as selective manifests. Workflow Actionlint passes. The private consumer cold/warm graph jobs also pass: the descendant restores the trusted ancestor baseline, reparses two controlled changes, reuses unchanged facts and reports the expected paths with zero Jev calls. Full consumer CI remains running with its original matrices and commands; its complete outcomes and runtime coverage are still pending. No omission policy is enabled.

Consumer integration implemented and locally verified (197 tests, two optional native checks skipped): move CI orchestration and experiment assertions into `faultline graph ci` and the pinned `actions/graph` action. Display would-run targets, reasons and dependency paths in the job summary, with complete artifacts. The separate consumer new-file stack now passes live CI: it restores the packaged baseline, discovers a new helper and test through unchanged configuration, verifies paths to existing tests, and publishes a larger source baseline. Job summaries and frozen artifacts expose would-run targets. Original full-CI heads/runs remain intact. Their checked-out merge trees match the predicted heads; complete changed-branch test outcomes remain pending, so no missed-regression rate is claimed.

Next controlled regression check: start with an integration-only baseline from
the consumer's main branch. Add a new test and deliberately change production
behavior that an unchanged main-branch test already covers. Freeze the graph
prediction before running tests; verify the exact affected sources, the unchanged
existing test blobs, and an unrelated configured test as a negative control.
Use native tests to establish passing control and failing-change outcomes, while
retaining all normal CI matrices. Keep the intentional regression isolated in a
throwaway draft PR. This is a designed sensitivity check, not held-out recall.

The package controls pass 199 checks in the exact published tree (two optional
native checks skipped), and its installation self-test passes in live CI. The
fresh consumer baseline producer and its descendant graph CI both pass. The
descendant asserts remote restoration, exactly two changed/added parsed sources,
at least 6,000 reused facts, new-target discovery, exact affected sources and
unchanged existing test blobs; configuration is unchanged. Local native control runs validate
the designed regression: the main module passes, the changed module has exactly
the new and unchanged expected assertion failures, and restoring production
behavior while keeping the new test passes again. The frozen graph retains both
failing files, retains a passing mocked consumer conservatively, and leaves the
unrelated passing control unresolved. Full remote CI and general recall remain
separate; no skipping or Jev calls are enabled.


Two further reference examples now copy pinned snapshots of open consumer PRs
onto a clean integration baseline, then stack the copies. Verify identical
patch bytes and changed-file blobs, preserve the original PRs, and show original,
incremental-copy and combined-stack predictions before inspecting copy outcomes.
The original and copied revisions retain the same affected source sets. One
example retains an existing test and a new test through production dependencies;
the other retains only a newly added test, with no resolved path from its changed
production classes. Surface that gap in the review instead of interpreting a
small candidate set as sufficient coverage. Keep full native CI enabled and
Jev off. Private references, source paths, summaries and artifacts stay with the
consumer experiment; update the at-a-glance comparison as CI evidence arrives. Both copied
graph CI jobs passed remote parent-baseline restoration and reuse checks. Full
native QA remains queued; no new recall or performance claim is established.

## Installation and inspection objective: verified preview, 2026-11-01

The requested installation skill, dependency package and readable graph/query
interface are implemented on `codex/reusable-ci-setup`. They are installable from
a full commit SHA; the default branch and package version have not been promoted
to a new release. [Installation](docs/install.md) gives the preview commands.

| Requested outcome | Current evidence |
| --- | --- |
| Skill guides installation, including GitHub CI | `skills/faultline/SKILL.md` routes to a self-contained installation guide and source-baseline workflow. Skill validation passes; `skills add` discovers the published pinned skill. An extracted standalone bundle resolves every local reference and runs the file query successfully. |
| Faultline installs as a dependency without consumer vendoring | `pyproject.toml` builds the package and `actions/setup` installs the exact action revision in an isolated environment. Local and live CI package installation pass. The earlier private consumer migration also passed, with its engine copy removed. |
| Consumer interface can survive a later Rust/Go implementation | The executable and versioned JSON report are the documented boundary in `docs/cli-contract.md`; the new consumer workflow invokes CLI commands, not Python internals. The current engine remains Python; another backend and speed claims are future work. |
| Readable dependency tree/cache and file-impact inspection | JSON snapshots expose nodes, typed edges, targets, provenance and gaps. `graph affected --file` returns positive paths and unresolved/unknown inputs; `graph compare` reviews committed changes. Installed and bundled CLI checks pass. |
| Added/changed/deleted files are reviewable | Regression fixtures cover newly resolved imports, deleted dependencies using an older snapshot, removed targets, cycles, setup inputs and unchanged Git snapshots despite dirty working files. Source inspection remains explicitly commit-based. |
| Preserve future Jev and Entire work | Graph queries and baseline CI make zero Jev requests. Controlled with/without-Jev comparisons, regression recall and an optional Entire source-graph adapter remain explicit future experiments below. They are not implied by cache reuse. |

Validation: 41 graph/query/shared-baseline checks ran, with 39 passing and two
optional native checks skipped. The installed package also ran the actual source
workflow's build, compare and pack commands in separate synthetic checkouts; a
local restore reused unchanged facts. YAML lint and skill validation passed.

Live [cold CI](https://github.com/ronaldtebrake/faultline/actions/runs/41288487287)
built ten facts and published a baseline. The subsequent
[warm CI](https://github.com/ronaldtebrake/faultline/actions/runs/41288686037)
authenticated that exact producer/artifact, parsed one changed source and reused
nine unchanged facts. Both installations returned the expected file-to-test path
with no model requests or test-selection decisions. These are synthetic protocol
and installation checks, not full application coverage or a measured speedup.

The completion audit also exposed unordered artifact results: an older compatible
baseline was selected before a newer one. Retrieval now sorts the bounded page by
creation time before applying its candidate limit. Regression checks cover out-of-
order IDs, malformed timestamps and fallback from a corrupt newer artifact. The
[corrected engine's CI](https://github.com/ronaldtebrake/faultline/actions/runs/41289291657)
passes. Preview installation and the consumer template pin that corrected engine.

The consumer draft used for earlier validation was found closed and was left
closed. Further installation verification runs in Faultline's own repository.

## Completed controlled milestone: shared CI baseline reuse

Pilot scope update: the user authorized fixed, smaller test probes in the
throwaway consumer PR to obtain cache evidence faster. The initial broad run
verified live Behat/Playwright imports, then was stopped before complete suite
execution. A dedicated two-case native Playwright workflow now verifies sharing
and invalidation against the complete repository source graph. The cases are
explicit experimental controls, not graph-selected product tests. This does not
authorize production omissions. The successful cold/warm pair now establishes
remote restoration, parser reuse and controlled runtime invalidation.

Priority updated on 2026-10-31: implement and validate a shared dependency
baseline before enabling graph-driven test skipping. Normal test runs and merge
gates retain full execution. The disposable consumer experiment may use the
explicit fixed probe described above; this exception does not change production
selection policy.

1. Package validated Behat and Playwright observations and reusable graph facts
   as versioned baseline artifacts, with exact repository/revision, suite,
   variant, configuration and producer provenance.
2. Publish baseline artifacts from full CI runs and retrieve an eligible trusted
   ancestor baseline in later runs. Missing, expired, incompatible or invalid
   artifacts take the cold analysis path and must not affect full test execution.
3. Measure graph preparation, reused and invalidated facts, source coverage gaps,
   and correspondence with fresh observations. Preserve run, shard and attempt
   identities; do not treat missing observations as proof of independence.
4. Validate restoration and invalidation across changes using synthetic fixtures,
   then exercise actual consumer CI collection and a controlled cold/warm probe.
   Full application coverage remains a separate validation requirement.
5. Use temporary draft consumer PRs for the experiment. Their titles must contain
   `[WIP] DONT MERGE`, and their descriptions must explain that they will be
   closed after validation. Draft publication is authorized; merging is not.

Acceptance: a later CI probe demonstrably restores a compatible baseline,
reuses unchanged graph work, refreshes changed inputs and reports those decisions.
Invalid baseline cases still run all tests. This milestone neither publishes
selective execution decisions nor enables omission, and requires no Jev calls.
Evaluate CI/test selection only after baseline validation and a separate decision
to proceed.

Validated on 2026-10-31: a cold CI run published parser facts and two native test
observations. Its descendant restored the exact authenticated ancestor artifact,
parsed only the single changed source, carried the unchanged observation and
invalidated the changed observation. Both cases ran again and their fresh
observations matched these expectations. CI asserts these conditions before
publishing a replacement baseline. No Jev requests or omission decisions occurred.

The first warm attempt exposed unavailable PHP tokenization under isolated
`php -n` on shared-extension runners. The loader now explicitly loads the
installed tokenizer when necessary, preserving INI isolation. The corrected
cold/warm pair passed; local graph/shared-baseline regressions also pass.
Private reports, revisions and run/artifact identifiers stay in the consumer's
ignored workspace and temporary draft PR. Earlier live Behat and generated
Playwright imports were verified separately; the broad run was cancelled.

This completes the controlled cross-run baseline milestone, not full application
coverage or a performance win. The measured warm aggregation took longer than
the cold aggregation despite near-total parser reuse. Measure download, baseline
validation, historical/current graph resolution and cache-write costs separately
before claiming CI savings. Full-suite bundle scale, dependency completeness and
regression recall remain unvalidated; production selection is unchanged.

Distribution follow-up: consumers should reference `actions/setup` in Faultline
at a reviewed full commit SHA. The action installs the exact engine into an
isolated runner environment and exposes its CLI/Python paths. The experimental
setup branch contains the same engine bytes as the validated baseline snapshot;
consumer repositories retain configuration and integration helpers, without a
vendored engine or wheel. The packaging migration passed in CI: the external
action installed successfully, restored the exact preceding baseline, reparsed
zero sources and carried both observations, matching both fresh native cases.

## 1. Compare evidence

Compare diff-only and enriched runs at the same revisions, inventory, policy, and model. Include ordinary code changes and dependency updates across text-based test frameworks. Record missing context, setup dependencies, inventory gaps, and agent costs.

Acceptance: every configured target is assessed, retained by explicit positive dependency evidence, or visibly unresolved. No candidate is silently excluded, and an empty suite cannot authorize skipping tests.

## 2. Check against outcomes

Freeze proposals and alternative policies before inspecting later CI outcomes. Import exact revisions and attempts; distinguish confirmed regressions, flakes, infrastructure problems, and unknown failures. Keep previously inspected tuning cases separate. Repeated attempts are not independent regression cases.

Acceptance: reproducible failing-change and failing-test recall with explicit denominators and uncertainty. Unexecuted tests are never counted as passing.

## 3. Measure value and cost

Collect test/job durations, setup overhead, selection latency, request counts, and tokens. Include retries, recovery, audits, and external agent costs where known. Use dated pricing; do not invent per-test costs from mixed batches.

Acceptance: compare detections and misses at equivalent measured execution cost. Keep relevance, regression recall, measured coverage, and savings separate. Smaller selections alone do not choose a winner.

## 4. Later: validate selective execution

Keep full CI execution during shadow adoption. The opt-in PHPUnit/Behat pilot now exports compact manifests, publishes before pushing, retrieves trusted decisions on PR events, and executes selected files. Optional agent hooks check readiness; absent or invalid publications run fully. Validate the supplied templates in a consumer before enabling them. Before making it a required CI policy, verify exact selectors, datasets, outlines, variants, prerequisites, stale decisions, and unsupported runners. Require maintainer opt-in, preserve post-merge full runs and a deterministic outcome-independent audit sample, and suspend selection after a confirmed missed regression.

Acceptance: incomplete or invalid decisions never authorize running zero tests. No automatic promotion or coverage-preservation guarantee.

## Later work

The [Vercel, Pest and Entire comparison](docs/dependencies.md#external-graph-approaches-reviewed-2026-10-30)
now records the public capabilities and their limits. Entire has a source graph;
an optional snapshot adapter and Gherkin/runtime-attribution contributions are
candidates for evaluation after the consumer baseline pilot. No provider has
been integrated and no upstream contribution has been published. Keep measured
preparation and CI outcomes separate from search benchmarks or inferred edges.

Benchmark optimizations against frozen evidence before adopting them: batching, shared trusted caches, incremental preparation, setup context, and windowing. Extend runner support, validate the new transport against the earlier SDK experiments, add CI comment publishing, versioned releases, and further result/coverage importers when the evidence supports them.
