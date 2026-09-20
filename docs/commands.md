# Commands

Run commands from the project you are analyzing, or put `--root /path/to/project` before the command. Skill-only installations use `python3 "<installed-skill>/scripts/run.py"` in place of `faultline`.

## Prepare and score

Resolve the PR/MR’s cumulative diff base and tested head through your Git hosting tools. For a merged PR, use its original revisions, not today’s main. Fetch missing objects without switching branches.

```bash
faultline benchmark --base <diff-base> --head <tested-head>   --prepare --max-requests 100

faultline benchmark --base <diff-base> --head <tested-head>   --id PR-123 --max-requests 100 --selection-seconds 120
```

Preparation is offline. Inspect eligible targets, blockers, and estimated uncached requests before scoring. The example budget may not fit your suite. The live command saves JSON evidence, Markdown, and CSV under `.faultline/benchmarks/`; it never runs tests.

For supporting product or dependency source, have your agent follow the [context reference](../skills/faultline/references/context.md), then add `--context <bundle.json>` to both commands. Without it, the inputs are the diff and test source.

## Compare relevance thresholds

```bash
faultline benchmark-report --benchmark <case.json>   --compare-policies --relevance-thresholds 0.10 0.25 0.50   --output .faultline/reports/pr-review.md
```

This reuses saved judgments without API calls. The CSV lists every file’s decision and reason. Comparisons retain mandatory rules and unresolved fallbacks; relevance is not a probability of failure.

Use `--format comment` for a compact PR-comment preview. It writes a local file and does not post anything. Add `--pricing <price.json>` for dated cost estimates; the [benchmark reference](../skills/faultline/references/benchmark.md) describes the format.

## Recover incomplete scoring

```bash
faultline benchmark-recover --benchmark <case.json> --prepare --max-requests 50
faultline benchmark-recover --benchmark <case.json> --max-requests 50 --selection-seconds 120
```

Use your remaining request budget, including earlier attempts and retries. Recovery preserves accepted judgments and writes a new case. It does not solve missing source or declared context gaps by spending more.

## Import outcomes

Freeze the report and policy comparison before examining CI results. Then import results tied to the exact tested revision and attempt:

```bash
faultline benchmark-report --benchmark <case.json> --outcomes <outcomes.json>
```

See [outcome assessment](../skills/faultline/references/benchmark.md#assess-outcomes) for the schema and failure classifications. Unexecuted tests remain unknown.

## Other commands

| Command | Purpose |
| --- | --- |
| `init`, `discover` | Initialize ignored storage and inspect configured Git test files. |
| `context` | Verify and freeze an agent’s source manifest. |
| `select`, `shadow-report` | Save and review selection receipts for the optional execution workflow. |
| `run`, `record`, `execution-report` | Preview, explicitly run full suites, and import their results. |
| `mapping import-phpunit` | Import existing test-attributed coverage as positive evidence. |
| `cache compact` | Consolidate old answer files into SQLite. |

The [execution reference](../skills/faultline/references/execution.md) covers runner setup. `run` only executes with `--execute`; selective execution is unavailable. Use `faultline <command> --help` for all options.

Exit codes: **0** completed, **1** command error, **2** incomplete assessment, **130** interrupted. Explicit execution preserves the runner’s exit status. Incomplete scoring still saves its report.
