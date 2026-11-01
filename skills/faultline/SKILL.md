---
name: faultline
description: Install Faultline and configure GitHub CI, inspect readable dependency graphs and tests affected by file changes, or assess PR test impact with optional Jev scoring. Use for Faultline setup, dependency review and test-impact reports.
---

# Faultline

Use the bundled engine: `python3 "<this-skill>/scripts/run.py" --root "<repo>" ...`. Resolve `<this-skill>` to this installed directory. It includes the same engine as the standalone `faultline` command and needs only Python 3.10+ and Git. No second skill is required for routine use.

For installation or GitHub CI setup, follow [installation](references/install.md).
Prefer the packaged CLI and commit-pinned setup action for consumers; do not copy
the engine into their repositories. Configure source inspection and baseline
validation first, with existing tests retained. Installation and graph queries
need no Jev key or assessment budget. Other CI providers can use the same CLI;
their workflow integration is not supplied yet.

For "what tests depend on this file?", use `graph affected --file <path>` and
read [dependency inspection](references/dependencies.md). For actual commit
changes, use `graph compare`. Return the JSON explanation and unresolved paths;
these commands do not execute tests or call Jev. Use the assessment guidance
below only when the user requests semantic scoring.

Follow [setup, assess and report](references/assess.md). Configure actual test paths, resolve the cumulative diff base and exact tested head, and keep the user's branch and tracked files unchanged. Read Git objects; do not bootstrap the application. Every readable configured test stays eligible. Do not invent scores, generate test descriptions or prefilter candidates.

Start with the diff. If a dependency, external patch, inherited implementation or opaque switch leaves behavior unexplained, gather the smallest verifiable source evidence using [context gathering](references/context.md). Handle mixed changes component by component. Ordinary API use alone does not require enrichment. Never send this skill, investigation transcripts or a codebase overview as Jev context.

Prepare offline, inspect the work estimate, then run `assess`. Target under $0.50 in Jev usage per PR snapshot and stop before $0.90, respecting any smaller user budget. Use the pinned model's dated price and maximum billable request input to derive a conservative request ceiling; follow [budget arithmetic](references/benchmark.md#spending-budget). Count gates, scoring, retries and earlier attempts together. Choice persists a request ceiling; opt-in Noul also enforces a run-wide dollar ceiling. Unknown usage is not free. Do not silently drop evidence to fit.

New assessments are fresh by default. `assess --resume <run-id>` retains completed answers and prior attempts. `--reuse-cache` is an explicit optional optimization. Explain incomplete evidence and full-suite fallbacks rather than retrying indefinitely.

For explicitly requested dependency reuse, read [incremental dependencies](references/dependencies.md). Opt-in Noul `--dependencies` retains tests reached by positive source/runtime paths without scoring them; remaining tests still receive assessment. Dependency-selected tests have no invented probability. Runtime collection belongs in an authorized existing test run; source graph inspection executes no application code. Missing graph paths never authorize omissions.

The additional `--dependency-catalog` experiment caches separate test-to-surface relationships under reviewed application boundaries. It requires an explicit `--relationship-threshold`; never substitute the PR impact cutoff or infer complete ownership from a missing graph path. Keep declarations, routing contracts and setup evidence current, inspect uncovered changes, and compare with full CI before adopting omissions. `--fresh` supports an uncached relationship comparison. Outcomes never enter inference inputs.

Return the HTML report and run ID. Show 10/25/50% RUN/OMIT proposals, assessed/unresolved counts, tokens, dated input cost, and engine/inference time. Separate fresh, resumed and reused answers. Agent investigation and installation are outside the engine clock; their unmeasured costs remain unknown. Relevance is not failure probability, coverage or measured CI savings.

Shadow analysis runs no tests and changes no CI. Native discovery can load application code and needs separate authorization. Read [execution](references/execution.md) only when explicitly requested; the legacy `run` command executes full suites. For compact exports and selective PHPUnit, Behat and Playwright execution, read [selective CI](references/ci.md). Assessment alone never authorizes `ci-submit` or test execution. When the user enables the optional push-readiness workflow, follow [agent hooks](references/hooks.md): resolve the actual target branch, assess the cumulative merge-base-to-head diff within the existing budget, and confirm publication before a separate push. A published full fallback is available without scoring. Never silently bypass a hook or increase spending.

Credentials load from `TYPESAFE_API_KEY`, repository `.faultline/.env`, then root `.env`. The user enters keys locally. Never request or display them, and never disable TLS verification. Selected change evidence and test source go to Jev.

For outcome evaluation, freeze proposals before inspecting CI results; follow [outcome assessment](references/benchmark.md#assess-outcomes). Repeated attempts are not independent cases and unexecuted tests are not passing. Generating a report never publishes a comment.

Contributors changing Jev questions, evidence, transport or performance experiments should use the `typesafe-ai` skill and [Jev guidance](references/jev.md), or its official-documentation fallback. Routine assessment uses the bundled contract. The default remains Choice. Opt-in `assess --evaluator noul-v1` uses the experimental Noul contract with bounded parallel HTTP; its scores and thresholds must not be substituted for Choice. Change source and reinstall; never patch an installed skill copy.
