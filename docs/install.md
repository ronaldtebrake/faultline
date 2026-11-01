# Install Faultline

You need Git and Python 3.10+. Faultline reads test source; setup and assessment do not start your application or run tests.

## With a coding agent

Install the skill once for your agent account. This keeps its bundled support
files out of consumer repositories. The skill installer needs Node.js/npm:

```bash
npx skills add https://github.com/ronaldtebrake/faultline --skill faultline --global
```

Select your agent and start a new session. The skill includes its Python engine: no separate pip install, database service, or second skill is needed. Private repositories require authenticated Git access.

The new installation/graph workflow is currently available on the experimental
`codex/graph-default` branch. To use its reviewed snapshot before it reaches
the default branch:

```sh
npx skills add https://github.com/ronaldtebrake/faultline/tree/e3ebb6fdd9c0166df1ba4558ef5349418778f406/skills/faultline --skill faultline --global
```

For the matching CLI dependency, append
`@e3ebb6fdd9c0166df1ba4558ef5349418778f406` to the Git package URL below.
This is a commit-pinned preview, not a new tagged release. Project-scoped skill
installation is also possible, but keep the installed engine ignored instead of
vendoring it into the application. Commit configuration and dependency pins.

Ask your agent:

> Set up Faultline for this repository. Review the actual test paths, variants and change scope, and validate the inventory without running tests.

The agent saves `faultline.json`. Review and commit it so teammates reuse the setup. Empty suites and unsupported test conventions need attention; filename suggestions are not proof of a complete inventory.

The default graph assessment needs no key. Run `faultline assess --base <merge-base>` and keep full CI running while validating its paths and unresolved tests.

Only for explicitly requested Jev scoring, add your key to the ignored `.faultline/.env` created during setup:

```dotenv
TYPESAFE_API_KEY="your-key"
```

The process environment takes precedence; root `.env` is the final fallback. This works in IDEs as well as terminals. Enter the key locally, never in chat or Git. Scoring sends selected change evidence and test source to Jev.

Then ask:

> Use Faultline to assess this PR. Start with the diff and collect only missing implementation evidence. Prepare offline, keep Jev spending below $0.90 including retries, and give me the HTML report with 10/25/50% comparisons. Do not run tests.

For this explicit paid request, the agent resolves the PR's original base and head, checks the work estimate, and invokes `assess --jev`. The result includes a shareable HTML file and a run ID for recovery. Context investigation remains agent work and is costed separately.

## Terminal or CI

The standalone CLI contains the same engine:

```bash
python3 -m venv ~/.venvs/faultline
~/.venvs/faultline/bin/pip install 'git+https://github.com/ronaldtebrake/faultline.git'
export PATH="$HOME/.venvs/faultline/bin:$PATH"
faultline setup
```

Review the suggested test paths, then configure them with `setup --source '<test-glob>' --scope '<source-glob>'`, or create multiple suites in `faultline.json`. Add the key as above and follow [the commands guide](commands.md). CI should pin installation to a reviewed commit.

GitHub Actions consumers can use the [setup action](../actions/setup/README.md)
at a full commit SHA instead of committing the engine or a wheel:

```yaml
- uses: actions/setup-python@v6
  with:
    python-version: '3.12'
- uses: ronaldtebrake/faultline/actions/setup@<reviewed-full-commit-sha>
- run: '"$FAULTLINE_CLI" graph build'
```

The action installs that exact source revision in a fresh runner-local virtual
environment. Use `"$FAULTLINE_PYTHON"` for helpers that import Faultline; the
consumer's default Python and dependencies remain unchanged.

For an unpublished dependency-collection pilot, use a reviewed wheel and a
requirements file that pins its SHA-256. Keep both files in the same directory,
create a fresh virtual environment, and install from that directory with
`python -m pip install --no-index --no-deps --require-hashes -r requirements.txt`.
Record the exact source snapshot as well as the wheel hash; a package version
alone cannot distinguish local builds. The CLI contains the Python engine and
its native analysis/runner helpers. Copy the separate Behat or Playwright
collector assets into the consumer as described in the
[dependency guide](../skills/faultline/references/dependencies.md).
Collection and graph preparation require no Jev key. Validate the installed
package with the actual consumer configuration before enabling collection in CI.

To see the report format without credentials or API calls:

```bash
faultline report --demo --output faultline-demo.html
```

Skill-only users can ask their agent to generate that demo. The HTML uses invented data.

## Optional agent push hooks

Enable [automatic PR selections](ci.md) first, then merge the matching [hook template](../skills/faultline/references/hooks.md) into your agent settings, preserving existing hooks. Review the hook trust prompt; nothing installs automatically. CI needs no Jev key.

## Updating and contributing

Rerun the skill installer to update; copied skills include a copy of the engine. For the CLI, repeat the pip command with `--upgrade`. For local development, use `pip install -e /path/to/faultline`; reinstall copied skills after changing their source. Native Codex and Claude plugin manifests point at the same bundled skill.

Contributors changing Jev questions, inputs or transport should also install the [TypeSafe guidance](https://github.com/typesafe-ai/skills):

```bash
npx skills add typesafe-ai/skills --skill typesafe-ai
```

Routine Faultline users do not need it. If TLS verification fails, repair Python's trust store or use an approved `SSL_CERT_FILE`/`SSL_CERT_DIR`; optional `certifi` is supported. Never disable verification.

The pinned `actions/graph` integration installs Faultline and owns baseline restoration, validation, would-run summaries and artifacts. Consumer repositories need only configuration and workflow wiring; no verification or metadata scripts. See [the workflow template](../skills/faultline/assets/faultline-graph.yml).
