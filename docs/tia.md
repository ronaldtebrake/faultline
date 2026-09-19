# CodeGraph-based test impact analysis

The [graph workflow](../skills/faultline/references/graph-workflow.md) documents the implemented architecture, installation, configuration, PR/MR flow, artifact sharing, report-only shadow mode, explicit execution, and reports.

The [shared-catalog reference](../skills/faultline/references/shared-catalog.md) covers source-only discovery, optional native enrichment, whole checks, reviewed descriptions, generic inventory contracts, and optional coverage import. Both references travel with the installable skill. The Python CLI and bundled entry point use the same engine.

[PLAN.md](../PLAN.md) tracks real-project validation and future selective execution. Shadow mode executes no tests. Only explicit `run --execute` evaluations run the full configured suites.
