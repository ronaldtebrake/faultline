# CodeGraph-based test impact analysis

The [graph workflow](../skills/faultline/references/graph-workflow.md) documents the implemented architecture, installation, configuration, PR/MR flow, artifact sharing, report-only shadow mode, explicit execution, and reports.

The graph is the primary source/test index. Initialize a baseline, share it through artifact import/export, and derive immutable branch snapshots for each PR. The [legacy catalog reference](../skills/faultline/references/shared-catalog.md) retains older maintenance commands and the native/generic inventory and optional coverage contracts. Both references travel with the installable skill. The Python CLI and bundled entry point use the same engine.

[PLAN.md](../PLAN.md) tracks real-project validation and future selective execution. Shadow mode executes no tests. Only explicit `run --execute` evaluations run the full configured suites.
