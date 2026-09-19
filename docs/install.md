# Install and try Faultline

Faultline bundles one Agent Skill and its evaluation scripts. Install it with the Skills CLI or your agent's native plugin manager. Both use the same `skills/faultline/` directory; no separate Python installer or package installation is needed.

## Requirements

- For IDE use, an agent that supports Agent Skills, with repository, file, and shell access. CI can use the standalone CLI without an agent.
- Python 3.10+ to run the bundled evaluator, with no third-party Python runtime packages.
- CodeGraph 1.6.0 for structural indexing; see the [graph workflow](../skills/faultline/references/graph-workflow.md#install-and-configure).
- Native test runners and their existing dependencies for discovery and execution.
- Node.js/npm when using `npx skills`; native plugin installation does not require npm.
- Existing Git credentials for this private repository, and authenticated hosting tools for PR/MR analysis.
- `TYPESAFE_API_KEY` configured below for live ranking. Indexing, dry runs, and saved reports work without it. Selected change text and test descriptions are sent to TypeSafe.

## Configure the Jev API key

Before the first live ranking, ask Faultline to initialize or index the repository. Then create `.faultline/.env` **in the repository you want to analyze**, using your IDE:

```dotenv
TYPESAFE_API_KEY="your-key"
```

Faultline initialization creates `.faultline/.gitignore` with an ignore-all rule, keeping this local credential file out of ordinary Git commits. Do not put a real key in the installed skill, prompts, or `config.json`.

The evaluator reads the file automatically when a live request is needed, including when your agent runs in an IDE. No terminal export or agent restart is required for file-based setup. Installation, indexing, dry runs, cached rankings, and saved reports do not require the key.

Lookup order is a nonempty process environment variable, then `.faultline/.env`, then the analyzed repository's root `.env`. If you already use a root `.env`, add the key there and ensure that file is ignored by Git. Paths are resolved from the analyzed repository, never from the plugin's installation directory or unrelated working directory.

Only `TYPESAFE_API_KEY` is read; other entries are ignored. Single-line plain or quoted values, optional `export`, and trailing comments are supported. Values are literal: no variable interpolation, shell execution, multiline strings, or escape processing. The key is not written to caches or reports.

## Skills CLI

From the repository you want to analyze:

```bash
npx skills add git@github.com:ronaldtebrake/faultline.git --skill faultline
```

Choose your agent interactively or add `--agent codex` or `--agent claude-code`. Add `--global` for installation across projects. Project installation can create skill directories and a lockfile in the current repository; review these before committing them. No `--target` or manual copying is needed.

The [Skills CLI](https://github.com/vercel-labs/skills) supports private Git sources and copies the selected skill's scripts and references with it. Faultline has no dependencies on sibling skills or repository-root files at runtime. Its Python package is optional developer tooling.

## Native plugins

Choose this instead of Skills CLI installation to let your agent's plugin manager manage the bundle. Do not install both methods in the same scope, which can expose duplicate skills.

### Codex

With a Codex CLI that provides `codex plugin`:

```bash
codex plugin marketplace add git@github.com:ronaldtebrake/faultline.git
codex plugin add faultline@faultline
```

The repository includes a marketplace at `.agents/plugins/marketplace.json`, a portable root `plugin.json`, and a `.codex-plugin/plugin.json` compatibility manifest. See [OpenAI's plugin packaging documentation](https://developers.openai.com/plugins/build/plugins).

### Claude Code

In Claude Code:

```text
/plugin marketplace add git@github.com:ronaldtebrake/faultline.git
/plugin install faultline@faultline
```

The `.claude-plugin/` manifests package the same skill and scripts. See [Claude Code's marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces). Plugin skills are namespaced; use `/faultline:faultline` or ask for Faultline in plain language.

## Try unpublished changes from a local checkout

Remote installation uses the pushed repository revision. To try local work before it is pushed, run this from the repository you want to analyze, replacing the source path with your Faultline checkout:

```bash
npx skills add /path/to/faultline --skill faultline --agent codex
```

This installs the skill through the normal Skills CLI. Re-run it after local changes; do not assume the installed bundle is a live link to the source checkout. `--copy` requests copied files rather than agent-directory symlinks.

Native local alternatives:

```bash
codex plugin marketplace add /path/to/faultline
codex plugin add faultline@faultline
```

```bash
claude --plugin-dir /path/to/faultline
```

Refresh/restart your agent after installation if the skill is not visible. For migration from the old installer, remove only the old Faultline `index-tests` and `rank-tests` directories or symlinks you previously installed. Their data remains in the target repository's `.faultline/` directory.

## Standalone CLI for local development and CI

The Python package and skill entry point use the same engine. To test your current Faultline checkout from another repository:

```bash
python3 -m venv .venv-faultline
.venv-faultline/bin/pip install -e /path/to/faultline
npm install -g @colbymchenry/codegraph@1.6.0
.venv-faultline/bin/faultline --help
```

Ignore the virtual environment in the target repository, or create it outside the checkout. Use a pinned Git revision or wheel for CI; an editable install is convenient for testing unpublished local changes. CodeGraph's agent/MCP installer is unnecessary.

## First trial

Ask the installed skill:

```text
Use Faultline to configure native test discovery and reviewed descriptions for this repository.
Then analyze PR 123 with CodeGraph and Jev, run the full suites in shadow mode,
and save the findings and report. Respect the configured budgets.
```

The agent handles PR metadata through existing hosting tools and invokes the same commands CI uses. There is no built-in GitHub/GitLab client or bulk PR crawler. Work from the actual tested revision and cumulative diff base; freeze proposals before inspecting outcomes. For ranking-only requests, the agent can stop after selection.

Follow the [graph workflow](../skills/faultline/references/graph-workflow.md) for complete configuration and runnable `select`, `run`, `record`, and `shadow-report` examples. `record` saves a report immediately after a single run; `shadow-report` aggregates saved cases offline. Use fresh selection, receipt, and result paths for each attempt.

The default Jev ceiling is 100 HTTP attempts, with bounded batches, pacing, retries, and elapsed time. Set a smaller `evaluator.jev_requests` budget in committed `faultline.json` for an initial pilot. Missing credentials or incomplete evidence produce a full-execution fallback. Existing exact-input caches can be restored from trusted CI jobs.

The standalone legacy `rank`/`evaluate`/`report` workflow remains available for previously prepared profile and prediction files. Its contracts are described in the bundled [evaluator](../skills/faultline/references/evaluator.md) and [historical reporting](../skills/faultline/references/report.md) references; it does not consume graph selections.

## Development validation

From the Faultline checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=skills/faultline/scripts python3 -m unittest discover -s tests -v
```

Distribution has also been checked with a real Skills CLI 1.7.0 local copy installation and the Codex plugin manifest validator. Native Codex/Claude plugin installation and remote private-Git installation have not been exercised end to end.

The default suite uses synthetic data and mocked HTTP. Set `FAULTLINE_CODEGRAPH` to the pinned executable path to run the additional real-producer conformance test. It verifies portable installation, incremental indexing, caching, rate-limit handling, probability validation, prediction integrity, outcome separation, metrics, and offline reports. It does not establish live Jev quality or the correctness of an agent's repository interpretation.

## Package layout and contributor tools

```text
plugin.json                       Portable Agent Plugins metadata
.codex-plugin/plugin.json         Codex compatibility metadata
.agents/plugins/marketplace.json  Codex repository marketplace
.claude-plugin/                   Claude Code plugin and marketplace
skills/faultline/
  SKILL.md                        Agent entry point
  references/                     Indexing, evaluator, and report contracts
  scripts/run.py                  Bundled helper entry point
  scripts/faultline/               Standard-library-only evaluation code
```

Instructions resolve the helper relative to the installed skill, then pass the analyzed repository with `--root`. Installation location and analyzed repository can be different. Generated evidence stays in the analyzed repository's `.faultline/`; catalog maintenance updates its committed `faultline/catalog/`. CodeGraph works in temporary Git snapshots. The engine does not modify the installed skill bundle.

For contributor use, `python3 skills/faultline/scripts/run.py --help` works directly. An optional `pip install .` in a virtual environment exposes the equivalent `faultline` command; it is not required for skill or plugin installation.
