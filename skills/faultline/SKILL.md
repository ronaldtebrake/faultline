---
name: faultline
description: Analyze test impact for a PR/MR with CodeGraph and Jev, maintain shared source-based test catalogs, run full-suite shadow evaluations, and explain Faultline reports. Also supports existing semantic rankings and retrospective evaluation.
---

# Faultline

You gather repository evidence and interpret findings. Jev supplies semantic judgments. The bundled code owns questions, probability validation, scoring, cache identity, and measurements. Never replace Jev scores or reorder its ranking with your own judgment.

Use [the CodeGraph workflow](references/graph-workflow.md) for new setup and PR/MR analysis. CodeGraph supplies structural relationships; configured source paths identify provisional file targets; Jev supplies relevance probabilities. Native runners establish executable identities only when execution is requested. All current execution is full-suite shadow execution. Never treat a graph's empty result as permission to skip tests.

Resolve `<this-skill>` to the directory containing this installed SKILL.md. Invoke `python3 "<this-skill>/scripts/run.py" --root "<repo>" ...`, or the equivalent installed `faultline` CLI. Keep generated state in the analyzed repository, not the installed skill. CodeGraph is a separate pinned CLI dependency; its MCP/agent installer is unnecessary.

## Current single-PR flow

1. Inspect existing suite commands and CI variants. Configure `faultline.json` and use [source discovery and catalog review](references/shared-catalog.md). `discover`, all `catalog` commands, and `select` do not invoke test runners by default. Use `kind: "check"` for whole checks such as static analysis. Reuse committed descriptions; update only changed tests/context. Do not invent test identities or generate descriptions automatically in CI.
2. Resolve the requested PR/MR's actual cumulative diff base and tested head using Git and available hosting tools. Work on the tested revision. Do not replace a stacked PR's base with the main branch. Reuse the user's authorized setup and scope.
3. Run `select --base <base> --head <tested-head> --id <pr-id> --output <fresh-selection-path>`. It builds/reuses both graphs, obtains bounded Jev judgments, and freezes a provisional file-level proposal. Native discovery is optional via `select --native` or `discover --native`; use it only when explicitly requested in a prepared test environment. Do not start services, install runtime dependencies, or invoke test runners merely to analyze source. Use dry-run when checking existing evidence/cost limits; it performs no indexing or API calls.
4. For an evaluation request, continue through `run` for each configured suite/variant and `record` for each receipt. Each `run` validates only the requested suite with its runner, retains exact native members in the receipt, and executes the full suite. Discovery failure or disagreement keeps full execution and makes the assessment incomplete. Whole checks run directly without test enumeration. These commands require the prepared application environment; CI service/container orchestration stays with the project. Respect prerequisite receipts. Capture JUnit for supported native runners or import the exact generic outcome contract. Test failures must still be recorded; they do not end the reporting flow.
5. Present the saved Markdown/JSON report and `shadow-report` aggregate. Distinguish graph paths, semantic relevance, observed regressions, and measured coverage. Surface full fallbacks, unmatched tests, incomplete data, costs, and limits. Do not claim that a green run proves omission safe.

For ranking-only requests, stop after presenting the frozen proposal. For full analysis/evaluation requests, carry through reporting when the environment is available; describe concrete blockers if execution cannot proceed. Do not trigger remote CI jobs or post messages unless requested.

Credentials are loaded lazily from `TYPESAFE_API_KEY`, repository `.faultline/.env`, then root `.env`. If absent, explain the full fallback and let the user enter the key locally; never ask them to paste it into chat or display credential files. Selected change context, descriptions, and graph paths are sent to Jev. Follow the configured request/time/byte limits.

## Existing ranking and retrospective data

The `rank`, `evaluate`, and `report` commands remain available for existing explicit profile/prediction files. They do not consume the shared graph pipeline's selections. Read [indexing](references/indexing.md), [the index contract](references/index-schema.md), [the evaluator contract](references/evaluator.md), and [history/reporting](references/report.md) only when working with those records.

## Existing explicit-profile ranking flow

1. Read repository instructions. Use [the indexing workflow](references/indexing.md) to create/update `.faultline/index.jsonl` when missing or stale. Do not force a framework-specific implementation on the repository.
2. Resolve the requested PR/MR and the appropriate base/head/tested revisions with Git and the available hosting tools. Cache evidence under `.faultline/history/`. Use a PR/MR's cumulative change, not each constituent commit as an unrelated change. Do not expose a standalone commit-ranking workflow as the default.
3. Write structured change input according to the evaluator contract. Keep only pre-outcome context. For an ordinary current ranking, set `provenance.historical` to false.
4. Run `rank --change <change.json> --dry-run`. Report the expected uncached request count when meaningful. The default ceiling is 100 Jev requests; honor user constraints and configured limits. One test judgment uses one request. Before live ranking, the key must be available as `TYPESAFE_API_KEY` in the process environment, the analyzed repository's `.faultline/.env`, or its root `.env`, in that priority order. If missing, tell the user to enter it locally in `.faultline/.env` after initialization; do not ask them to paste it into chat or read/display the file yourself. The helper reads it automatically. Never print the key or include it in generated artifacts. Selected change text and profiles are sent to TypeSafe.
5. Run `rank --change <change.json>`. It saves the full probability evidence and a readable ranking automatically. Repeated identical input reuses the frozen prediction. A partial result is visibly incomplete; do not present it as a full ranking or reveal historical outcomes until it is complete.
6. Present the saved ranking, its scope, and limitations. For a request to **analyze/evaluate** this PR/MR, continue into the retrospective flow and save its findings and report in the same user request. The user should not have to invoke each internal stage.

## Historical flow: prediction before outcome

Select one PR/MR by default. Process a larger sample only when explicitly requested, incrementally and within provider budgets. A single case can be useful but does not establish general performance.

Before inspecting test outcomes, identify run IDs/attempts and tested revisions using metadata limited to those fields. Reconstruct each applicable cumulative diff and outcome-blind intent. Never use the final fixed diff for an earlier failing run. Current PR text may have been edited after failure; omit it if a trustworthy historical version is unavailable and document that omission.

The strict sequence is: prepare index/context → call Jev → persist a **complete frozen prediction** → inspect outcomes → classify with evidence → run deterministic `evaluate` → present the generated report and explain misses. Do not inspect job conclusions, failure logs, results artifacts, or later debugging comments before prediction. Do not preselect only known failing snapshots. Rank the chosen snapshots independently of their outcomes.

If this agent context has already seen the historical failures, do not assert `outcomes_seen: false`. Use a genuinely fresh outcome-blind session with only permitted input, or clearly report that a valid retrospective experiment cannot be completed in this context. Do not delegate unless the user's environment and instructions authorize it. The helper checks declared provenance but cannot prove what an agent has seen.

After freezing, collect outcomes using the user's existing Git/hosting tools. Do not trigger workflows, post comments, or modify CI. Map actual result identities to catalog IDs using explicit evidence, not fuzzy guesses. Classify failures as confirmed regression, likely flake, infrastructure, baseline, or unknown; leave uncertain cases unknown. Record evidence for every non-unknown label.

Run `evaluate --prediction <prediction-id-or-file> --outcomes <outcomes.json>`. This automatically saves JSON findings and a Markdown report. Investigate poor ranks only after the prediction is frozen. Any improved index/question belongs to a new experiment; never overwrite the original result.

`report --prediction <id>` regenerates a case report from saved findings. `report` aggregates saved evaluations without API calls. The JSON measurements are authoritative; add narrative explanation without inventing evidence or changing numbers.

## API discipline

Repository collection uses the agent's available tools, not a Faultline hosting client. Make authenticated serial requests, reuse cached responses, retrieve only the selected change and necessary artifacts, and paginate with an explicit finite request budget (default 100 hosting requests per invocation). Track calls in the local collection notes. Stop and save progress when the budget is exhausted. Refresh existing remote evidence only on an explicit refresh request; show collection time.

Honor provider `Retry-After`/reset instructions and bounded backoff. Do not repeatedly fetch expired artifacts, poll unfinished runs, or download unrelated logs. The bundled Jev transport independently enforces pacing, a request ceiling including retries, and resumable rate-limit cooldowns. Unknown network outcomes are not retried automatically because inference may already have been billed.

The existing explicit-profile ranking commands do not execute tests. The graph workflow executes configured full suites and records proposed omissions for assessment; it does not enable test skipping.
