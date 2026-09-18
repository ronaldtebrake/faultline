# Install and try Faultline

Faultline currently ships as two Agent Skills, not a hosted service or an MCP server. The agent performs repository discovery and history collection. A bundled Python helper validates the inputs, talks to Jev, and calculates rankings and reports.

## Requirements

- Python 3.10 or later.
- A coding agent with repository, file, and shell access and support for Agent Skills.
- `TYPESAFE_API_KEY` available to the agent's shell for live ranking. Indexing, dry runs, and offline reports do not need it.
- Your usual authenticated Git/hosting tools for PR/MR work. For GitHub, the agent can use `gh` with your existing authentication.

No third-party Python runtime packages are required. Live ranking sends the supplied change text and test descriptions to TypeSafe. Nothing in the installer sends repository contents anywhere.

## Local checkout installation

From your Faultline checkout, install both skills into the target repository's skill directory:

```bash
python3 scripts/install_skills.py --target /path/to/target-repo/.agents/skills
```

The default creates symlinks to this checkout, so local updates are immediately available. The installer refuses to overwrite unrelated existing skills. Use `--copy` for a self-contained copy; copied installations must be replaced deliberately when updating.

For Codex, repository skills belong in `.agents/skills`, or use `~/.agents/skills` for user-wide installation. Codex supports symlinked skill directories. See the [official skill documentation](https://developers.openai.com/codex/skills/). Other agents have their own skill locations and invocation UX; install the same two directories together in the location they support. Cross-agent UI compatibility has not been live-tested.

This adds skill directories to the target repository. To keep a local trial out of commits, add those two paths to the repository's local Git exclude file, or choose user-wide installation instead. Faultline-generated data under `.faultline/` has its own ignore-all file and remains local.

The helper also works directly from the checkout, without installing skills:

```bash
python3 /path/to/faultline/skills/rank-tests/scripts/run.py --help
```

An optional console command can be installed in a virtual environment:

```bash
python3 -m venv /path/to/faultline-venv
/path/to/faultline-venv/bin/python -m pip install /path/to/faultline
/path/to/faultline-venv/bin/faultline --help
```

The package provides the helper CLI; install the two skill directories separately for agent discovery. A private Git remote needs no special runtime integration: use the local clone you already have access to.

## First trial

In the target repository, ask the agent:

```text
Use index-tests to build the Faultline catalog for this repository.
Show the discovered suite coverage and a few representative profiles.
```

Then, in a context that has not seen the historical failures:

```text
Use rank-tests to analyze PR 123 with Faultline.
Start with this one PR. Freeze predictions before inspecting test outcomes,
then save the findings and report. Respect the configured request ceilings.
```

Use the skill picker or the agent's supported explicit invocation syntax if it does not select the skills from that request. In Codex, you can reference `$index-tests` and `$rank-tests`. Refresh/restart the agent if newly installed skills do not appear.

For current ranking without retrospective comparison:

```text
Use rank-tests to rank the tests for PR 123.
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

Detailed contracts: [index](../skills/index-tests/references/index-schema.md), [evaluator](../skills/rank-tests/references/evaluator.md), [historical reports](../skills/rank-tests/references/report.md).

## Development validation

From the Faultline checkout:

```bash
PYTHONPATH=skills/rank-tests/scripts python3 -m unittest discover -s tests -v
```

The suite uses synthetic data and mocked HTTP. It verifies portable installation, incremental indexing, caching, rate-limit handling, probability validation, prediction integrity, outcome separation, metrics, and offline reports. It does not establish live Jev quality or the correctness of an agent's repository interpretation.
