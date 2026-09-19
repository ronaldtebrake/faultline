# Test impact analysis with CodeGraph and Jev

Start with [the reference benchmark](../skills/faultline/references/benchmark.md). It compares CodeGraph, Jev, and graph-enriched Jev on one frozen PR/MR snapshot, then imports existing CI outcomes to assess their value. The guide includes the shared main-branch baseline workflow, API budgets, and report interpretation.

The [graph workflow](../skills/faultline/references/graph-workflow.md) describes suite configuration, graph import/export, existing selection commands, and explicit execution. The graph is the primary source/test index. Both guides travel with the installable skill; the Python CLI and bundled entry point use the same engine.

[PLAN.md](../PLAN.md) tracks real-project validation and later optimization experiments. Shadow analysis executes no tests. Explicit `run --execute` evaluations run the full configured suites; selective CI execution remains future work.
