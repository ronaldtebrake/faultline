---
name: faultline
description: Assess which tests a PR, MR or cumulative diff should run using Jev. Set up source discovery, gather missing implementation evidence, produce shareable reports with costs and relevance thresholds, and resume incomplete assessments without running tests.
---

# Faultline

Use the bundled engine: `python3 "<this-skill>/scripts/run.py" --root "<repo>" ...`. Resolve `<this-skill>` to this installed directory. It includes the same engine as the standalone `faultline` command and needs only Python 3.10+ and Git. No second skill is required for routine use.

Follow [setup, assess and report](references/assess.md). Configure actual test paths, resolve the cumulative diff base and exact tested head, and keep the user's branch and tracked files unchanged. Read Git objects; do not bootstrap the application. Every readable configured test stays eligible. Do not invent scores, generate test descriptions or prefilter candidates.

Start with the diff. If a dependency, external patch, inherited implementation or opaque switch leaves behavior unexplained, gather the smallest verifiable source evidence using [context gathering](references/context.md). Handle mixed changes component by component. Ordinary API use alone does not require enrichment. Never send this skill, investigation transcripts or a codebase overview as Jev context.

Prepare offline, inspect the work estimate, then run `assess`. Target under $0.50 in Jev usage per PR snapshot and stop before $0.90, respecting any smaller user budget. Use the pinned model's dated price and maximum billable request input to derive a conservative request ceiling; follow [budget arithmetic](references/benchmark.md#spending-budget). Count gates, scoring, retries and earlier attempts together. The engine persists the run-wide attempt count; it does not enforce a dollar limit. Unknown usage is not free. Do not silently drop evidence to fit.

New assessments are fresh by default. `assess --resume <run-id>` retains completed answers and prior attempts. `--reuse-cache` is an explicit optional optimization. Explain incomplete evidence and full-suite fallbacks rather than retrying indefinitely.

Return the HTML report and run ID. Show 10/25/50% RUN/OMIT proposals, assessed/unresolved counts, tokens, dated input cost, and engine/inference time. Separate fresh, resumed and reused answers. Agent investigation and installation are outside the engine clock; their unmeasured costs remain unknown. Relevance is not failure probability, coverage or measured CI savings.

Shadow analysis runs no tests and changes no CI. Native discovery can load application code and needs separate authorization. Read [execution](references/execution.md) only when explicitly requested; execution currently runs full suites.

Credentials load from `TYPESAFE_API_KEY`, repository `.faultline/.env`, then root `.env`. The user enters keys locally. Never request or display them, and never disable TLS verification. Selected change evidence and test source go to Jev.

For outcome evaluation, freeze proposals before inspecting CI results; follow [outcome assessment](references/benchmark.md#assess-outcomes). Repeated attempts are not independent cases and unexecuted tests are not passing. Generating a report never publishes a comment.

Contributors changing Jev questions, evidence, transport or performance experiments should use the `typesafe-ai` skill and [Jev guidance](references/jev.md), or its official-documentation fallback. Routine assessment uses the bundled contract. The faster pooled/Noul experiment is not the shipped evaluator. Change source and reinstall; never patch an installed skill copy.
