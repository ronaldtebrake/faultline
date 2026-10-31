# Install Faultline

You need Git and Python 3.10+. Faultline reads test source; setup and assessment do not start your application or run tests.

## With a coding agent

Run this in the repository you want to assess. The skill installer needs Node.js/npm:

```bash
npx skills add https://github.com/ronaldtebrake/faultline --skill faultline
```

Select your agent and start a new session. The skill includes its Python engine: no separate pip install, database service, or second skill is needed. Private repositories require authenticated Git access.

Ask your agent:

> Set up Faultline for this repository. Review the actual test paths, variants and change scope, and validate the inventory without running tests.

The agent saves `faultline.json`. Review and commit it so teammates reuse the setup. Empty suites and unsupported test conventions need attention; filename suggestions are not proof of a complete inventory.

Add your key to the ignored `.faultline/.env` created during setup:

```dotenv
TYPESAFE_API_KEY="your-key"
```

The process environment takes precedence; root `.env` is the final fallback. This works in IDEs as well as terminals. Enter the key locally, never in chat or Git. Scoring sends selected change evidence and test source to Jev.

Then ask:

> Use Faultline to assess this PR. Start with the diff and collect only missing implementation evidence. Prepare offline, keep Jev spending below $0.90 including retries, and give me the HTML report with 10/25/50% comparisons. Do not run tests.

The agent resolves the PR's original base and head, checks the work estimate, and invokes `assess`. The result includes a shareable HTML file and a run ID for recovery. Context investigation remains agent work and is costed separately.

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

To see the report format without credentials or API calls:

```bash
faultline report --demo --output faultline-demo.html
```

Skill-only users can ask their agent to generate that demo. The HTML uses invented data.

## Updating and contributing

Rerun the skill installer to update; copied skills include a copy of the engine. For the CLI, repeat the pip command with `--upgrade`. For local development, use `pip install -e /path/to/faultline`; reinstall copied skills after changing their source. Native Codex and Claude plugin manifests point at the same bundled skill.

Contributors changing Jev questions, inputs or transport should also install the [TypeSafe guidance](https://github.com/typesafe-ai/skills):

```bash
npx skills add typesafe-ai/skills --skill typesafe-ai
```

Routine Faultline users do not need it. If TLS verification fails, repair Python's trust store or use an approved `SSL_CERT_FILE`/`SSL_CERT_DIR`; optional `certifi` is supported. Never disable verification.
