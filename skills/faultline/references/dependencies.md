# Incremental dependency evidence

The current rollout milestone is shared baselines with full test execution.
Collect during existing full runs, package with `graph baseline pack`, and
restore a compatible ancestor using authenticated `graph baseline fetch`.
Keep collection and aggregation outside existing test gates. Report cache reuse,
invalidated observations, missing evidence and agreement with fresh full-run
observations. Do not enable selection as part of this milestone. These commands
make no Jev requests. See [installation and GitHub CI](install.md).

Opt-in Noul `--dependencies` retains tests reached by positive source/runtime
paths without a Jev question. Every other configured test stays eligible for
assessment. Missing edges never authorize omission. Dependency-selected tests
have no fabricated probability; reports label them separately.

An additional experimental surface policy can reuse semantic relationships,
including negative memberships, across PRs. It requires a reviewed catalog and an
explicit relationship cutoff. It does not infer complete application boundaries
from missing source/runtime links. See below before enabling it.

## Source snapshots and assessment

```bash
faultline graph build --revision HEAD
faultline graph affected --file src/price.ts --revision HEAD
faultline graph compare --base <cumulative-base> --head <tested-head>
faultline assess --jev --evaluator noul-v1 --dependencies \
  --base <cumulative-base> --head <tested-head> --prepare
```

Use the same assessment options without `--prepare`, with an authorized
`--max-cost`, to score unresolved tests. Resume uses frozen dependency decisions
and saved questions; omit `--dependencies` on resume.

Ignored `.faultline/dependency-graph/` stores immutable snapshots and source facts
cached by exact Git blob and adapter version. Resolution runs again against each
tree, so adding a definition or implementation can connect an unchanged consumer.
Selection consults base and head paths, including deleted dependencies. Dirty
working-tree source is never used in place of a requested Git revision.

Use `graph affected --file <path>` for a hypothetical change to an existing file.
Repeat `--file` for multiple literal repository-relative paths. The JSON lists
affected target IDs and one shortest dependency path per input and snapshot,
including edge kinds and the revision that supplied each explanation. It also
lists unresolved targets and unknown files. Missing paths do not prove safety.
Add `--base <older-revision>` to include old paths for deleted or disconnected
dependencies. New or uncommitted files need a new committed snapshot before their
contents can be resolved. Use `graph compare` to review the actual added/removed
edges and affected targets between two commits. `--output .faultline/impact.json`
saves a readable impact report; neither query calls Jev or executes tests.

JavaScript/TypeScript records relative imports, re-exports and literal
`require`/`import` calls. Aliases, dynamic imports and browser/server relationships
remain gaps. PHP uses `php -n` and `token_get_all` on text, without evaluating or
loading consumer code. It records class/type references. Behat links English
feature steps to literal or PCRE definitions. Without PHP, those gaps remain
visible. Context activation, Turnip parameters, transforms, hooks, localized
features and outlines may require native evidence. File-level links can retain
more tests than a method-level graph would.
PHP binding fingerprints also preserve declaration headers, attributes, docblocks,
constants and registration code outside function bodies. Ordinary method-body
edits can leave that fingerprint stable; changing a route attribute or method
signature cannot. Conditional named declarations inside functions remain tied to
the enclosing body. This is a conservative lexical check, not a complete PHP
call graph or proof of dynamic dependency boundaries.

## Behat collection in existing CI

Copy [FaultlineDependencyExtension.php](../assets/FaultlineDependencyExtension.php)
to a tools directory outside Behat's bootstrap directory. Register the file under
the existing Behat profile's `extensions` mapping, preserving its other settings:

```yaml
default:
  extensions:
    tools/FaultlineDependencyExtension.php: ~
```

Commit the integration, then bind the collector before the existing full test
command:

```bash
faultline graph context --suite acceptance:default \
  --output .faultline/behat-context.json
export FAULTLINE_DEPENDENCY_CONTEXT="$PWD/.faultline/behat-context.json"
export FAULTLINE_DEPENDENCY_OUTPUT="$PWD/.faultline/behat-observations"
# Run your existing full Behat command.
```

The extension observes Behat's native event results without adding test hooks or
replacing formatters. It records resolved steps, background steps, and the hooks
Behat actually dispatched at step, scenario, feature and suite boundaries. Native
filters decide which hooks apply. Native suite names and outline row lines keep
identities distinct. This integration is verified with Behat 3.29.0.

Each callable records its reflected symbol, source file, inclusive line range,
SHA-256 of those complete source lines, role and execution state. `called` means
Behat produced a call result, including failed attempts; it is not line coverage.
`resolved` identifies a defined step that was skipped, including dry runs. Import
checks field types, bounds, tracked source and exact range bytes against Git, then
adds callable files to the positive graph. Reflection supplies the symbol label;
the importer does not independently prove that a function executed.

Records are written after suite teardown so after-feature and after-suite hooks
are included. Setup/teardown failures retain failed observation status. Each
scenario writes a unique file, safe across separate worker processes. An
interrupted suite may produce no records. No coverage driver is required.
Helper calls, constructors, argument transforms and external browser/server
execution remain explicit gaps. Native callable evidence does not override
configured setup guards or authorize method-level omissions: carry-forward still
requires unchanged file dependencies and resolution.
Dynamic steps can share one PHP adapter closure even when they invoke different
remote operations. Its source range identifies the adapter, not the remote
implementation. Such integrations need explicit request observations or reviewed
operation mappings before the graph can distinguish their server dependencies.

### Explicit HTTP observations

A remote-operation adapter can dispatch `faultline.http_request` immediately
before its transport attempts a request. Its event must extend
`Behat\Testwork\Event\Event` so Behat's existing formatters accept it, and expose
public `getMethod(): string` and `getUrl(): string` methods. For example:

```php
final class HttpAttempted extends \Behat\Testwork\Event\Event {
    public function __construct(private string $method, private string $url) {}
    public function getMethod(): string { return $this->method; }
    public function getUrl(): string { return $this->url; }
}

$dispatcher->dispatch(new HttpAttempted($method, $url), 'faultline.http_request');
// Invoke the existing transport with its original arguments.
```

Inject Behat's `event_dispatcher` into the adapter only when the collector is
registered. The bundled extension's service ID is `faultline.dependencies`;
consumer extensions can check it during their `process()` phase, after all
extensions have loaded. This leaves clients without collection unchanged.

The collector retains only the uppercase method and URL path. It drops host,
credentials, query and fragment, and never reads headers or bodies. Malformed
events add a gap. Events during a scenario belong to that scenario; requests in
feature or suite setup/teardown apply to their enclosed scenarios. Events outside
an active suite are ignored. Failed transport attempts remain observations, and
dry runs emit none unless another integration explicitly dispatches them. Neither
an observed request nor a successful response proves which server source ran.

### Container paths and source verification

When CI runs Behat in a container, declare how its source directory maps to Git.
For an application subtree baked into an image at `/app`:

```bash
faultline graph context --suite acceptance:default \
  --mount /app=applications/web \
  --output .faultline/behat-container-context.json
```

Use `/workspace=.` for a whole-repository mount. Multiple `--mount` values are
allowed, but runtime roots must not overlap each other or the host checkout.
Repository prefixes must name tracked directories. Mapping does not require the
container path to exist on the host.

Mount the context JSON read-only, the extension PHP file read-only outside Behat's
bootstrap directory, and an empty observation directory writable by the container
user. Set `FAULTLINE_DEPENDENCY_CONTEXT` and `FAULTLINE_DEPENDENCY_OUTPUT` to their
container paths. Keep the existing database, browser, archive and other mounts.
The existing Behat command, feature filters, tags and formatters still apply.

The extension also supports registration through Behat's `BEHAT_PARAMS` JSON:

```json
{"extensions":{"/faultline/FaultlineDependencyExtension.php":{}}}
```

Merge this entry into existing parameters instead of replacing them. Do not
register the same extension twice. Native checks verify that environment-based
registration preserves suites from the existing configuration file.

Every mapped record must include SHA-256 hashes of the full feature file and all
observed repository files, including files containing dispatched hooks. Import
compares these bytes with the bound Git snapshot. A matching method range cannot
hide stale surrounding source in a container image. Collection also checks that
those files stayed unchanged during the suite. This verifies observed files;
unobserved helpers and external application servers remain gaps.

Create separate contexts for configured suite variants such as install/update
or different release environments. Use unique output directories and artifact
names for each matrix job and attempt, and upload observations on successful runs
as well as failed runs. Import each artifact with its matching context and exact
revision. Empty, interrupted or partial collection is never proof that a test is
unaffected. Collection and import do not call Jev or change test selection.

For existing integrations that need Xdebug file coverage, the simpler
[FaultlineDependencyContext.php](../assets/FaultlineDependencyContext.php) remains
available. Add it to the bootstrap directory and suite's contexts. It records
resolved definition files from scenario hooks, and optional
`FAULTLINE_DEPENDENCY_COVERAGE=1` adds executed PHP files when another collector
does not own coverage. Its own hook position limits setup/teardown visibility.
Use one collector per run. The event extension does not currently collect Xdebug
coverage. Neither collector covers a separate application server.

## Playwright collection in existing CI

Copy [playwright-dependencies.mjs](../assets/playwright-dependencies.mjs), its
[TypeScript declaration](../assets/playwright-dependencies.d.mts), and
[playwright_source.mjs](../scripts/faultline/tia/playwright_source.mjs) into the
same project directory and wrap its existing fixture:

```javascript
import { test as existingTest } from './existing-fixtures';
import { withFaultline } from './playwright-dependencies.mjs';
export const test = withFaultline(existingTest);
```

Tests must import the wrapped fixture. Bind `graph context --suite browser:default`
and set the two environment variables as above before the existing full Playwright
command. No browser is initialized just for API-only tests. Requests on the
supplied browser context are attributed to the current test; records retain
project/test identities and retries in separate files.

Only HTTP method and path are stored: credentials, host, query strings, headers
and bodies are excluded. Requests may be mocked and do not prove server-side
execution. Custom contexts, worker setup and standalone API request contexts need
explicit instrumentation. A test can call `faultlineDependencies.file(path)` or
`faultlineDependencies.request(method, absoluteUrl)` for additional observations.

For clients that use an `APIRequestContext`, explicitly wrap the instance passed
to that client. This also covers `context.request`, whose API calls do not emit
browser page request events:

```javascript
const observed = faultlineDependencies.requestContext(context.request, baseURL);
const client = new ExistingApiClient(observed);
```

The wrapper observes `fetch`, `get`, `post`, `put`, `patch`, `delete` and `head`.
Pass the context's actual `baseURL` to resolve relative paths for attribution;
request arguments and native URL resolution remain unchanged. Cookies, return
values, errors and disposal use the original context. Other methods keep their
native receiver. An attribution error records a gap and preserves the native
call. Failed request attempts are positive observations too, not proof that a
server handled them. With collection disabled, the original instance is returned.

### Generated Gherkin tests

A generator can attach a `faultline-source` annotation to each native test. The
annotation identifies one original tracked feature and fingerprints its declared
generation inputs. Failure source maps and other annotations remain untouched.
Use the same source helper in the generator:

```javascript
import { sourceAnnotation } from './playwright_source.mjs';

// Run this while generating the spec, with the exact clean Git revision.
const annotation = sourceAnnotation({
  root: repositoryRoot,
  revision: generationRevision,
  source: 'features/checkout.feature',
  inputs: [
    'tools/generate.mjs',
    'tests/fixtures.mjs',
    'steps/checkout.ts',
    'config/test-operations.json',
    'playwright.config.mjs',
  ],
  // Optional downloaded or locally generated inputs, staged inside the repo.
  artifacts: ['.artifacts/standard/enabled-modules.json', '.artifacts/standard/catalog.json'],
});

// Embed the literal. Do not recompute the stamp when loading a stale spec.
const declaration = `test('checkout', { annotation: ${JSON.stringify(annotation)} }, async ({ page }) => { /* generated steps */ });`;
```

All paths are canonical repository-relative paths. The helper adds the feature
itself, hashes exact file bytes with SHA-256, and records the exact Git revision.
Inputs must be tracked regular files. Include the generator, fixture/setup code,
resolved step implementations and tracked catalog/registration sources used for
the selected release. The generator remains responsible for declaring those
inputs and matching its release catalog/environment; the stamp does not prove
that the declaration is complete. Untracked build artifacts are not graph nodes.

The optional `artifacts` list creates a version-2 declaration. Each artifact is
an untracked regular file inside the repository, named separately from tracked
source. Discovery and runtime import verify its SHA-256 against the current file.
Missing files, symlinks, path escapes, overlapping input names and artifacts
larger than 16 MiB are rejected. There are at most 512 tracked and artifact inputs
combined; declaration size stays bounded at 128 KiB. Version-1 declarations
without artifacts remain supported. Keep large site archives outside this
generation-input contract and retain the existing setup guards.

Before reusing a graph snapshot at the checked-out revision, Faultline rechecks
its declared artifacts. An unchanged Git commit cannot hide a changed release
catalog. Matching artifacts and unchanged source boundaries allow observation
carry-forward; missing or changed artifacts invalidate the relevant records.
Historical observations remain evidence of their original revision and declared
artifact hashes. Carry-forward to a historical destination that is not checked
out requires fresh evidence; local artifacts cannot establish that environment.

With `assess --jev --dependencies --runtime <baseline>`, validated generation inputs
become frozen assessment evidence. Targets needing inference include the complete
declared source and artifact text; missing, binary or oversized evidence retains
the target without a model request. Generation evidence is bounded at 96,000
bytes, with the existing smaller question/request limits still enforced.

Export writes a version-2 execution manifest when the assessment contains
generation bindings. It carries declaration digests by suite, variant and
original feature, including omitted features; source and artifact contents stay
in the local assessment. Export and resume preserve the original digests rather
than adopting files changed afterward. `ci-run` requires native discovery to
produce exactly those declarations before accepting either `selected` or `none`.
Changed artifacts, missing declarations and additional declarations retain full
execution. An older version-1 manifest cannot authorize omissions for an
artifact-dependent suite. Source-only generated suites keep their established
selection path when no assessment binding is present.

The native runner validates the declaration against the current revision and
tracked source before selecting original feature paths. One generated spec may
contain several features; projects, repeated cases and retries keep their native
identities. Generated setup/dependency/teardown projects remain under Playwright's
control. Native code fingerprints must agree between discovery and execution.
Missing mappings for generated targets, ambiguous declarations, stale revisions,
changed inputs and unsupported mappings retain full execution. Changed native
code after discovery cannot be reported as a successful selected run.

With runtime collection enabled, the same mapping attributes each observation to
its original feature. Import independently checks generation inputs against Git
and adds their declared file dependencies to the positive graph. These inputs
remain distinct from observed server coverage. A later input change invalidates
the affected baseline records; unchanged records can carry forward. No model
calls or additional application runs are required to collect this evidence during
an existing full run.

## Validate and reuse

Import records while the tracked checkout remains unchanged. Supply `--input`
once per file; a JSON array of records is also accepted:

```bash
faultline graph import --context .faultline/behat-context.json \
  --input .faultline/behat-observations/<record>.json \
  --output .faultline/behat-runtime.json
faultline graph build --revision HEAD --runtime .faultline/behat-runtime.json
```

Import verifies repository, revision, configuration, inventory and tracked paths.
It does not claim that a partial run is complete or send outcomes to Jev. Keep the
validated runtime artifact with that revision's trusted CI artifacts. A later
assessment can reuse a baseline from the base or an available ancestor:

```bash
faultline assess --jev --evaluator noul-v1 --dependencies \
  --runtime <trusted-ancestor-runtime.json> \
  --base <cumulative-base> --head <tested-head> --prepare
```

The graph overlays observations whose test, configured setup, observed files and
known transitive dependencies remain unchanged. It resolves source links again;
new or removed bindings also invalidate a record. Each retained record preserves
the original revision and artifact identity, with `observed` or `carried`
freshness. `runtime_reuse.invalidated` explains discarded observations. These are
positive observations, not a claim that unobserved behavior is unchanged.
Sibling branches, missing ancestry and incompatible configurations are rejected.
Original CI artifacts remain immutable. Base-and-head traversal retains affected
tests even when the change itself invalidates their old observations.

Nothing automatically publishes artifacts or starts application/test processes
during graph operations. Selective CI exports support PHPUnit, Behat and
Playwright; see the [runner reference](ci.md) for supported versions and full-run
fallbacks.

## Reusable semantic relationships

A stable relationship such as “this scenario exercises checkout” can survive a
change inside checkout's implementation. A previous PR's impact score cannot be
reused for that purpose. The optional surface policy asks a separate Noul question
about membership and caches that exact judgment.

Binding fingerprints use PHP declarations/references and JavaScript/TypeScript
imports. Files without a binding parser, including ReScript, templates and routing
configuration, retain their full Git blob identity. A change to one of those owned
files uses diff assessment; it cannot reuse a negative membership just because
the filename stayed the same. Unchanged files can still participate in a cached
boundary. Relationship policy version 2 invalidates older membership caches and
requires a new assessment for an older frozen relationship plan.
Keep application route definitions, registration and other dynamic boundary
contracts in `contract_files`; source adapters do not infer all framework rules.

Commit a small application-surface catalog, for example `faultline-surfaces.json`:

```json
{
  "version": 1,
  "shared_inputs": ["config/global/**", "composer.lock", "package-lock.json"],
  "surfaces": [
    {
      "id": "checkout",
      "description": "Checkout page, basket totals and order submission exposed through GET and POST /checkout.",
      "inputs": ["src/Checkout/**", "templates/checkout/**"],
      "entrypoints": ["src/Checkout/Controller.php"],
      "contract_files": ["config/routes/checkout.yaml"],
      "resources": [
        {"method": "GET", "path": "/checkout"},
        {"method": "POST", "path": "/checkout"}
      ]
    }
  ]
}
```

`inputs` declares implementation ownership. It must include the behavior covered
by the description, including templates/data when applicable. Source traversal
expands those inputs through known dependencies. `entrypoints` adds roots;
`contract_files` supplies exact routing/interface evidence whose changes require
new judgments. `resources` can connect already observed HTTP method/path pairs
directly, avoiding inference. Resource matches are positive evidence even if a
request was mocked; absence never proves independence.

For parameterized routes, use an explicit `path_template` instead of `path`:

```json
{"method": "GET", "path_template": "/orders/{order_id}/items/{item_id}"}
```

Each `{name}` must occupy a whole segment and matches one nonempty path segment.
Names use ASCII letters, digits or underscores and cannot start with a digit.
The method must match (ignoring case); the path remains case-sensitive and keeps
its trailing slash. Matching does not decode percent escapes. Literals, including
regex characters, are exact. Optional segments, inline parameters and wildcards
are unsupported. Use `path` for an entirely literal path, including literal
braces. A resource must specify exactly one of the two fields.

A matching observation retains its test even if an older semantic judgment was
negative. Unmatched paths still require the normal relationship or diff
assessment; a non-match never permits omission. Changing a template changes the
catalog identity and prevents reuse of earlier memberships. Both Behat and
Playwright observations use this matching rule.

This declaration is a consumer-owned boundary contract. It is not a generated
proof that runtime behavior is confined to a directory. Include cross-cutting
bootstraps, hooks, registration, routing and global state in `shared_inputs` or
the appropriate contract/setup inputs. Changes to declared shared inputs retain
all tests. Keep suite `shared_inputs` and `description_inputs` accurate as well.
Incorrect ownership or incomplete setup can cause missed regressions; compare
against full existing CI before adopting omission decisions.

Inspect boundaries and the proposed work offline:

```bash
faultline graph build --catalog faultline-surfaces.json
faultline graph compare --base <base> --head <head> \
  --catalog faultline-surfaces.json
faultline assess --jev --evaluator noul-v1 --dependencies \
  --dependency-catalog faultline-surfaces.json --relationship-threshold 0.05 \
  --base <base> --head <head> --prepare
```

The cutoff above is an example, not a calibrated default. A surface membership
at or above the chosen cutoff retains the test. Omission requires valid answers
below that cutoff for **every affected surface**, plus complete declared ownership
of the changed files. Changes outside those boundaries, a changed catalog, or
changes to declarations, resolved bindings and contract files use the ordinary
cumulative-diff assessment. It sees both old and new behavior; head-only
membership cannot justify skipping a test of a removed route. The next ordinary
implementation change learns relationships for the updated boundary.
Missing/oversized relationship evidence retains
the affected test without truncation. Unanswered relationships remain unresolved;
export widens their suite. Existing mandatory rules and prerequisites still win.

Without `--prepare`, the same assessment uses its existing shared request, time
and dollar limits for relationship maintenance and any remaining diff questions.
It asks only about affected surfaces and their configured tests, not every
test–source-file combination. Known positive graph/resource paths need no Jev
questions. This remains opt-in; `--dependencies` alone retains its original
positive-path behavior.

The cache key includes the pinned model, question contract, repository/execution
configuration, test and setup source, surface description and contract source,
catalog namespace, resolved candidate paths, declarations and source edges.
Changed tests/setup, new candidates, changed bindings, catalog changes and adapter
versions invalidate the corresponding entries. Implementation-only changes can
reuse membership judgments when those inputs remain identical. The entire Git
tree is re-resolved, so new candidates do not have to appear in an old graph.

Facts live in ignored `.faultline/dependency-graph/relationships/`. Each retains
its original revision and exact inputs. The assessment freezes cache hits with
its plan; resume does not consult a newer cache. `--fresh` bypasses relationship
cache reads and writes for an independent comparison. Invalid cache entries are
visible misses, never substitute scores. No outcome/status evidence goes to Jev.

Reports separate relationship decisions from PR impact scores and show fresh and
reused pairs. The relationship cutoff is frozen independently of export's impact
cutoff. CI still consumes only the compact selected-file manifest. Keep the full
run comparison described in [selective CI](ci.md) while evaluating this policy.

## Verification

Synthetic tests cover cache reuse, added definitions, deleted dependencies,
revision/configuration checks, malformed observations, scenario outlines,
dependency-selected exports, native Behat attribution and native Playwright
fixture teardown/retries, project dependencies, expected failures, reporter
preservation, ancestor reuse, branch rejection and dependency invalidation.
Native tests use Behat 3.29.0 and Playwright Test 1.63.0/1.64.1.
These checks do not establish consumer regression recall or CI savings. No paid
Jev calls are required by the tests.

The sequential semantic pilot uses scripted provider answers and real Behat and
Playwright runners. A later implementation change reuses four membership facts
with zero new requests, selects one of two files per framework, and retains an
injected failure that also appears in the full runs. Playwright invokes a PHP
application process in this fixture; this is not a browser-coverage experiment.
