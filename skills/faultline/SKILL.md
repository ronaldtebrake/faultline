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

Follow [setup, assess and report](references/assess.md). Configure actual test paths and resolve the cumulative merge base and exact tested head. `assess --base <base>` and `select --base <base>` use the offline dependency graph by default. They read committed source, reuse parser facts and accept validated runtime observations. No key, application bootstrap or Jev request is needed. Keep full CI running while validating the graph.

Return the HTML report and run ID, affected paths, mandatory-rule retentions, unresolved tests, parser reuse and preparation time. Unresolved means no known dependency path; it does not mean safe to omit. Graph reports cannot be exported as selective execution manifests. `report --run <id>` and graph resume reopen frozen evidence offline. A new run rebuilds only invalidated source facts.

Jev is optional and off. Use it only when the user requests semantic scoring with an authorized budget. `assess --jev` chooses Noul and retains graph-positive tests before scoring unresolved tests. `--evaluator choice-v1` additionally selects the legacy Choice research contract. A saved Jev run still needs `--jev` on resume; credentials or evaluator configuration alone never enable inference. Research `benchmark` and `benchmark-recover` require `--jev` except for offline `--prepare`.

For authorized Jev work, start with the diff and follow [context gathering](references/context.md) where behavior is unexplained. Prepare offline, inspect the estimate and respect the user's smaller spending limit. Target under $0.50 and stop before $0.90 per snapshot; apply [budget arithmetic](references/benchmark.md#spending-budget). Count retries, earlier attempts and unknown usage. Never silently drop evidence to fit. PR impact scores remain fresh; Choice has an explicit `--reuse-cache` option. Relevance is not failure probability or measured CI savings.

The optional [surface relationship experiment](references/dependencies.md) requires `--jev`, a reviewed `--dependency-catalog` and an explicit `--relationship-threshold`. It is separate from graph facts and PR impact scores. Outcomes never enter inference inputs.

Shadow analysis runs no tests and changes no CI. Runtime collection belongs in an authorized existing full test run. Native discovery may load application code. Read [execution](references/execution.md) and [selective CI](references/ci.md) only for explicitly requested execution experiments. During graph validation, keep full suites. With an enabled [push-readiness hook](references/hooks.md), assess the cumulative diff and publish `ci-submit --full` before a separate push. Do not require paid scoring to publish full execution or increase budgets.

Credentials load from `TYPESAFE_API_KEY`, repository `.faultline/.env`, then root `.env`. The user enters keys locally. Never request or display them, and never disable TLS verification. Selected change evidence and test source go to Jev.

For outcome evaluation, freeze proposals before inspecting CI results; follow [outcome assessment](references/benchmark.md#assess-outcomes). Repeated attempts are not independent cases and unexecuted tests are not passing. Generating a report never publishes a comment.

Contributors changing Jev questions, evidence, transport or performance experiments should use the `typesafe-ai` skill and [Jev guidance](references/jev.md), or its official-documentation fallback. Routine assessment uses the bundled contract. The default is the offline graph. Opt-in `assess --jev --evaluator noul-v1` uses the experimental Noul contract with bounded parallel HTTP; its scores and thresholds must not be substituted for Choice. Change source and reinstall; never patch an installed skill copy.
