# Install Faultline

## 1. Check the prerequisites

You need Python 3.10+, Git, Node.js/npm, and a coding agent that supports Agent Skills. Test runners and application dependencies are needed when you execute tests; they are not required for source analysis.

Faultline is currently private, so your GitHub account needs access to the repository through SSH.

## 2. Install CodeGraph

```bash
npm install -g @colbymchenry/codegraph@1.6.0
codegraph --version
```

The version should be `1.6.0`. Faultline uses this CLI directly; no CodeGraph agent or MCP setup is needed.

## 3. Install the Faultline skill

Run this from the repository you want to analyze:

```bash
npx skills add git@github.com:ronaldtebrake/faultline.git --skill faultline
```

Choose your coding agent when prompted, then start a new agent session in that repository.

To test unpublished changes, replace the Git URL with your local Faultline checkout:

```bash
npx skills add /path/to/faultline --skill faultline
```

Use one of these commands. The skill includes its Python scripts; no separate Python package installation is required.

## 4. Initialize your project

Ask your agent:

> Use Faultline to initialize this repository, configure its test source paths. Runner commands and reviewed descriptions are optional for analysis. Use source-only discovery. Do not call Jev, invoke test runners, or start the application yet.

Faultline stores suite configuration in `faultline.json` and reviewed test descriptions in `faultline/catalog/`. Share configuration and any optional descriptions with your project; they need not be committed before analysis. Local credentials, caches, and reports belong in the ignored `.faultline/` directory.

## 5. Configure the Jev API key

After initialization, create `.faultline/.env` in the repository you want to analyze:

```dotenv
TYPESAFE_API_KEY="your-key"
```

Faultline reads this file automatically, including when invoked from an IDE. Keep it out of Git and do not paste the key into your agent conversation. An existing `TYPESAFE_API_KEY` environment variable takes precedence.

The key is needed for live Jev judgments. Selected change context, test descriptions, and graph evidence are sent to Jev.

## 6. Try a PR or MR

Ask your agent, replacing `123` with your PR or MR number:

> Use Faultline to analyze PR 123 with CodeGraph and Jev. Limit Jev to 10 HTTP requests. Save a shadow report showing which tests Faultline would run or omit. Do not execute tests or change CI.

Your agent needs access to the PR/MR through your existing hosting tools. Faultline saves the would-run report without executing tests. Use `faultline shadow-report` to summarize saved PR snapshots; keep your existing CI test jobs unchanged.

See the [workflow guide](../skills/faultline/references/graph-workflow.md) for configuration and command details.

## Optional: standalone CLI for CI

To use Faultline without a coding agent, install the Python package in a virtual environment:

```bash
python3 -m venv ~/.venvs/faultline
~/.venvs/faultline/bin/pip install 'git+ssh://git@github.com/ronaldtebrake/faultline.git'
~/.venvs/faultline/bin/faultline --help
```

CodeGraph is required for indexing. Your project's test runners and application environment are required for execution. For CI, pin the installation to a reviewed Git commit. Follow the same project configuration and API-key setup above, then use the commands in the [workflow guide](../skills/faultline/references/graph-workflow.md).

## Updating an existing installation

Reinstall/update the skill or plugin using the same method used above, then start a new agent session so it reads the new instructions. For a standalone checkout installation, reinstall from that checkout. Confirm the active engine with `faultline --version`, or `python3 "<installed-skill>/scripts/run.py" --version`: this source version is **0.2.0**. A Git-based installation receives it only after these changes are published to that Git revision.
