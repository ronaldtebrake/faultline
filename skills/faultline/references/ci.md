# Selective CI pilot

The agent assesses the change. CI consumes a small file selection and makes no Jev calls. Use the [automatic PR handoff](handoff.md) or the explicit comparison pilot below; keep existing required checks running while comparing outcomes. Optional [agent hooks](hooks.md) prepare a decision before pushing.

## Agent: assess and export

Use the cumulative merge base and exact revision CI will execute. Faultline's automatic PR template tests the exact PR head; existing required merge checks remain in place. Refresh the assessment when its head, merge base, target or reviewed configuration changes.

```bash
faultline assess --evaluator noul-v1 --base <base> --head <tested-revision> --prepare
faultline assess --evaluator noul-v1 --base <base> --head <tested-revision> --max-cost 0.50
faultline export-selection --run <run-id> --threshold 0.50 --output .faultline/selection.json
```

Supply the same verified `--context` bundle to preparation and scoring when needed. `noul-v1` is opt-in: it uses the tested yes/no impact question, lossless evidence windows, reversible batching and up to four persistent HTTPS connections. It requires no extra Python packages. The independent `choice-v1` evaluator remains the default; its scores cannot be substituted for Noul scores.

Noul pins Jev 1.13.0. Pricing is $0.042/million input tokens, output free, verified 2026-10-01. Every dispatch reserves 65,536 input tokens against a shared dollar ceiling, including uncertain earlier attempts. The default is $0.50, 180 requests and 120 seconds of inference per invocation. Requests and dollar usage survive `assess --resume <run-id>`; explicit budget increases must fit the user's authorization. PR impact answers have no cross-run cache. The separately opted-in [surface relationship policy](dependencies.md#reusable-semantic-relationships) reuses stable memberships and shares the same run-wide spending limits. The standard-library HTTPS transport has no hidden retries. This is a different transport implementation from the earlier SDK experiment, so its latency must be measured independently.

## Manifest

```json
{
  "version": 1,
  "revision": "<exact Git revision>",
  "config": "<repository and execution configuration fingerprint>",
  "suites": {
    "unit": {"mode": "selected", "files": ["tests/CheckoutTest.php"]},
    "acceptance": {"mode": "none"}
  }
}
```

Suite IDs refer to `faultline.json`. `selected` lists whole files, `all` runs the full suite, and `none` explicitly proposes no files. Missing suites run fully. Thresholds, scores, source contents, credentials and explanations never enter this file. A separate local export receipt links its digest to the complete assessment. A digest detects identity differences; it is not an authentication signature.

Assessments with validated generated-test evidence export version 2. It adds
`generation`, shaped as suite ID → variant ID → original source path → sorted
declaration digests. Bindings cover selected and omitted generated sources so CI
can check the inputs behind the whole decision. Digests include the declared
tracked-input and external-artifact hashes; they contain no artifact contents.
Export uses the assessment's frozen bindings. It does not refresh them from
later local files. Version-1 decisions remain supported for other suites.

Export unions selected files across configured variants, includes mandatory rules and prerequisites, and widens a suite when evidence is unresolved. Unsupported runners stay `all` for now. New integrations can translate the same file-based format; generated test files need an explicit source-to-executable mapping.

## CI: validate and execute

```bash
faultline ci-plan --selection .faultline/selection.json
faultline ci-run --selection .faultline/selection.json --execute \
  --runners phpunit behat playwright --output .faultline/selected-execution.json
```

Without `--execute`, `ci-run` only previews. Use `--suite unit:default` to integrate one existing CI job; provide successful `--prerequisite <execution-receipt>` files when that job depends on another suite. Without a suite filter, prerequisites and variants run sequentially in dependency order. CI still owns containers, services, browser installation and parallel job scheduling.

Configure full runner commands as argument arrays, including existing tags, groups, configuration, and shard filters. Commands must accept native runner flags appended by Faultline; do not embed positional test paths in these commands. Run the helper in the prepared environment where runtimes, dependencies, configuration and output paths are available. Native integrations support PHPUnit 9.6, Behat 3.29 and Playwright 1.63/1.64; unsupported versions fall back to full execution.

PHPUnit receives a temporary configuration in the original configuration directory, preserving relative bootstrap/extension paths and other settings. Native discovery resolves file exclusions and `--testsuite` first. PHPUnit 9.6’s [test-list command](https://github.com/sebastianbergmann/phpunit/blob/9.6/src/TextUI/Command.php) ignores runtime name/group filters. Those filters, XML groups and repeat modes therefore retain the full configured shard unless a reviewed `discovery_command` bridge provides its exact filtered inventory. Behat invokes each selected feature separately with the original command and variant arguments, retaining its hooks and reset wrapper. If your CI resets the database outside Behat, include that existing reset in a reviewed runner wrapper that forwards all arguments and preserves status; Faultline does not invent an application reset command.

Every selected file retains applicable datasets/scenarios and configured variants. Native validation occurs only in CI, including for `none`; a failed inventory is not permission to skip. Missing/mismatched manifests, incomplete discovery, dependencies requiring wider execution, and unsupported filtering produce visible full-suite fallbacks. Dirty tracked checkouts are rejected. A selected run that fails to report expected native cases is incomplete, never a passing empty run.

Playwright uses a temporary config beside the original, preserving its relative paths, fixtures, reporters and project settings. A bundled reporter uses native file exclusion while Playwright owns setup, dependency and teardown projects. Full and filtered native inventories must agree on selected cases, including repeated tests. Shard/filter changes that move expected cases trigger full execution. CLI reporter overrides, interactive/stateful filters, `--no-deps`, remote path mappings and unsupported versions retain the full configured command. Runtime results validate native identities and preserve retries, flakes and expected failures. This adapter is tested with Playwright 1.63.0 and 1.64.1; it does not install browsers or services.

Gherkin-to-Playwright generators can supply the validated
[`faultline-source` declaration](dependencies.md#generated-gherkin-tests).
Selection then uses original feature paths while results retain native identities
and generated-code fingerprints. The same declaration lets runtime collectors
attribute observations to features. Failure source maps or plain descriptive
annotations alone do not establish that mapping or generation freshness.
Generated targets without a valid mapping retain full execution; native
setup/dependency/teardown projects are preserved even when their files are generated.
Artifact-dependent suites additionally require assessment bindings that exactly
match native discovery, even for `none`. Changed catalogs, missing bindings or a
different declaration set trigger full execution. Native generation stamps alone
cannot establish which inputs an earlier assessment considered.

Receipts and native artifacts record actual outcomes and validation/execution time. Compare a selected run with a full run of the same revision/configuration:

```bash
faultline ci-compare --selected .faultline/selected-execution.json \
  --full .faultline/full-execution.json
```

The comparison reports observed failures and elapsed differences. It does not classify flakes as regressions, infer results for omitted tests, or claim parallel CI wall-clock savings from serial durations.
Full runs must contain matched outcomes. Playwright receipts also bind the full
native inventory and code fingerprints, including when the selection is `none`.
Two generated builds at the same Git revision cannot be compared as though they
were the same test execution inputs.

## Manual comparison handoff

For the automatic publisher, `ci-fetch`, and failure handling, follow [CI setup](handoff.md). The commands below retain the explicitly triggered comparison flow.

The skill includes a [pilot workflow](../assets/faultline-pilot.yml). Copy it into the consumer's `.github/workflows/`, pin `FAULTLINE_REF` to a reviewed Faultline commit, and supply its reviewed setup script. For a private Faultline repository, provide a read-only `FAULTLINE_REPO_TOKEN`; no Jev key is needed in CI. Keep all consumer-specific setup in the consumer repository.

```bash
faultline ci-submit --selection .faultline/selection.json \
  --repository owner/project --workflow faultline-pilot.yml
```

Submission is an explicit external action using the user's authenticated `gh`. The helper dispatches only the consumer's default-branch workflow. It verifies the origin, sends only bounded manifest data, and compresses transport only when needed. The receiver enforces both compressed and expanded limits, then stores ordinary JSON. Oversized payloads are rejected without truncation.

The pilot runs selected and full PHPUnit, Behat and Playwright executions for comparison and uploads their evidence. It intentionally saves no CI minutes while both are running. It does not replace required PR checks. No threshold, including 50%, is established as safe merely because the integration works.
