# Faultline

**Faultline is an agent-native semantic test-ranking plugin. It teaches your coding agent to understand your test suite, then uses a fast evaluation model to rank which tests are most likely to expose regressions from a change.**

Faultline ships as one self-contained Agent Skill, with native Codex and Claude Code plugin packaging. Its evaluation scripts travel with the skill. It is a proof of concept: the mechanics are implemented and tested offline, while ranking quality still needs to be measured on real changes.

## Why this exists

Large test suites can take a long time to reveal a regression. The test that detects the problem may execute near the end, leaving developers and coding agents waiting for useful feedback.

Paths, dependencies, coverage, and failure history provide useful signals. But a change can affect related behaviors across those boundaries. Faultline investigates whether comparing a change directly with the behavior protected by each test can bring relevant failures forward.

## The agent understands the repository

Your coding agent discovers the test framework, reads the tests and their setup, and creates an inspectable description of what each test demonstrates. It uses the repository's own tools to identify executable tests and retrieve change context.

This makes the agent the adaptation layer. Faultline does not need its own PHPUnit, Jest, Playwright, or other framework adapters. Each test becomes a generic profile with an exact identity, source, description, hashes, and provenance. Unchanged profiles can be reused.

## Jev judges relevance

Jev receives the change context and a test's description, then answers a fixed question: **How much regression-detection value does this test have for this change?**

Faultline converts probabilities over five relevance levels into a deterministic ranking. The agent can explain the result, but cannot change the scores or reorder tests based on its intuition. Full probability distributions remain available for inspection. A relevance score is not a calibrated probability that a test will fail.

```text
Agent: repository understanding → test catalog + change context
                                           ↓
                              Jev: bounded relevance judgment
                                           ↓
                             Faultline: deterministic ranking
                                           ↓
                           Agent: interpret evidence and misses
```

## Install

Using the [Skills CLI](https://github.com/vercel-labs/skills), run this from the repository you want to analyze:

```bash
npx skills add git@github.com:ronaldtebrake/faultline.git --skill faultline
```

Choose your agent when prompted, or add `--agent codex` or `--agent claude-code`. Private repository access uses your existing Git credentials. Python 3.10+ is needed to run the bundled evaluator; no pip install or third-party Python packages are required.

Native Codex and Claude Code plugin installation, local development, and API setup are covered in [the setup guide](docs/install.md). Choose one installation method.

## One skill, the whole workflow

Ask your agent to “Use Faultline to index this repository’s tests,” then “Use Faultline to analyze PR 123 and save a report.” Indexing preserves exact runner identities and describes behavior supported by the source.

For historical analysis, the agent freezes the ranking before collecting outcomes, compares the evidence, and saves findings and a report in the same interaction. Start with one PR/MR; additional cases accumulate gradually. Saved reports can be regenerated without API calls.

## Evidence before execution policy

Historical evaluation asks where confirmed failing tests appear in the ranking. Faultline compares those positions with lexical, path-based, seeded-random, and verified historical-order baselines. Where durations permit, it estimates serial time to a known failure without claiming that serial sums describe parallel CI wall-clock time.

Predictions are frozen before the agent reads outcomes. Reports distinguish confirmed regressions, likely flakes, infrastructure failures, baseline failures, and unknowns. Missing evidence is never treated as a passing test. A single PR is a case study; a green run cannot establish that low-ranked tests were unnecessary.

The initial release ranks and reports. It does not run tests, skip tests, trigger workflows, or modify CI. The catalog, runner locators, and structured rankings give both agents and future CI integrations a reusable basis for execution ordering, fast feedback jobs, and eventually explicit test budgets—if the evidence supports those policies.

## Local data and external evaluation

Catalogs, cached predictions, and reports stay under the target repository's ignored `.faultline/` directory. Selected change text and test descriptions are sent to Jev using `TYPESAFE_API_KEY`. Requests are paced, bounded, cached, and resumable. Repository history collection uses the agent's existing authenticated tools.

The implementation and remaining validation work are tracked in [PLAN.md](PLAN.md). Installation, usage, and testing instructions are in [the setup guide](docs/install.md).
