# Install the CLI and GitHub baseline workflow

Installation should leave a reviewed `faultline.json`, a runnable packaged CLI,
and optional CI observation alongside existing tests. It does not enable test
selection, spending, or push hooks. Respect any broader authorization already
given by the user; do not ask again for routine setup within that scope.

## Choose the installation

Inspect existing Faultline configuration, dependency management and GitHub
workflows first. Reuse an installed version if it supports the requested commands.
For CI, prefer `ronaldtebrake/faultline/actions/setup` at a reviewed full commit
SHA. GitHub retrieves the package from that commit and installs it under the
runner's temporary directory. It exports `FAULTLINE_CLI` and `FAULTLINE_PYTHON`.
Do not commit the Python engine, a wheel, or a private report to the consumer.

For a local dependency, use the project's existing Python tool/environment or
create a dedicated virtual environment, then install a commit-pinned package:

```sh
python3 -m venv .faultline/venv
.faultline/venv/bin/python -m pip install 'git+https://github.com/ronaldtebrake/faultline.git@<reviewed-full-commit-sha>'
.faultline/venv/bin/faultline --help
```

Ensure `.faultline/` is ignored. Keep the selected revision in the consumer's
dependency lock or CI workflow, so updating Faultline is an explicit dependency
update. Check the selected commit actually contains the setup action and commands;
do not assume an older published revision contains workspace-only features.
Python 3.10+ and Git are required. PHP is needed for PHP/Behat source links.
No application installation or model request is required for graph inspection.

## Configure and verify source inspection

Run `faultline setup` to inspect existing configuration or discover candidate test
paths. It intentionally returns incomplete when configuration is missing. Inspect
the real runner configuration before choosing globs, variants and shared inputs.
Use `setup --source '<glob>' --scope '<glob>'` for a simple suite or write multiple
reviewed suites using [configuration](workflow.md). Preserve existing settings.

Run `faultline init` and verify nonempty, complete source inventory. An empty suite
or unsupported convention needs correction, not an empty-success interpretation.
Run `faultline graph build --output .faultline/graph.json`, then query a known
dependency with `faultline graph affected --file <repo-relative-file>`. Inspect
the explanation and gaps using [dependencies](dependencies.md). Source snapshots
read committed Git objects: new files need a commit before their contents can be
indexed. An uncommitted configuration can be validated locally, but CI needs the
reviewed configuration committed. Do not commit unrelated user changes.

## Add GitHub CI without changing existing test execution

Use [the source graph workflow](../assets/faultline-graph.yml) as a starting point.
It is a source-only baseline: runtime collection is a separate optional extension.
Pin its setup action to the reviewed engine revision, keep the workflow filename
`faultline-graph.yml`, and integrate it beside the existing full test workflow.
It builds JSON reports on PRs and publishes parser baselines only on default-branch
pushes. The restore trust source is that repository's default branch. Preserve
existing required checks and runtime setup. Do not enable selective execution.

Use `contents: read` and `actions: read`, no Jev secret and no
`pull_request_target`. Retain full history for ancestor validation. Missing,
expired, incompatible or corrupt baseline evidence should produce a cold build;
it never authorizes omissions. Verify YAML and installation locally, then inspect
the first permitted CI run's report. A later descendant must show `restored: true`
and actual parser reuse before describing sharing as validated. A first PR without
a default-branch baseline is expected to be cold. Do not merge just to manufacture
that evidence; a user-authorized temporary branch can be used for a disposable
probe with explicit trust configuration.

When runtime observations are requested, use the [collector contracts](dependencies.md)
to bind existing Behat/Playwright runs to exact revision, suite, variant and attempt.
Generated tests need their original source and generation-input mapping. Preserve
full runs while comparing fresh and carried observations. Source-only reports do
not validate runtime coverage, and unknown paths do not establish independence.

Return the installed revision, configuration/workflow paths, inventory and query
results, and the actual CI state. Distinguish locally validated setup from a
completed live CI run. Explain gaps without inventing test savings or coverage.
