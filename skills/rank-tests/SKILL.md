---
name: rank-tests
description: Rank tests for a PR/MR or other software change using Faultline's fixed Jev evaluator, and evaluate frozen rankings against historical outcomes. Use for semantic test ranking, one-PR retrospective analysis, or explaining Faultline reports.
---

# Rank tests with Faultline

You gather repository evidence and interpret findings. Jev supplies semantic judgments. The bundled code owns questions, probability validation, scoring, cache identity, and measurements. Never replace Jev scores or reorder its ranking with your own judgment.

Use `python3 <this-skill>/scripts/run.py --root <repo> ...` (Python 3.10+, no third-party dependencies). An installed `faultline` command is equivalent. Read [the evaluator contract](references/evaluator.md) when preparing a change. For retrospective analysis also read [the history/report contract](references/report.md).

## Normal single-change flow

1. Read repository instructions. Use the sibling `index-tests` skill to create/update `.faultline/index.jsonl` when missing or stale. Do not force a framework-specific implementation on the repository.
2. Resolve the requested PR/MR and the appropriate base/head/tested revisions with Git and the available hosting tools. Cache evidence under `.faultline/history/`. Use a PR/MR's cumulative change, not each constituent commit as an unrelated change. Do not expose a standalone commit-ranking workflow as the default.
3. Write structured change input according to the evaluator contract. Keep only pre-outcome context. For an ordinary current ranking, set `provenance.historical` to false.
4. Run `rank --change <change.json> --dry-run`. Report the expected uncached request count when meaningful. The default ceiling is 100 Jev requests; honor user constraints and configured limits. One test judgment uses one request. The key comes from `TYPESAFE_API_KEY`; never print or persist it. Selected change text and profiles are sent to TypeSafe.
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

Version one supplies a signal for the agent and future CI policy. It neither runs tests nor decides which tests to skip. Preserve exact runner locators so later execution-order integrations can consume the same catalog.
