# Install and try Faultline

Faultline bundles one Agent Skill and its evaluation scripts. Install it with the Skills CLI or your agent's native plugin manager. Both use the same `skills/faultline/` directory; no separate Python installer or package installation is needed.

## Requirements

- An agent that supports Agent Skills, with repository, file, and shell access.
- Python 3.10+ to run the bundled evaluator, with no third-party Python runtime packages.
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

## First trial

In the target repository, ask the agent:

```text
Use Faultline to build the Faultline catalog for this repository.
Show the discovered suite coverage and a few representative profiles.
```

Then, in a context that has not seen the historical failures:

```text
Use Faultline to analyze PR 123 with Faultline.
Start with this one PR. Freeze predictions before inspecting test outcomes,
then save the findings and report. Respect the configured request ceilings.
```

Use the skill picker or the agent's supported explicit invocation syntax if it does not select the skill from that request. In Codex, you can reference `$faultline`. Refresh/restart the agent if the newly installed skill do not appear.

For current ranking without retrospective comparison:

```text
Use Faultline to rank the tests for PR 123.
```

The agent handles the end-to-end request, including input preparation and report generation. There is no framework-discovery `faultline analyze --pr` command: the skill is the orchestrator, while the helper accepts structured files.

If the agent has already inspected a failure, it must not claim to have produced an outcome-blind historical prediction. A fresh session can prepare the input without the outcomes; the comparison happens only after a complete ranking is saved.

## API usage and incomplete evidence

The initial configuration uses a pinned Jev model, one request at a time, one second between requests, a 100-request ceiling including retries, and up to two retries for explicit rate-limit/overload responses. One test judgment uses one request; a large suite can exceed that ceiling even for one PR.

The dry run shows how many uncached calls are needed. If it exceeds the ceiling, the helper makes no Jev calls and writes an incomplete ranking status. Review the estimate and set an appropriate limit in `.faultline/config.json` or use the helper's `--max-requests N`. Do not silently rank only the first N tests. Successful pair predictions survive interruptions and are reused on the next invocation.

GitHub/other history requests are made by the agent's tools. The skill instructs it to cache, limit, and pace collection; the Python helper cannot enforce calls made outside it. Neither part starts CI workflows or changes required checks.

A report may legitimately say performance cannot be assessed: no confirmed regression, missing artifacts, unmapped failing tests, or unreconstructable historical context are insufficient evidence. The report retains those limitations. Unknown failures can be reviewed later and reevaluated without repeating unchanged inference.

## Files and inspection

- `.faultline/index.jsonl`: test profiles and provenance.
- `.faultline/history/`: agent-collected change/run evidence.
- `.faultline/predictions/<id>/prediction.json`: frozen ranking inputs and probabilities.
- `.faultline/predictions/<id>/ranking.md`: ranking-only report.
- `.faultline/evaluations/<id>/`: outcome evidence, findings, Markdown and JSON case reports.
- `.faultline/reports/latest.md` and `latest.json`: offline aggregate.

The agent can show individual profiles with `explain-test`, regenerate a case with `report --prediction <id>`, or summarize all saved cases with `report`. Reports make no API calls. A one-PR summary remains a case study, not proof of general ranking quality.

Detailed contracts: [index](../skills/faultline/references/index-schema.md), [evaluator](../skills/faultline/references/evaluator.md), [historical reports](../skills/faultline/references/report.md).

## Development validation

From the Faultline checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=skills/faultline/scripts python3 -m unittest discover -s tests -v
```

Distribution has also been checked with a real Skills CLI 1.7.0 local copy installation and the Codex plugin manifest validator. Native Codex/Claude plugin installation and remote private-Git installation have not been exercised end to end.

The suite uses synthetic data and mocked HTTP. It verifies portable installation, incremental indexing, caching, rate-limit handling, probability validation, prediction integrity, outcome separation, metrics, and offline reports. It does not establish live Jev quality or the correctness of an agent's repository interpretation.

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

Instructions resolve the helper relative to the installed skill, then pass the analyzed repository with `--root`. Installation location and analyzed repository can be different. The helper writes only to the analyzed repository's `.faultline/`; it does not modify the installed bundle.

For contributor use, `python3 skills/faultline/scripts/run.py --help` works directly. An optional `pip install .` in a virtual environment exposes the equivalent `faultline` command; it is not required for skill or plugin installation.
