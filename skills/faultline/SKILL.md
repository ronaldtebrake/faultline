---
name: faultline
description: Use Jev to assess which tests a PR or MR should run, collect verifiable source context for code or dependency changes, configure language-neutral source discovery, benchmark a cumulative change, explain RUN/OMIT decisions and costs, recover incomplete scoring, and compare frozen proposals with existing CI outcomes.
---

# Faultline

Use the bundled Python engine to score actual test source with Jev. Your role is repository setup, accurate revision selection, source-context investigation, and explanation of evidence. Do not invent scores, generate descriptions as a prerequisite, or prefilter candidates with agent judgment.

Resolve `<this-skill>` to this installed directory. Run `python3 "<this-skill>/scripts/run.py" --root "<repo>" ...`, or the equivalent `faultline` CLI. Keep local state in the analyzed repository. Never patch installed copies; change Faultline’s source and reinstall.

## One PR or MR

1. Read [the source workflow](references/workflow.md) for configuration. Identify actual test paths, scope, setup dependencies, and variants. `init` and `discover --revision <ref>` read Git source without application startup or native test execution. No generated catalog or separate index is needed. Keep missing/empty suites visible.
2. Resolve the cumulative diff base and exact tested head using Git and existing hosting tools. Historical and stacked PRs require their actual base, not today’s main. Source comes from Git objects without changing branches; local configuration is recorded separately. Do not reset, commit, change exclusions, or modify application files to clear warnings.
3. Read [context gathering](references/context.md). Investigate the change at its exact revisions. Collect actual product integration source, configuration, and test helpers; for dependencies, also establish upstream versions and inspect their source changes. Use the same manifest for any language or package manager. Freeze it with `context --base <base> --head <head> --input <manifest>`. Record specific gaps and unknown collection costs. Do not invent source, inspect CI outcomes, or select Jev’s test candidates. If only a diff-only baseline is requested, skip collection and label its limitation.
4. Read [the benchmark guide](references/benchmark.md). Run `benchmark --base <base> --head <head> --context <bundle> --prepare` with the authorized request ceiling. Inspect eligible targets, source limits, readiness, and estimated uncached work. Then score the same inputs within the remaining budget. Default adaptive mode preserves whole inputs when possible, otherwise covers every source/change range in bounded windows. No source ranges are silently discarded; cross-window interactions remain outside scope.
5. Present the generated RUN/OMIT report, assessed/unresolved counts, requests, input tokens, and dated cost estimates. Identify diff-only versus enriched inputs, declared context gaps, and agent collection costs separately from Jev. Context must match the exact change; standalone CI needs the frozen bundle to reproduce enrichment. Separate policy choices, mandatory rules, and fallbacks. A model choice of irrelevant may still produce RUN below the omission cutoff. Relevance is not failure probability, measured coverage, or observed savings.
6. Use `benchmark-report --compare-policies` for offline threshold/budget comparisons, and `--format comment` for a compact preview. Neither calls Jev nor publishes a comment. Use a real HTTPS artifact URL with `--report-url`; never invent links or include local paths in posted summaries.

Shadow mode executes no tests and leaves CI unchanged. Native discovery, application startup, and execution are separate actions requiring user authorization. `run` only previews unless `--execute` is supplied; explicit execution currently runs full suites, not selected subsets. Agents can help configure selectors from real runner identities, but cannot invent executable identities.

## Incomplete evidence and costs

Use `benchmark-recover --prepare` to inspect unresolved work before authorized live recovery. Accepted judgments and the original case remain immutable. Oversized inputs use complete-line windows; every part needs a valid distribution before assessment is complete. Invalid-response retries and smaller batches after a confirmed provider token-limit rejection share the same request, time, and judgment limits. A single oversized question remains unresolved; do not retry ambiguous network failures as size errors. Unknown network outcomes are not retried automatically because the request may have been billed.

A user’s request budget is the total for the task, including probes, retries, and resumed invocations. Do not raise limits or loop to reset a budget. Partial scoring exits 2 and still saves a report. Zero requests may mean cached answers; check actual assessment status. Unknown token usage stays unknown. Cached or incomplete runs do not establish the price of a new fully scored PR.

Credentials load lazily from `TYPESAFE_API_KEY`, repository `.faultline/.env`, then root `.env`. Let the user enter the key locally; never request it in chat or display credential files. Actual test source and selected change context go to Jev. Repair TLS trust with an approved certificate path or optional certifi in the active Python environment; never disable verification.

## Outcomes after predictions

Freeze decisions and any policy comparisons before inspecting CI outcomes. Work on one PR/MR at a time unless broader collection is requested. Use exact tested revisions and attempts; do not apply a final fixed diff to an earlier failure. Omit historical PR text if its pre-outcome version is unverifiable.

If this session has already seen failures, record the case as previously inspected. Never claim outcome blindness retroactively. Import existing CI outcomes with `benchmark-report --outcomes`; match native identities explicitly, classify failures with evidence, and leave uncertainty unknown. Unexecuted tests are not passing tests. Repeated attempts are related observations, not independent cases. Keep tuning cases separate from later assessment cases.

Use existing hosting tools with bounded requests, provider rate-limit handling, and cached responses. Do not trigger CI, publish comments, or modify test commands as part of report generation. Report-only summaries need no external writes.

For explicitly requested native discovery, full-suite execution, or coverage imports, read [runner integration](references/execution.md).
