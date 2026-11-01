# Shared dependency baselines: full execution first

For the current baseline-validation milestone, leave all existing test commands
and merge gates in place. Add collection beside full runs and aggregation after
them, outside their dependency/gate paths. Do not use a selection manifest for
this milestone.

For first-time installation, use the skill's [installation workflow](../skills/faultline/references/install.md)
and [source graph template](../skills/faultline/assets/faultline-graph.yml). It uses
the commit-pinned `actions/graph` action, which installs Faultline, restores source facts, writes a would-run job summary, and publishes source parser facts on default-branch
pushes and reports PR impact without changing existing test jobs. This initial
template contains no runtime observations; extend collection alongside existing
full runs when needed. The package and JSON CLI are the integration boundary. Consumers need configuration and CI wiring, with no Python verification, producer-metadata or report-copy helpers. `actions/setup` remains available for installation alone.

`faultline.json` describes the scope and test suites; it is not the baseline.
The report artifact's `graph.json` contains a node for every tracked file, known
dependency edges and configured test targets. Nodes alone do not establish
complete dependency coverage. The separate `baseline.json` artifact carries
reusable parser facts from a trusted ancestor. A descendant reuses unchanged
facts, parses changed or added sources, and resolves a fresh graph for its tree.
New tests matching the configured source patterns are discovered automatically.

For controlled experiments, the optional action `expectations` JSON can assert
`exact_affected` source paths, configured `unresolved` controls, and
`unchanged_tests: {"revision": "<full commit SHA>", "sources": ["tests/ExistingTest.php"]}`.
The last check compares Git blobs with the pinned revision, so changing the test
cannot masquerade as retaining an existing test through a dependency path.
The package checks these controls and writes their result into the job summary
and artifact. An unresolved control still runs in full CI; it is not permission
to skip it. When comparing a stack, the incremental prediction appears first,
with the cumulative integration diff below it.

`faultline graph baseline pack --producer producer.json --runtime runtime.json
--output baseline.json` creates a portable bundle containing parser facts and
validated observations. Producer metadata names the GitHub repository and numeric
repository ID, workflow filename, push branch, exact revision, run ID, attempt
and each collection's job/shard key and runtime integrity hash. Use fresh
observations from that revision; carried records retain their old provenance.

Upload only `baseline.json` in an artifact named `faultline-baseline-v1`.
Restore on a later checkout with full Git history:

```sh
faultline graph baseline fetch --repository owner/repository \
  --workflow qualitychecks.yml --branch main \
  --output .faultline/downloaded-baseline.json
```

The authenticated lookup accepts only a completed push run from the named
repository, workflow and branch, with an available ancestor revision. It checks
artifact expiry, archive digest, member names, size limits, producer run/attempt,
configuration and engine identity. A rejected/missing baseline returns
`restored: false`; continue cold analysis and the full suite. A failed test run
may contain useful positive evidence; its conclusion is retained, and coverage
always remains incomplete. A temporary pilot branch must be explicitly selected
and must not become a production trust source accidentally.

The returned `runtime_paths` can feed `graph build --runtime ...` for carry and
invalidation measurements. Compare those observations with freshly imported
records after the full tests. Missing fresh observations are unknown, not
agreement. Parser facts are portable; graph resolution is rebuilt on the new
tree. Generated external inputs must be independently restored and hash-checked
from the current run before measuring reuse.

Local `graph baseline restore --input baseline.json` assumes the caller already
trusts the producer. A checksum alone does not authenticate a producer. Never
restore arbitrary PR-uploaded evidence as a trusted production baseline.

## Optional selective execution experiment

The following is separate from graph validation and requires explicit adoption.

# Prepare before pushing; execute in CI

The agent assesses the cumulative PR diff and publishes a compact decision before pushing. The automatic PR job retrieves it once, then runs selected PHPUnit, Behat or Playwright files or falls back fully. CI has no Jev key and never waits for scoring.

```bash
faultline ci-submit --run <run-id> --threshold 0.50 \
  --target-branch main --repository owner/project
# Without a completed assessment, explicitly publish full execution:
faultline ci-submit --full --head HEAD --target-branch main \
  --repository owner/project --reason 'Assessment unavailable'
```

Wait for `published: true`, then push in a separate tool call. Publication waits at most two minutes; missing/invalid publications make CI run fully. Explicit `none` still requires setup and native validation. Broken setup and runner failures remain failures.

Start with the [README's synthetic configuration](../README.md#optional-github-ci), then follow the [complete setup and handoff guide](../skills/faultline/references/handoff.md). It explains permissions, target branches, artifact trust, time limits and recovery.

- [Publisher template](../skills/faultline/assets/faultline-publish.yml): reviewed default-branch workflow; only publishes data.
- [Automatic PR template](../skills/faultline/assets/faultline-pr.yml): exact-head checkout, one lookup, existing setup, `ci-run`.
- [Optional agent hooks](../skills/faultline/references/hooks.md): Cursor, Claude Code and Codex; preserve existing hooks during installation.
- [Manual comparison pilot](../skills/faultline/assets/faultline-pilot.yml): selected and full runs at the same revision.
- [Runner reference](../skills/faultline/references/ci.md): selectors, variants, prerequisites and execution receipts.

Keep existing required merge checks. The new job tests the exact PR head; its 50% cutoff remains experimental. Templates are shipped for review, never installed automatically.
