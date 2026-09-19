# Faultline implementation and validation plan

Faultline is an agent-native semantic test-ranking plugin, distributed as an Agent Skill and native plugins. The agent understands repositories and gathers evidence; Jev provides bounded relevance judgments; deterministic code owns ranking, caching, and measurements.

## Architecture and boundaries

- The agent handles discovery, source understanding, stable runner identities, Git/hosting operations, historical-result interpretation, and miss analysis. There are no framework adapters or hosting clients in the core.
- One self-contained `faultline` skill includes indexing, ranking, and reporting workflows plus a standard-library-only Python helper. Scripts and references stay inside the skill so selective Skills CLI installation is complete. An optional Python package exposes the same CLI. No MCP server or hosted service is required.
- Indexing produces `.faultline/index.jsonl`. Ranking receives generic profiles and structured change input. Exact runner locators remain available for future agent/CI execution policies.
- The default interaction analyzes one PR/MR, including relevant historical snapshots and attempts. A larger historical sample is an explicit request, not an automatic scan.
- Initial behavior is ranking and local reporting. Test execution, selective validation, test budgets, and CI modification remain outside the proof of concept.

## Stage 1 — Agent-generated test understanding

Implemented:

- The indexing workflow teaches the agent to read repository instructions, discover actual executable tests, use readable labels/source, inspect necessary setup, and describe only demonstrated behavior.
- Generic profile contract: required `id`, `source`, `description`; optional `runner`, `locator`, `metadata`, and `context_sources`. The helper computes source hashes and records skill/agent provenance.
- Incremental indexing preserves unchanged entries, replaces changed/new entries, and removes tests omitted from a complete rediscovered inventory. Full-file hashes conservatively invalidate sibling cases. Declared setup/helper sources also affect hashes.
- `index-status`, `index show`, and `explain-test` make the catalog inspectable. Discovery completeness and undeclared dependencies remain the agent's responsibility.

Acceptance: demonstrate complete discovery and incremental updates in a real repository; spot-check descriptions and parameterized/duplicate-name identities. The offline fixture tests cover preservation, changes, removals, invalid paths, and stale inputs. Real-repository semantic quality is still to be validated.

## Stage 2 — Fixed Jev evaluation and reproducible ranking

Implemented:

- The ranking workflow gathers cumulative PR/MR context and the actual tested revision. Revision IDs are provenance, not a standalone commit-ranking UX.
- Versioned evaluator `relevance-v1`, using a fixed Choice question and five definitions: irrelevant, weak, plausible, strong, direct. Initial model: `jev-1.13.0`, configurable only as a pinned version.
- Probability validation, expected relevance scoring with values 0–4, and deterministic test-ID tie-breaking. The agent never modifies scores or order.
- `rank` / `jev-evaluate` accept structured change/catalog files, expose a network-free dry run, cache each test judgment, and save full probabilities plus a readable ranking. Cache identity includes relevant change input, snapshot, profile, question/schema, and model configuration.
- Complete predictions are frozen with an integrity hash and full source inputs. Partial attempts remain inspectable and resume from completed pair predictions. Integrity checks detect accidental edits, not dishonest agent attestations.
- Jev transport uses serial paced calls, an explicit request ceiling including retries, bounded backoff for rate limiting/overload, persisted cooldowns, and no automatic retry of ambiguous connection failures. Oversized context is rejected rather than silently truncated. Credentials come from the environment or local `.env` files, are loaded only for live evaluation, and never enter saved evidence.

Acceptance: inspect rankings for several real changes; verify unrelated tests score low and relevant cross-behavior tests appear high. Live service access and ranking quality remain unverified. Offline tests exercise the HTTP contract, invalid probabilities, interruption/reuse, request limits, model versions, and credential-safe errors.

**Milestone 1:** an installable self-contained skill, inspectable incremental catalogs, one-change semantic ranking, probability evidence, deterministic order, and local caches. Code and skill packaging are implemented; real-change validation is the next experiment.

## Stage 3 — Historical evidence without hindsight

Implemented as skill workflow and structured contracts:

1. Select a PR/MR and snapshots independently of failures. Read only outcome-blind intent/diff and run identity/revision metadata.
2. Build/freeze each complete prediction before reading conclusions, artifacts, debugging comments, or test outcomes.
3. Retrieve existing results through the agent's available tools, without triggering workflows. Preserve run IDs, attempts, tested snapshots, collection completeness, and evidence locations.
4. Normalize outcomes into the generic schema. Require explicit test identities and evidence for non-unknown failure labels. Keep ambiguous matching and missing tests visible.
5. Classify confirmed regressions, likely flakes, infrastructure, baseline, and unknowns. Do not equate a red workflow with a regression or a passing retry with proof of flakiness.

Historical context must match the tested snapshot, including synthetic merge revisions when applicable. Omit edited PR text if its pre-outcome form is unavailable. Do not substitute a final fixed diff. A current test index is explicitly exploratory because of suite drift.

The script validates declared outcome-blind provenance and requires an outcome-collection timestamp after the completed prediction. It cannot independently prove what an agent has seen. A contaminated agent context must not claim blindness; use a genuinely fresh allowed context or disclose that the experiment is invalid.

Hosting calls are the agent's responsibility: serial authenticated requests, local reuse, explicit refresh, a finite collection budget (default 100 calls), pagination accounting, and honoring provider backoff/reset instructions. Jev's request ceiling is independently enforced by code.

Acceptance: one real PR/MR with multiple commits and attempts produces separate applicable predictions and traceable outcome records. Missing/expired artifacts, CI downtime, and incorrect revision mappings remain exclusions or limitations, not false successes.

## Stage 4 — Evaluation and reports in the same interaction

Implemented:

- An agent request to analyze one PR/MR runs the complete skill workflow. Users need not manually invoke indexing, ranking, comparison, and report commands.
- `evaluate` compares a complete frozen prediction with subsequently collected outcomes and automatically saves `findings.json`, `report.json`, and `report.md`. Updating classifications recalculates measurements without repeating unchanged Jev calls.
- Baselines use identical catalogs: lexical cosine similarity over words, shared-path proximity, deterministic seeded random order, and verified historical execution order when available.
- Metrics distinguish hit rate from failing-test recall at 1, 5, 10, 20, 50, plus first-failure positions. A confirmed failure missing from the catalog excludes that run's metrics to avoid optimistic recall.
- Time to Semantic Failure is a serial duration sum, available only with every needed duration. Queueing and infrastructure downtime are excluded. Parallel/unknown scheduling is not presented as observed wall-clock improvement.
- Per-case reports expose coverage, classifications, exclusions, complete rankings, and worst misses. Green/unknown-only evidence says regression-detection performance cannot be assessed.
- Offline `report --prediction` regenerates a case report. Unscoped `report` aggregates saved evidence, counting one earliest eligible case per PR/MR and separating repositories/evaluator configurations/index hashes/random seeds. Repeated attempts do not increase denominators. Recall is macro-averaged; p90 is omitted below ten cases.
- The agent adds evidence-based narrative and investigates misses without changing the authoritative JSON measurements. Improvements after inspecting outcomes belong to a new experiment, preserving the original frozen result.

Acceptance: a real single-PR request ends with an understandable case report and its evidence; a second case joins the aggregate without repeated downloads or inference. Offline tests cover this pipeline and report generation, including no eligible regressions, reruns, wrong revisions, missing durations, multiple PRs, and evaluator separation.

**Milestone 2:** reproducible historical evaluation with evidence-based labels, baselines, and local reports. The deterministic pipeline is implemented and tested with synthetic fixtures. Real-history usefulness remains to be established.

## Distribution and validation

- The Skills CLI installs `skills/faultline/`, including all scripts and references. A standalone copied bundle is tested with Python third-party packages disabled. The custom Python installer has been removed.
- Native Codex and Claude Code manifests and repository marketplace catalogs wrap the same skill. A portable Agent Plugins manifest identifies the package. Python package installation remains optional contributor tooling. Remote installs require the packaging revision to be pushed; public-directory publishing is separate future work.
- The README explains the project; `docs/install.md` documents setup and invocation. Schema/behavior details live with the skills.
- No implementation test uses a live Jev key or downloads private repository history.
- Next: install into a separate repository, review the index, run an outcome-blind real-change ranking, and evaluate the resulting report. Record failures of the workflow before expanding the sample.

## Success criteria and later work

Continue only if relevant failures consistently move earlier and semantic ranking adds value over simple baselines. Keep tuning separate from future untouched assessment cases; do not claim general success from a hand-selected case or a green run. A negative result is useful.

If evidence supports it, later stages can introduce full-suite execution ordering, a fast feedback lane with a complete-suite backstop, explicit test budgets, and eventually selective validation. Shared histories, hosted/MCP services, embedding baselines, candidate retrieval, historical-revision indexing, and additional coverage/runtime/reliability signals remain future work. Agent and CI integrations should consume the same inspectable catalog and ranking evidence.
