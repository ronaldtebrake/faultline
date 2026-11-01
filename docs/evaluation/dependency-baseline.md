# Dependency baseline validation

The implementation separates source/runtime dependencies, stable semantic
memberships and PR impact judgments. The last two use distinct questions and
policies. This record covers reproducible synthetic checks and anonymized live
measurements. Private source, payloads and individual judgments remain in the
consumer's ignored workspace.

## Verified synthetic sequence

`tests/test_dependency_semantics.py` creates a Git history with checkout and
profile application surfaces, two Behat features and two Playwright test files.
The first implementation change asks four test-to-checkout membership questions.
Scripted provider answers retain the checkout tests and omit the profile tests.
A later body-only change reuses all four facts, making zero new model requests.

The native pilot freezes that proposal before running tests. It injects a checkout
regression, executes selected and full runs in both Behat 3.29.0 and Playwright
1.64.1, and compares exact native identities. Each selected run executes one of
two files and catches the same failing test as its full run. Playwright tests
invoke a separate PHP application process; no browser is installed for the pilot.

Additional sequential cases verify:

- A changed test or its imported setup refreshes only the corresponding facts.
- A new catalog entry or an added owned source is discovered independently of old
  edges and invalidates the affected cache scope.
- Model and question changes cannot reuse earlier answers.
- Unparsed owned files, including ReScript, Twig and routing YAML, use full content
  fingerprints. A dependency change inside those files cannot reuse old negative
  memberships based on a stable filename.
- PHP declaration fingerprints distinguish ordinary body edits from changes to
  route attributes, docblocks, method signatures, constants and function imports.
  Nested named declarations remain tied to their enclosing body. Native PHP
  tokenization handles closures and interpolated-string braces without executing
  consumer source.
- Runtime HTTP observations retain matching surfaces without model inference.
- Unowned changes use the existing diff assessment; declared shared changes retain
  every test.
- Failed/partial inference cannot become an omission. Resume uses frozen inputs.
- Cache corruption becomes a visible miss. Oversized setup is retained without
  truncating relationship evidence.
- CI export keeps mandatory rules and distinguishes relationship decisions from
  impact probabilities.
- Batched PHP parsing preserves isolated namespaces and aliases without executing
  source; repeated Gherkin text is matched once per tree. Stable size-limit gaps
  reuse snapshots but still prevent semantic omissions. Changing analysis limits
  rebuilds bindings, and transient tokenizer failures are retried.

Generated-test checks create two original features in one ignored Playwright
spec, with two projects, repeated tests, retries and ignored setup/teardown files.
Feature selection retains only the requested feature's native cases plus native
prerequisites. Full-run collection imports twelve test-attributed records; changing
one feature's step implementation invalidates its eight records and carries the
other four. Stale revisions, changed declared inputs, ambiguous annotations and
untracked inputs cannot become valid discovery. A native-code change after
discovery cannot be reported as successful selected execution. This validates
the generator contract; it does not establish consumer input completeness.

Native Behat event collection now distinguishes five scenario instances across
two suites, including background steps and two outline rows per suite. The checks
verify native hook filters, all eight hook phases, suite-specific contexts,
failed steps, skipped definitions, dry runs, and setup/teardown failures. Callable
source ranges and hashes survive import into graph observations. An unrelated
change carries all five records; a hook-file change invalidates the three records
from the suite using that context and carries the other two. This deliberately
keeps file-level invalidation, even when only an unused method changed. It does
not establish method-level omission safety or consumer evidence completeness.

These are implementation tests with a controlled answer oracle. They do not
measure Jev's calibration, actual provider tokens/cost, real regression recall,
browser attribution coverage, or consumer CI savings.

Native container-path checks run the same Behat fixture from a separate physical
directory mapped to a monorepo subtree. They verify exact feature/context file
hashes, reject stale uncalled method bodies and feature text, preserve both native
suites when enabling the extension through `BEHAT_PARAMS`, and reject ambiguous
mounts or incomplete hashes. These are local native tests, not a consumer Docker
or CI run. Legacy unmapped evidence remains accepted with its existing limits.

Generated-input checks also cover downloaded release catalogs. A version-2
declaration distinguishes tracked source from locally staged artifact hashes.
Native discovery and runtime import reject a changed catalog even when generated
code and Git revision stay unchanged. Graph reuse checks artifacts before its
snapshot lookup: matching bytes allow an otherwise unchanged observation to
carry forward, while changed/missing bytes invalidate it. Original historical
observations preserve their provenance; a historical destination without verified
artifact state cannot inherit them. Native selection checks pass against both
Playwright 1.63.0 and 1.64.1.

## Private consumer generator integration, 2026-10-29

A reviewable patch in a private consumer checkout adds a generation-time metadata
callback and an opt-in source-binding wrapper. Existing Gherkin annotations and
failure source maps remain intact. Callback failure leaves existing generated
output untouched. The consumer's 165 generator tests, type check and targeted
lint passed; Faultline's full suite passed 265 tests, followed by the historical
artifact check in the graph suite.

Using five existing feature files, a checked-in trimmed release-catalog fixture
and a controlled module list, generation produced 158 cases. Native discovery
mapped those cases to their original features and retained the setup case.
Filtering to one original feature produced two cases plus setup. Changing the
catalog without regeneration failed discovery; restoring it restored discovery.
The declarations bind the generator package, release configuration, module
identity, original feature and the two external generation artifacts.
This filtering result is a native inventory check. Assessment-to-execution
bindings were validated separately in the synthetic sequence below; this private
consumer inventory check did not produce an assessment or authorize omissions.

This validates the consumer generator and selection interfaces with controlled
artifacts. It executes no application/browser test bodies, makes no Jev requests,
and does not measure CI savings or regression recall. The patch has not been
applied to the consumer's primary checkout or CI. Actual release-input
completeness and full-run outcomes still need validation.

## Generation evidence through CI execution, 2026-10-29

The assessment now freezes declared generation source and artifact contents,
while a version-2 execution manifest transports only their declaration digests.
Synthetic checks cover export, resume and trusted artifact retrieval. Changing
local artifacts after assessment cannot silently update the exported decision.
Missing, binary or oversized evidence retains the affected target without
inference. Native execution requires the complete declaration set from assessment.

An end-to-end native sequence collects full-run observations, assesses a later
change with a controlled answer oracle, and executes a selected feature while
preserving setup and retries. A `none` decision also validates successfully.
Replacing the catalog and regenerating tests at the same Git revision makes the
old decision fall back to full execution. Legacy decisions without artifact
bindings also retain full execution for artifact-dependent suites.

A relationship-cache sequence reuses all four memberships for unchanged
generation inputs. After refreshing the baseline for one changed catalog, it
asks one new membership question and reuses three. These are synthetic provider
answers, not additional live Jev measurements. The full suite passed 272 tests in
177.319 seconds with native Behat 3.29.0 and Playwright 1.64.1. The new execution
sequence also passed separately on Playwright 1.63.0 in 17.757 seconds.

## Existing consumer CI report audit, 2026-10-29

Read-only inspection found that one successful workflow had skipped its Behat
and Playwright test jobs and published no test artifacts. Workflow success alone
therefore did not establish a full test run. A separate completed workflow
provided all twenty Playwright shard reports from Playwright 1.63.0. Their
declared and finished inventories matched: 179 executions, including repeated
setup, covered 160 distinct native test IDs. All passed, with no missing or
unexpected outcomes. The reports retained 158 Gherkin annotations across five
original feature files.

These existing reports can supply native outcome identities and source labels.
They contain no Faultline generation declarations or complete server dependency
observations. They cannot retroactively create a validated dependency baseline.
The inspection made no Jev requests and started no tests or CI jobs. Because no
graph proposal was frozen before inspecting these outcomes, this is an artifact
compatibility audit, not a held-out regression-recall result. Private artifacts
and exact run provenance remain in the consumer's ignored workspace.

## API clients and source-planner integration, 2026-10-29

The Playwright collector now offers explicit `requestContext` wrapping for
API clients, including clients using the browser context's request object.
Native tests on Playwright 1.63.0 and 1.64.1 verify all supported HTTP methods,
relative URL attribution, cookies, native receiver binding, return values,
errors and disposal. Failed attempts remain observations; unparseable attribution
adds a gap without replacing the native call. Records exclude hosts, query
strings, authorization headers, cookies and response bodies.

A private consumer patch wires this wrapper into both its browser and API
fixtures. Thirty-one existing runtime/client tests, type checking and targeted
lint passed. A separate native component probe invoked the actual API fixture
against a synthetic loopback endpoint and imported its method/path observation.
Site provisioning was disabled, container commands were replaced with failing
stubs, and no container or browser was launched.

The consumer's CI generator derives release plan inputs from source, whereas
the earlier local generator experiment supplied existing catalog artifacts.
The prepared wrapper now supports the source-planner path as well. A bounded
stub supplied controlled catalog/module bytes to both the original planner and
the binding wrapper. Both invoked the same two planning commands and produced
the same 159 native cases, projects and Gherkin labels across five features.
This verifies command and inventory preservation with those inputs; it does not
verify a real image, installed release, or full consumer run.

Faultline's full suite passed 273 tests in 197.821 seconds. No additional Jev
requests were made. The expanded consumer patch is local and reviewable; CI
collection, actual release-input completeness and regression recall remain
unverified. Native Behat inspection also confirms that remote operations can
share one adapter closure, so callable ranges alone cannot identify the remote
implementation. That path still needs explicit operation/request attribution.

## Behat request attribution and optional CI collection, 2026-10-29

The native Behat extension accepts explicit HTTP-attempt events from an adapter.
It attributes scenario requests locally and merges feature/suite setup and
teardown requests into their enclosed scenarios. Records retain method and path;
authority, credentials, query, fragment, headers and bodies are excluded.
Malformed events add an evidence gap. Attempts do not prove server execution.
Native tests cover five scenario instances across two suites, outline rows,
hook attribution, failed attempts and dry runs. All fourteen Behat collector
tests passed.

A private consumer component probe used its actual HTTP service definition with
Symfony HTTP Client 6.4.37 and synthetic loopback responses. It preserved one
passing and one deliberately failing scenario and imported request attribution,
including suite teardown. The final patch injects the dispatcher only when the
collector is registered. Both enabled and disabled service definitions compiled
with the expected injection in an offline check. The final enabled/disabled
transport comparison remains unverified because automatic approval review timed
out twice; the earlier successful transport probe preceded that opt-in wiring.
No consumer application, browser or container was launched.

A cumulative private workflow patch prepares, imports and uploads evidence from
existing Behat install/update jobs and Playwright shards. Collection defaults
off and does not select tests. The patch preserves job dependencies, matrices,
gates, Behat database-reset loops and native filters. Playwright retains its
existing full-shard command when preparation or bound generation fails. Only
the dedicated job evidence directory is uploaded. Activation requires a reviewed
pinned Faultline CLI and a committed configuration covering the actual variants;
a separate candidate configuration preserves the other suites and enumerates
six Behat install/update/release variants.

YAML parsing, thirteen shell syntax checks and PHP syntax checks passed. The
action helper prepared a real context and imported five native fixture records;
duplicate attempt directories, empty collections and failed generation were
rejected. Actionlint and remote Actions execution were not performed. These
checks do not validate a real container image or full consumer workflow.

The regression run passed 274 tests in 193.938 seconds. It excluded the unchanged
Playwright loopback API test, which requires socket permission and had passed on
both supported versions in the preceding validation. The new Behat tests are
included. No additional Jev calls were made, and the consumer's primary checkout
and CI policy remain unchanged. Full-run collection, boundary completeness and
held-out regression recall remain outstanding.

## Parameterized HTTP resources, 2026-10-29

The surface catalog now accepts explicit path templates, allowing an observed
request such as `/orders/123` to retain a test for the declared `/orders/{id}`
boundary. Each parameter consumes one nonempty segment. Method, literal path
characters and trailing slash must match; percent escapes remain encoded.
Literal resources keep exact matching. Unsupported template syntax is rejected.

A sequential synthetic check first caches negative memberships for a Behat
feature and a Playwright file. Importing their parameterized request observations
then retains both targets in the exported CI decision. The remaining two
memberships are reused, with zero new provider requests. Wrong methods, extra
segments and mismatched literals still require judgments. Template changes
invalidate the catalog namespace; malformed templates cannot reuse cached
answers. The provider in these checks is a deterministic test double.

An offline private check invoked the consumer's actual Behat path resolver on
its trimmed tracked API fixture: all 44 operation paths matched their declared
templates, including 27 parameterized paths. Inputs included slashes, query and
fragment markers, spaces and non-ASCII characters; the resolver encoded them
within path segments. No HTTP requests or application processes ran. This
establishes compatibility with that fixture, not complete release coverage.

The dependency, semantic and distribution checks passed 59 tests in 40.683
seconds, including the existing native Behat/Playwright selection sequence. A
subsequent malformed-catalog cache check and two distribution checks also passed.
These changes add positive routing evidence. They do not narrow configured shared
context inputs or establish that missing runtime paths are safe to omit.

## Installed CLI validation, 2026-10-29

A local review wheel now packages the current dependency implementation. Its
59 engine files match the source snapshot byte for byte, including the PHP and
JavaScript analysis/runner helpers. A fresh Python 3.12 environment installed it
without downloads using a SHA-256-pinned requirements file. The package remains
unpublished; its ordinary version string does not identify this uncommitted
source snapshot. The private build manifest records both source and wheel hashes.

The installed engine passed 280 tests in 148.840 seconds, with no skips. The one
unchanged Playwright loopback API check remains explicitly excluded because it
requires socket permission; it passed on both native versions in the preceding
validation. The test process verified that engine imports came from the installed
wheel, while repository fixtures supplied synthetic source and collector assets.

The private CI action helper also ran through the installed `faultline` entry
point. It prepared a context, collected five native Behat scenarios, imported all
five records and carried them across an unrelated implementation change. Offline
assessment then retained one feature through a parameterized HTTP resource and
left the unmatched feature requiring a membership judgment. No judgment was
requested, and the baseline remained explicitly incomplete.

The installed CLI also prepared contexts from the candidate consumer
configuration for six Behat install/update/release variants and one Playwright
feature suite. Each Behat context contained 536 feature sources with the declared
container mapping; the Playwright context contained five original feature
sources. These are configured source inventories, not executed scenario counts.
The candidate configuration was loaded only in the private integration checkout
and the previous private configuration was restored afterward.

The review bundle pairs the pinned wheel with the cumulative consumer patch and
candidate suite configuration. It does not publish or enable collection. These
installed-package checks do not establish a real consumer application, container
or remote workflow run; full CI observations and boundary validation remain due.

## Refreshed consumer preparation, 2026-10-30

The consumer default branch was refreshed through authenticated HTTPS Git after
the REST API remained rate-limited. The pilot patch applied cleanly: none of the
74 upstream changed files overlapped its 15 files. All pilot file blobs match the
earlier integration, and the relevant locked Behat and HTTP-client versions are
unchanged. A separate private checkout preserves the earlier validation state.

The installed CLI regenerated all seven collection contexts against the new
candidate revision, with the same nonempty configured source inventories and
container mappings. This replaces stale revision bindings for the prepared
candidate; it does not imply any tests ran at that revision.

Actionlint 1.7.12 was built with normal Go module checksum verification and run
locally on both the current base and candidate workflows. Both passed with the
existing self-hosted runner label declared in a private linter configuration.
No diagnostics were filtered. ShellCheck and Pyflakes integration were disabled
because those executables were unavailable; earlier Bash syntax and helper
execution checks retain their separate scope. No private workflow source was
uploaded for linting. Publication, full consumer CI collection and the final
enabled/disabled HTTP comparison remain pending.

An independent offline import audit also checked the generation wrapper, runtime
fixture and Playwright configuration at the refreshed candidate revision. It
followed 78 local ES module import edges through 44 source files; every file was
among the wrapper's 119 declared package inputs. External package imports were
present in the package manifest, and both manifest and lockfile were bound. The
audit stripped TypeScript types and parsed module syntax without executing any
consumer module. It found no unresolved local or nonliteral dynamic imports in
that closure. This checks the runtime module inputs, not every filesystem or
environment read. The separately hashed planner outputs still need comparison
with real release artifacts; container, site archive and server dependency
completeness remain unverified. No additional tests or provider calls ran.

## Optional Behat integration with mock transport, 2026-10-30

A private native comparison now exercises the final optional service wiring with
Symfony's in-process `MockHttpClient`. The consumer HTTP executor and service
extension are byte-identical to the prepared candidate. A fixture-only alias
replaces the static HTTP factory; the executor itself is unchanged. PHP socket
and cURL entry points and URL stream access are disabled. No server is started.

Both collection modes ran two scenarios, with one expected pass and one expected
failure. Request methods, URLs, headers and bodies were identical, as were return
values, captured cookies and the failure message. The enabled mode emitted four
events and imported two scenario records, including suite teardown attribution;
the disabled mode emitted no events or records. Collected records contained none
of the synthetic query, body, user, cookie or host markers. The imported baseline
remained incomplete and retained its server/helper dependency gaps.

This used the consumer's installed Behat 3.29.0, HTTP Client 6.4.37 and HTTP Client
Contracts 3.7.1. The final comparison took 0.361 seconds, excluding fixture
preparation, and made no network or Jev requests. It verifies optional integration
behavior with a mock transport. It does not replace the pending real loopback
comparison or full consumer CI validation. The earlier loopback script is no
longer present in temporary storage; its fixture and prior results remain in the
private workspace.

## Measurements for the consumer pilot

Use a reviewed surface catalog, the same pinned evaluator, exact cumulative base
and head revisions, and a sequence of held-out PRs. Freeze each prediction before
inspecting full-run outcomes. Keep all private sources and reports in that
consumer's ignored `.faultline/` workspace.

Compare fresh diff assessment, positive graph routing and cached surface routing.
For each snapshot, record graph parsing/reuse and time, relationship preparation
time, fresh/cached pairs, provider requests/usage including retries, total
preparation-to-report latency, native validation/execution time, selected cases,
and failures seen only in the full run. Keep infrastructure failures, flakes and
regressions separate after review. A lower test count does not establish quality.

The engine now records dependency and relationship preparation time separately
inside the overall source phase. Inference timing is the combined dispatcher
duration; it is not per-test latency. CI receipts record validation and execution
durations. Serial duration differences do not establish parallel CI wall time.

Use `--fresh` to compare uncached membership judgments with reused ones. Preserve
all original catalog versions and fact provenance. Test route/registration changes,
shared hooks, dynamic bindings, new endpoints, test changes, deleted files,
cross-surface dependencies and ordinary implementation changes. Calibrate the
separate relationship cutoff on development cases, then assess held-out outcomes.

An offline consumer inspection now compares graph preparation on adjacent commits
and an unchanged revision. The optimization preserved graph edges, bindings,
targets and affected-test decisions in that comparison. Its timing evidence stays
in the consumer's ignored workspace. This is a preparation measurement, not a
held-out model-quality or CI-savings experiment. Existing partial historical
outcome records cannot supply a complete regression-recall denominator.

Preparation exposed broad shared Behat setup edges that retain the whole suite
on a context-file change. Native step/hook observations must be validated before
using them to reduce that fallback. Held-out PR/full-run history also remains to
be selected. GitHub access recovered after the earlier rate limit. Both QA runs
at the inspected consumer head were cancelled. The separate artifact audit above
establishes the availability of native Playwright outcomes, while dependency
collection still needs adoption in existing full CI runs.

## Approved live source probe, 2026-10-29

A small experiment used a private augmented Git history with controlled edits to
real implementation source. It preserved one suite's existing shared inputs and
compared first-time membership scoring, reuse on a later body change, and fresh
scoring. One test's complete evidence fit the request limit; the larger test
remained retained without inference. The user approved the two frozen payloads
and a shared maximum of eight attempts, below $0.023. Only four attempts were
needed, all successful: 31,888 input tokens, costing $0.001339296 at the verified
Jev 1.13 price of $0.042/M input tokens. There were no unknown-usage attempts.

| Assessment | New requests | Cached pairs | Assessment invocation, including report |
| --- | ---: | ---: | ---: |
| First assessment, graphs already prepared | 2 | 0 | 2.446 s |
| Later body change, new graph | 0 | 2 | 4.581 s |
| Same later change, warm graph | 0 | 2 | 1.945 s |
| Fresh judgments on that change, warm graph | 2 | 0 | 2.190 s |

Reused probabilities matched their original saved facts exactly. Fresh scoring
returned the same selection decisions, with a small change in one probability.
An additional change confined to the unrelated surface reused one negative fact
with zero requests and exported a proposal containing one of the two test files.
The larger test remained selected because its evidence exceeded the limit. No
consumer test or application process ran, and no consumer CI policy was changed.

These are single observations from a small development case, not a calibrated
cutoff or regression-recall result. The cost and request savings are measured;
general latency savings are unproven. In particular, preparing a new graph took
longer than the inference it replaced in this small case. The table excludes
earlier source investigation, repository preparation and offline preflight, so it
is not total task or CI latency. Full payloads, provenance, receipts and the
closed spending ledger remain in the consumer's ignored experiment directory.
