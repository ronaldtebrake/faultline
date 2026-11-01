# Setup, assess, report

Use the installed `faultline` CLI, or `python3 "<this-skill>/scripts/run.py" --root "<repo>"`.

1. Run `setup`, review the source suggestions and save the actual test paths with `setup --source '<glob>' --scope '<glob>'`. For multiple suites use [configuration](workflow.md). Existing configuration is validated without being overwritten.
2. Resolve the cumulative PR merge base and exact committed head. Analysis reads Git objects, not uncommitted edits.
3. Run `assess --base <base> --head <head>`. This defaults to `graph-v1`, uses no credentials and makes no Jev calls. Add `--runtime <validated-observations.json>` to include existing CI evidence. Source facts are reused automatically. `--prepare` inspects the same graph without freezing a report.
4. Return the run ID, HTML and frozen JSON paths. Explain affected paths, mandatory rules and unresolved tests. The full suite remains required: missing paths do not establish independence.
5. Use `report --run <id> --output <basename>` to regenerate HTML, Markdown and CSV offline. `assess --resume <graph-run-id>` reopens the original frozen report. A new assessment uses the current revisions and configuration.

`select --base <base>` also defaults to a graph report. Graph reports are not executable selection manifests; `export-selection` rejects them. Keep full CI running throughout validation.

## Optional paid Jev assessment

Only when requested within an authorized budget, follow [context gathering](context.md), [Jev guidance](jev.md) and [budget arithmetic](benchmark.md#spending-budget). The user enters a key locally; never request or display it.

```sh
faultline assess --jev --base <base> --head <head> --prepare --max-cost 0.50
faultline assess --jev --base <base> --head <head> --max-cost 0.50
faultline assess --jev --resume <run-id>
```

Explicit `--jev` selects Noul with positive dependency retention. Unresolved tests remain eligible for scoring. Paid progress and spending limits survive resume. Supplying an evaluator, a key or a saved Jev run never substitutes for `--jev`. Configuration/context changes require a new run. Do not increase a spending limit without authorization.

Use `--jev --evaluator choice-v1` for the legacy Choice contract, with request limits and optional `--reuse-cache`. Its scores and thresholds are not interchangeable with Noul. `benchmark` and `benchmark-recover` also require `--jev` for inference; `--prepare` is offline.

Reports separate model proposals from measured outcomes. Agent investigation is outside the engine clock; missing API usage is unknown. Test counts alone do not establish regression recall or CI savings. Selective execution remains a separate, explicitly authorized [CI experiment](ci.md).
