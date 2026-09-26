# Setup, assess, report

Use `python3 "<this-skill>/scripts/run.py" --root "<repo>"` before the commands below. The bundled engine needs Python 3.10+ and Git; no pip install or separate skill is required.

1. Run `setup`. If configuration is missing, review its candidate paths and inspect the repository's runner configuration for missing conventions. Save reviewed sources with `setup --source '<glob>' --scope '<glob>'`; repeat either option as needed. For multiple suites or variants, create `faultline.json` using [configuration](workflow.md). Existing configuration is only validated. Confirm the inventory with the user when its scope is ambiguous.
2. The user enters `TYPESAFE_API_KEY` locally in `.faultline/.env`, the environment, or root `.env`. Never print or request the key. Setup reports presence, not API validity.
3. Resolve the cumulative base and exact PR/MR head using existing Git/hosting tools. Keep the current checkout unchanged. For merged PRs, use original revisions rather than today's main. Inspect the diff; load [context gathering](context.md) only if changed behavior is missing. Freeze a bundle before scoring; do not send whole investigation transcripts.
4. Prepare offline:

   ```bash
   assess --base <base> --head <head> --prepare --max-requests <allowance>
   ```

   Include the same `--context <bundle>` in both commands when needed. Review eligible targets, blockers and the estimate against the user's spending allowance. Apply [the budget arithmetic](benchmark.md#spending-budget); this engine enforces HTTP attempts, not a dollar limit.

5. Score and export:

   ```bash
   assess --base <base> --head <head> --id <display-name> --fresh \
     --max-requests <allowance> --selection-seconds <seconds>
   ```

   It saves a single-file HTML report with 10/25/50% tabs plus JSON, Markdown and CSV. Report the returned paths and run ID. Analysis runs no tests. Valid answers are saved immediately; uncertainty remains visible.

6. If interrupted or incomplete, use `assess --resume <run-id>`. Accepted answers and prior attempts survive restarts. The run-wide request allowance does not reset. Increase `--max-requests` only within an authorized remaining spending budget. Configuration, context and revision changes need a new run. Missing source or semantic gaps need better evidence, not retries.
7. `report --run <run-id>` regenerates reports offline. `report --demo --output <path.html>` demonstrates the format with invented data and no credentials.

Each new assessment is fresh by default; `--fresh` is explicit. `--reuse-cache` permits an optional 64 MiB exact-input answer cache. Run evidence is separate and always retained. The report distinguishes newly accepted answers, recovered answers in this run, and reuse from other runs. Cache misses or cache failures never erase paid progress.

The current evaluator uses five-level Choice probabilities and serial bounded transport. Pooled/Noul experiments are documented separately; these commands do not promise their timings. Compare relevance thresholds offline without changing or normalizing the stored probabilities.

Engine-to-report time excludes installation, agent investigation and the final metadata export. Report unknown agent time/cost and missing API usage as unknown. Fewer selected files do not establish actual CI time saved, regression recall or coverage.
