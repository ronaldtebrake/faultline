# Work with Jev using TypeSafe guidance

Use the installed [`typesafe-ai` skill](https://github.com/typesafe-ai/skills) when designing or reviewing questions, shaping evidence, interpreting scores, or experimenting with Jev cost and latency. In the TypeSafe plugin it is named `typesafe:typesafe-ai`. Read only the guidance relevant to the task; ordinary discovery and offline report generation need no additional model calls.

If the skill is unavailable, consult the official docs directly. Its absence does not block the bundled CLI. Keep provider guidance in the agent's working context; never send the skill or documentation as test evidence to Jev.

## Read current guidance

Start with the [documentation index](https://docs.typesafe.ai/llms.txt), then the relevant pages:

- [State](https://docs.typesafe.ai/concepts/state) and [question primitives](https://docs.typesafe.ai/primitives) for evidence and judgment design.
- [Python SDK](https://docs.typesafe.ai/sdk/python) or [HTTP API](https://docs.typesafe.ai/api) for integration changes.
- [Parallel questions](https://docs.typesafe.ai/cookbooks/parallel_questions) for batching, and [models](https://docs.typesafe.ai/models) for current limits and pricing.

Read the limitations for the pinned model linked from the models page. If live docs are unavailable, use installed SDK types and previously verified contracts, disclose the limitation, and avoid inventing current limits or prices.

## Apply it to test impact analysis

- Define the judgment before choosing a primitive: Noul estimates whether a proposition is true; Choice compares alternatives; Score measures a described degree. Keep model judgments separate from execution policy. A Noul impact probability is not a failure probability, and a maximum across fragments is not a calibrated whole-change probability.
- Give each question the source and relationships needed to answer it. Use named fields and explicit references; question IDs are not visible to Jev. Independent questions cannot see each other's answers. Keep dependency changes and the integration path needed to understand them together, without adding a general codebase overview. Follow [context gathering](context.md) for provenance and scope.
- Distinguish risk to a product integration from behavior exercised by a particular test. A fixed-input helper test need not cover its production caller. High integration risk with low test scores calls for checking executable coverage and evidence gaps; it does not justify inflating scores or declaring the change safe.
- Reduce repeated source before removing evidence. Compare sharing a change across tests with sharing a test across change windows. Preserve every original test–change evidence pair and verify those associations. A smaller payload or retained source bytes alone does not establish equivalent judgments.
- For transport changes, evaluate the official SDK and connection reuse with bounded concurrency. All workers and retries must share rate, elapsed-time, and cost limits. Account for SDK retries explicitly, reserve uncertain usage, honor provider cooldowns, and stop dispatch on billing/authentication failures or ambiguous failures requiring investigation. Preserve TLS and per-answer validation. Follow the existing [spending budget](benchmark.md#spending-budget).

## Validate before adoption

Separate transport, request layout, context, and evaluator changes so their effects can be assessed. Compare identical-input repeatability, threshold changes, input usage, scoring time, and failing-test recall at comparable execution budgets. More or fewer proposed tests is inconclusive without outcomes or source review. Keep development cases separate from later assessment cases; never feed outcomes into scoring inputs.

Measure elapsed time from the initial PR assessment request through context investigation, source collection, request preparation, scoring, and report completion. Record phase timings separately; mark unmeasured phases as unknown. Scoring latency or a sum of selected scripted steps is not end-to-end latency. Label fresh versus reused answers. Keep unresolved evidence and existing execution guards visible. Use dated pricing and include failures/retries in costs; a partial assessment cannot establish the price of a complete PR.

The shipped benchmark uses five-level Choice judgments. Noul scoring, pooled transport, and mixed request layouts have been explored in separate experiments; they are not implicitly enabled by this guide. Treat evaluator changes as versioned experiments and do not transfer thresholds between primitives without validation. Consult the installed CLI and current source for supported behavior.
