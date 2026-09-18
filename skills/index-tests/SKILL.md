---
name: index-tests
description: Build or update Faultline's inspectable semantic test catalog using the repository's own test discovery tools and source evidence. Use when preparing tests for semantic ranking or inspecting their Faultline profiles.
---

# Index tests with Faultline

You are the repository adaptation layer. Discover tests using the project's conventions and available runner inventory, then describe the behavior each test actually establishes. Faultline does not maintain framework-specific discovery adapters.

Read [the index contract](references/index-schema.md) before writing the catalog. The deterministic helper ships in the sibling `rank-tests` skill at `../rank-tests/scripts/run.py`. Both skill directories must be installed together. Run it with Python 3.10+; no packages or MCP server are needed. An installed `faultline` command exposes the same interface.

## Workflow

1. Read repository instructions and identify test suites, runner configuration, and how each runnable case is addressed. Prefer the runner's discovery/list mode or existing inventory. Do not execute the suite merely to discover tests. Discovery can load project code; follow repository execution constraints.
2. Run `python3 <helper> --root <repo> init`, then `index-status`. Inspect existing profiles before regenerating them. Rediscover the inventory so newly added and removed tests are accounted for.
3. Use exact runner identities including suite, parameters, and browser/project variants where those distinguish cases. Do not guess identities from prose or merge distinct cases with the same display name. If only file-level discovery is available, record that granularity and limitation instead of pretending to enumerate individual tests.
4. Preserve unchanged descriptions. For changed/new tests, use existing titles, steps, comments, and assertions where sufficient. Inspect setup and helpers when needed to understand the actual assertion. Describe demonstrated behavior; distinguish explicit coverage from assumptions. Include relevant setup/helper paths in `context_sources` so their changes invalidate the description.
5. Write a **complete discovered inventory** to `.faultline/index.draft.jsonl`, using the contract below. Unchanged entries may be copied verbatim. For regenerated entries omit `source_hash`; the helper calculates it. Do not copy an old hash onto a changed description or source.
6. Run `index --input <draft> --agent <actual-agent-name>`. This validates identities/paths, computes hashes, preserves unchanged entries, and removes omitted IDs. Use `--rewrite` only for an intentional review of unchanged descriptions or an indexing-policy change. Never submit a partial inventory as a complete replacement; finish discovery or explain the blocker while retaining the existing index.
7. Report catalog size, additions/changes/removals, suite coverage, and unresolved discovery limitations. Use `index show` or `explain-test <id>` for inspection.

All generated repository data belongs under `.faultline/`, which the helper locally ignores. No project taxonomy is needed. Skills may use runner XML/JSON inventories or source parsers as tools; framework details stay in the agent's workflow, not Faultline's ranking code.

When indexing for a historical experiment, do not use failure output, later fixes, or debugging discussion to improve descriptions before prediction. Record whether the index represents the tested revision or the current checkout. A current index is exploratory evidence and can contain suite drift.
