# Install and set up Faultline

You need Git and Python 3.10+. Analysis does not require application dependencies or test runners.

## 1. Install the skill or CLI

For a coding agent, run this in the repository you want to analyze. The installer also needs Node.js/npm:

```bash
npx skills add https://github.com/ronaldtebrake/faultline --skill faultline
```

Choose your agent, then start a new session. If the repository is private, Git must be authenticated with an account that has access.

For agents working on Jev inputs, scoring, or performance, also install the recommended [TypeSafe companion skill](https://github.com/typesafe-ai/skills):

```bash
npx skills add typesafe-ai/skills --skill typesafe-ai
```

Select the same agent and start a new session after installation. Faultline's instructions use this guidance when relevant. The CLI and CI do not require the companion skill.

For terminal or CI use, install the standalone CLI:

```bash
python3 -m venv ~/.venvs/faultline
~/.venvs/faultline/bin/pip install 'git+https://github.com/ronaldtebrake/faultline.git'
export PATH="$HOME/.venvs/faultline/bin:$PATH"
faultline --version
```

Both contain the same engine. If you installed only the skill, your agent invokes `python3 "<installed-skill>/scripts/run.py"` instead of `faultline` in the commands below.

## 2. Configure the project

Ask your agent:

> Set up Faultline with this repository’s actual test paths, change scope, variants, and must-run rules. Validate the inventory without calling Jev, starting the application, or running tests.

Or create `faultline.json` yourself. Adapt this example to suites that actually exist:

```json
{
  "schema_version": 2,
  "scope": ["src/**", "config/**"],
  "suites": [
    {"id": "unit", "sources": ["tests/**/*.test.ts"]},
    {"id": "acceptance", "sources": ["features/**/*.feature"]}
  ]
}
```

```bash
faultline init
faultline discover --revision HEAD
```

Check the listed files, then commit `faultline.json` to share the setup. Empty suites remain incomplete. See the [configuration reference](../skills/faultline/references/workflow.md) for shared inputs, required tests, and variants.

## 3. Add your Jev key

Create `.faultline/.env` in the project:

```dotenv
TYPESAFE_API_KEY="your-key"
```

`init` keeps `.faultline/` ignored. Faultline reads the key in terminals and IDEs. The process environment takes precedence; root `.env` is the final fallback. Keep keys out of Git and chat. Live scoring sends selected change context and test source to Jev.

## 4. Benchmark a PR

Ask your agent to benchmark the PR from its diff, gather only missing implementation evidence, and stay within your spending budget. It can analyze an open or closed PR without switching your branch.

For CLI use, follow [the commands guide](commands.md). You need the cumulative diff base and exact tested head locally. Prepare first, inspect the work estimate, then score. The CLI accepts an agent-prepared context bundle; without one, it scores the diff and test source alone.

## Updates and local development

Rerun the skill installer to update. For the CLI, repeat the pip command with `--upgrade`. Pin CI installations to a reviewed commit.

To use a local Faultline checkout:

```bash
npx skills add /path/to/faultline --skill faultline
# Or, for the CLI:
~/.venvs/faultline/bin/pip install -e /path/to/faultline
```

Reinstall copied skills after source changes. Editable CLI installs read that checkout directly.

If TLS verification fails, repair the active Python environment’s trust store. Optional `certifi` or approved `SSL_CERT_FILE`/`SSL_CERT_DIR` settings can provide trusted certificates. Do not disable verification.
