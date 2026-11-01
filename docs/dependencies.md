# Dependency graph development

The goal is a persistent dependency baseline that avoids reassessing every test
on every PR, with particular attention to Behat and browser tests. Source analysis
and observations from existing full CI runs are both supported inputs.

The current milestone validates a shared CI baseline before graph-driven test
selection. Normal CI keeps full execution; the disposable consumer experiment
uses two fixed native cases against the full repository graph, as authorized by
the user. `graph baseline pack` packages fresh observations, job/run/attempt
provenance and immutable parser facts. `graph baseline restore` accepts an
explicitly trusted local artifact; `graph baseline fetch` authenticates a GitHub
push workflow and its explicitly trusted branch before restoring an ancestor.
Missing, expired, incompatible or rejected remote evidence reports a cold start.
No baseline command calls Jev, executes tests or authorizes an omission.

The bundle binds the repository, exact origin revision, configuration, analysis
limits, graph/parser versions and engine source fingerprint. The destination
rebuilds resolution against its own tree and revalidates runtime dependencies;
it never restores an old execution decision. Checksums detect corruption, while
GitHub producer checks establish the remote trust boundary. A failed full test
run may supply positive observations, but the report retains its conclusion and
missing observations remain unknown. Collection is never a coverage guarantee.

The temporary consumer pilot reports restored facts, parsed/reused sources,
carried/invalidated observations, source gaps and correspondence with fresh
observations. Validation of cache reuse and graph accuracy precedes any
decision to try selective execution. This is independent of the optional
assessment and selection features described below.

A controlled cold/warm CI pair now verifies authenticated cross-run restoration,
one-source reparsing and one carried versus one invalidated native observation.
The experiment caught and fixed missing PHP tokenizer loading under isolated
`php -n` on runners that package tokenizer as a shared extension. The warm
aggregation was slower overall despite parser reuse, so this establishes cache
correctness, not net CI savings. Full-suite artifact scale and dependency
completeness remain separate validation work. Private run reports stay with the
consumer; the [plan](../PLAN.md) records the milestone and remaining measurements.

Consumers can install the engine through the [shared setup action](../actions/setup/README.md)
at a full commit SHA instead of committing a package copy. The action uses an
isolated runner environment. Migration from the identical copied engine has also
passed CI restoration with zero reparsing and matching carried observations.

The first layer is available through `graph build`, `graph compare`, `graph
context`, `graph import` and opt-in Noul `assess --jev --dependencies`. See the
[bundled dependency guide](../skills/faultline/references/dependencies.md).

Implemented: exact Git snapshots, reusable blob parsing, PHP/type references,
Behat step links, JS/TS imports, re-resolution of new links, base-and-head
traversal, test-attributed Behat/Playwright observations, validated runtime imports,
and retaining known affected tests without Jev scores. Existing assessment resume,
reporting and CI export preserve the distinction between graph decisions and
model judgments. Runtime baselines now carry forward through unchanged dependency
boundaries, retain their original provenance and expose record-level invalidation.
Native Playwright 1.63/1.64 selection retains project setup/teardown, configured
fixtures and reporters, with exact case and retry accounting.
Generated suites can attach validated `faultline-source` declarations to map
native cases back to tracked features. The same declarations provide generation
inputs for runtime graph imports, with exact revision/file checks and separate
native-code fingerprints. Consumer generators must opt into this contract.
Downloaded catalogs and module lists can be bound separately as generation
artifacts. Their hashes are checked before native discovery, runtime import and
graph snapshot reuse at the current checkout, including changes at the same Git
revision. Historical artifacts are not assumed to match the local environment.
Assessment freezes generation evidence and exports declaration digests in a
version-2 execution manifest. CI requires the same declaration sets before
omitting generated tests; changed artifacts or missing bindings retain full runs.
An optional Behat event extension records native step/hook callables, their exact
source ranges, dispatched versus resolved-only steps, and suite/outline identity.
Imports verify range hashes against Git. These richer observations keep the
existing conservative file-level invalidation and configured setup guards.
Container collectors can declare runtime-to-repository directory mappings.
Mapped observations require exact full-file hashes, preventing a stale image
from passing import merely because its observed method ranges still match.

Graph preparation batches PHP tokenization and deduplicates repeated Gherkin
step matching within each tree. Blob facts remain independent of file location;
class and step resolution still repeats against the complete new tree. Stable
size-limit and non-regular-file gaps can reuse a snapshot, while missing tools
and read failures remain retryable. Snapshot identity includes analysis limits,
so changing a limit cannot silently reuse an earlier partial graph.

The optional `--dependency-catalog` policy now caches separate test-to-surface
Noul memberships. Body-only changes can reuse positive and negative facts;
test/setup, contract, namespace, declaration and candidate changes invalidate
them. The policy requires explicit declared boundaries and a separate retention
cutoff. Unknown ownership uses diff assessment, incomplete relationships remain
unresolved, and mandatory execution rules still apply. Runtime HTTP observations
can connect to declared surfaces without a model call.
Declared resource templates also connect parameterized paths, such as
`/orders/{id}`, to concrete Behat or Playwright observations. These matches only
retain tests; unmatched requests still require assessment.
Unparsed languages, templates and routing data retain their complete blob identity
in a surface boundary. Changing them invalidates reuse even if paths stay the same.
PHP fingerprints preserve declaration headers, route attributes, constants and
registration outside function bodies, while ordinary body edits can reuse them.
Native callable fingerprints alone are insufficient to narrow a context file:
an unchanged step can still depend on a changed helper or setup method.

A small approved real-source probe now demonstrates live membership reuse across
controlled implementation changes, zero additional Jev requests for cached
decisions, and matching fresh selection decisions. It also shows that new-graph
preparation can dominate inference time in a small case. The larger test in that
probe remained selected because its evidence exceeded the request limit. See the
[validation record](evaluation/dependency-baseline.md) for measured limits.

## Remaining goal

1. Consumer validation of boundary completeness, setup evidence and live Jev
   relationship judgments, especially browser actions reaching a separate server.
2. Sequential-change experiments comparing full assessment, dependency routing
   and focused Jev updates. Measure maintenance, preparation, inference and CI
   costs plus missed regressions. Later outcomes must stay out of inference.
   Private data belongs in the consumer's ignored workspace.
3. Adopt and validate the prepared consumer generator integration in CI. A
   private patch now embeds generation-time declarations without replacing
   Gherkin annotations or source maps. Local consumer generation and native
   discovery use controlled release artifacts; full application outcomes and
   actual release-input completeness remain unverified. Native synthetic
   checks now cover multiple features in one generated spec, projects, retries,
   ignored setup/teardown, stale declarations and baseline invalidation. Consumer
   suites without this mapping continue to retain full execution.
   Assessment-to-execution artifact bindings now pass native synthetic checks,
   including `none` decisions and catalog replacement after export. Consumer
   adoption still needs complete generation inputs and full-run observations.
   The prepared fixture integration also observes explicit browser/API request
   contexts, and its source-planner mode preserves existing generation commands.
   Native component checks pass with a synthetic endpoint and controlled planner
   outputs. A temporary draft consumer PR now stages and imports per-job evidence
   for the existing Behat install/update jobs and Playwright shards, using a
   hash-pinned experimental engine and committed variant configuration. Sampled
   native artifacts imported successfully at the expected CI revision and attempt;
   the broad run was stopped before completion. The dedicated two-case probe
   separately verifies shared baseline restoration and invalidation.
   A local wheel and checksum-pinned review bundle now pass installed-engine
   regression checks and the collection helper against a native synthetic
   fixture. The package remains unreleased and the consumer PR remains a
   disposable draft, with no merge or production adoption.
4. Validate the native Behat step/hook observations against consumer context
   configuration and use them to design narrower evidence and invalidation. A
   declared shared context directory currently connects every
   feature to every context file; this is conservative but can retain the whole
   suite for a single step change. Do not remove declared setup inputs merely to
   reduce the selected count or fit model input limits.
   Explicit Behat request events now distinguish remote operations in native
   scenario and hook observations. A consumer HTTP-client probe verified method
   and path attribution with synthetic responses; full application-server
   coverage and narrower omission decisions remain unverified.
   The final optional service wiring also passes a native enabled/disabled
   comparison with an in-process mock transport. Requests, cookies, results and
   failures match; disabled collection emits no events. Real transport and full
   consumer CI validation retain their separate scope.

The earlier graph comparison found broad false edges and missing dynamic paths.
Source/runtime links still supply positive evidence only. The separate surface
policy makes an explicit, experimental membership decision under a declared
ownership contract; it does not turn missing graph edges into proof of no impact.
The [validation record](evaluation/dependency-baseline.md) demonstrates synthetic
native selection and limited live cache reuse. It does not establish consumer CI
savings or held-out regression recall.

## External graph approaches reviewed, 2026-10-30

Recommendation: borrow task invalidation and consider an optional external source
graph, while keeping Faultline responsible for test observations, relationship
reuse and execution policy. This review does not install or integrate another
provider, adopt Turborepo, or establish consumer CI savings.

| Approach | Confirmed capability | Application to Faultline |
| --- | --- | --- |
| [Vercel CI](https://vercel.com/docs/ci) | Schedules affected Turborepo tasks, checks their cache and executes remaining tasks in dependency order. | Separate dependency preparation, relationship assessment and test execution into independently reusable work. |
| [Pest TIA](https://pestphp.com/docs/tia) | Records test/file dependencies with a coverage driver and can distribute a CI-recorded baseline. Its current guidance reserves ordinary TIA replay for local development and keeps normal CI tests running fully. | Collect observations during full runs and validate a baseline before reusing it. This is not evidence that selective CI preserves regression detection. |
| [Entire Graph](https://github.com/entireio/entire-graph) | Provides a source graph, change analysis and exports; [PHP and TypeScript have semantic parsing](https://github.com/entireio/entire-graph/blob/main/docs/language-support.md). | Evaluate it as an optional source of structural evidence alongside the native Behat and Playwright collectors. |

Turborepo distinguishes [package and task graphs](https://turborepo.dev/docs/core-concepts/package-and-task-graph).
Those task dependencies do not by themselves identify which Gherkin scenario
exercises a remote handler. Its [comparison controls](https://turborepo.dev/docs/guides/skipping-tasks#customizing-the-comparison)
use the branch merge base by default and permit explicit base/head revisions.
Its [cache fingerprints](https://turborepo.dev/docs/crafting-your-repository/caching)
include declared files, configuration and environment inputs; deterministic
outputs are an assumption. For Faultline, reuse analysis and membership facts
first. Replaying a browser test's previous pass would additionally need a complete
model of its server, data and environment.

Faultline already separates exact-blob parsing from graph snapshot reuse and
test-to-surface judgment reuse. The implementation re-resolves links for each
tree and binds relationship facts to their evidence and evaluator contract.
Do not copy Pest's comment normalization indiscriminately: Behat docblocks can
contain executable step and hook declarations. Their changes must remain visible.

Entire's [committed-tree cache](https://github.com/entireio/entire-graph/blob/main/docs/operations.md#cache)
binds provider identity, tree and graph-shaping options. Working-tree queries
bypass it; a changed tree selects another entry. This documentation establishes
snapshot reuse, not a measured cross-PR speedup or an incremental changed-file
parsing guarantee. Compare preparation cost before replacing Faultline's existing
blob cache.

An adapter could consume Entire's [native NDJSON snapshots](https://github.com/entireio/entire-graph/blob/main/docs/snapshot-format.md),
which already export files, symbols and relations. Validate repository, commit,
tree, supported schema and `identity_revision`; read profile metadata from the
header and completeness from the final summary. Preserve relation provenance:
`TESTS`, `HTTP_CALLS` and route associations are documented as inferred, including
when their targets resolve exactly. They are not executed coverage or calibrated
Jev probabilities. A missing or partial edge cannot authorize omission. Use the
full export for traversal; the interactive
[`impact` command](https://github.com/entireio/entire-graph/blob/main/docs/commands.md)
has a bounded caller depth and is not a complete test-selection contract.

A useful contribution candidate is stronger Gherkin/Behat step and hook linkage,
or an explicit interchange for test-attributed observations from multiple
runners. Keep inferred code relationships distinct from observed client requests
and from actual server coverage. First check the upstream implementation and
maintainer direction; the reviewed docs do not establish native scenario-level
runtime attribution. The repository is MIT-licensed and already has graph export,
so building another general export format is not the starting point. Any upstream
fixtures must be synthetic or properly anonymized. No upstream issue or PR has
been posted.
