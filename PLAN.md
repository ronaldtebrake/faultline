# Validation plan

Faultline can discover configured test source, accept verified context, obtain Jev judgments, recover incomplete scoring, and report proposals. The next goal is to establish whether those proposals retain useful regression detection at a worthwhile cost.

Longer-term validation goal: maintain a reusable dependency baseline that reduces
repeated Jev work, particularly for Behat and Playwright. Combine source analysis
with evidence from existing full CI runs. Track the implemented layer and remaining
requirements in [dependency graph development](docs/dependencies.md).

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

## Current milestone: validate shared CI baseline reuse

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
