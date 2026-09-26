# Commands

Run in the analyzed repository, or put `--root /path/to/project` before the command. Skill installations invoke `python3 "<installed-skill>/scripts/run.py"` instead of `faultline`.

## Set up once

```bash
faultline setup
# After reviewing the suggestions, use your actual paths:
faultline setup --source 'tests/**/*.test.ts' --scope 'src/**'
```

The first command suggests common test filenames when configuration is absent. The second saves your chosen patterns. Existing configuration is validated without being overwritten. For multiple suites and variants, edit `faultline.json`; see the [configuration reference](../skills/faultline/references/workflow.md).

## Assess a PR or MR

Use the cumulative diff base and exact tested head supplied by your hosting tools or agent. For a merged PR, use its original revisions. Fetch missing Git objects without switching branches.

```bash
faultline assess --base <diff-base> --head <tested-head> --prepare --max-requests 100
faultline assess --base <diff-base> --head <tested-head> --id PR-123 \
  --fresh --max-requests 100 --selection-seconds 120
```

Preparation is offline. Review eligible targets, missing evidence, request estimates and your [spending allowance](../skills/faultline/references/benchmark.md#spending-budget) before scoring. The example request limit is not a universal dollar budget. Provide dated pricing in `faultline.json` to obtain cost estimates; unknown charges stay unknown.

`assess` saves HTML, Markdown, CSV, policy comparisons, frozen evidence and progress under `.faultline/runs/<run-id>/`. The HTML works as a single file, including 10/25/50% tabs, with no JavaScript or external assets. It contains test identities and decisions, so review those before sharing.

New assessments are fresh by default. `--fresh` makes this explicit: no old answer reuse and no shared-cache writes. `--reuse-cache` opts into exact-input reuse through a disposable cache capped at 64 MiB. Both modes save this run's progress.

When changed implementation is absent from the diff, follow the [context reference](../skills/faultline/references/context.md) and add `--context <bundle.json>` to preparation and assessment. The engine does not autonomously fetch dependencies or investigate callers.

## Resume or regenerate a report

```bash
faultline assess --resume <run-id>
faultline report --run <run-id> --output .faultline/reports/pr-review.html
```

Resume retains accepted answers and all recorded attempts. The run-wide request ceiling does not reset; increasing it requires an explicit `--max-requests`. Changed configuration or engine versions require a new run. Source Git objects must remain available. Report generation is offline and does not need them.

Reports separate fresh, resumed and reused answers; input cost; inference time; and engine time through report generation. Agent investigation and installation are outside that clock. Missing usage and interrupted durations are not assumed to be zero. None of these commands executes tests or changes CI.

## Advanced tools

Existing commands remain available for research and CI outcome comparison:

| Command | Purpose |
| --- | --- |
| `init`, `discover` | Inspect configured source inventory. |
| `context` | Verify and freeze an agent's source manifest. |
| `benchmark`, `benchmark-recover` | Lower-level evidence experiments and window recovery; legacy per-invocation budgets and cache behavior. |
| `benchmark-report` | Import exact existing CI outcomes, or generate a PR-comment preview; never posts it. |
| `report --benchmark <case.json>` | Add standalone HTML to an existing compatible benchmark. |
| `select`, `shadow-report` | Save and inspect execution proposals. |
| `run`, `record`, `execution-report` | Explicit full-suite execution and outcome import. |
| `mapping import-phpunit` | Import positive coverage evidence. |
| `cache compact` | Migrate legacy per-answer files to SQLite. |

See the [benchmark reference](../skills/faultline/references/benchmark.md) and [execution reference](../skills/faultline/references/execution.md). Relevance is not failure probability; mandatory and unresolved targets remain RUN. Selective execution is not implemented.

Exit codes: **0** complete, **1** command error, **2** incomplete assessment, **130** uncaught interruption. Caught inference interruptions save an incomplete report and return 2. Explicit execution preserves the runner's exit status.
