# Dependency inspection interface

Integrations should invoke the installed `faultline` executable and consume JSON,
not import Python internals. GitHub's setup action exposes `FAULTLINE_CLI` for this
purpose. Python is the current implementation; a future Rust or Go executable
can preserve this interface without copying an engine into consumer repositories.
No performance improvement from another language has been established yet.

## Default assessment

`assess --base <merge-base> --head <head>` and `select --base <merge-base>`
produce a sealed schema-2 `graph-assessment` document with evaluator `graph-v1`.
The returned `path` points to frozen evidence. `tests` contains opaque target
IDs, `affected`/`required`/`unresolved` status, reasons and positive paths;
`summary` counts these mutually exclusive statuses. `complete` describes the
configured inventory, not dependency coverage. `source_gaps` and `unknown_paths`
remain visible. `ci_policy` is `full_suite`, `execution` is `none`, and both
`coverage_complete` and `omission_authorized` are false. `jev_requests` and
`cost_usd` are zero. These documents cannot be exported as execution selections.

Graph facts reuse exact immutable inputs automatically. `--runtime` adds existing
validated observations; it never runs a collector. `--prepare` returns the graph
assessment without saving a run. `report --run <id>` and graph resume regenerate
reports from frozen evidence. `assess --jev` explicitly enables the optional Noul
contract with positive graph retention. Any paid run, including a resume,
requires `--jev`; stored configuration and credentials do not enable it.

## File impact

```sh
faultline --root /path/to/repository graph affected \
  --file src/price.ts --revision HEAD --output .faultline/impact.json
```

`--file` is a literal repository-relative path, repeatable for multiple inputs.
It is not a glob. `--revision` selects immutable committed source, defaulting to
`HEAD`; working-tree edits do not affect the result. `--base` optionally supplies
an older tree, allowing a deleted dependency's old path to explain a current test.
Validated runtime evidence can be supplied through repeatable `--runtime` paths.
That evidence must be compatible with every requested snapshot.

Successful output is one JSON object on stdout. `--output` saves the same object
as indented UTF-8 JSON. Operational errors go to stderr and return nonzero; a
successful query with unknown files is still a successful query, not an omission
decision. Consumers must inspect the evidence fields, not just the exit status.

| Version 1 field | Meaning |
| --- | --- |
| `schema_version`, `kind` | `1`, `dependency-impact`. Check these before consuming fields. |
| `repository`, `revision`, `base_revision` | Repository identity and exact resolved Git revisions. |
| `files`, `unknown_files` | Normalized requested files; paths absent from both inspected trees. |
| `affected` | Current configured target IDs with positive paths to requested files. |
| `unresolved` | Other current targets; absence of a known path does not prove independence. |
| `removed_targets` | Targets present only in the optional older tree; not runnable current tests. |
| `explanations` | Per affected target, one deterministic shortest path for each matching input/tree. |
| `inventory_complete` | Whether configured source inventory was complete; distinct from dependency coverage. |
| `snapshots` | Local paths to the immutable JSON graph documents used. |
| `preparation` | Parser/reuse operation counts, including any historical tree preparation. |
| `coverage_complete`, `omission_authorized` | Both `false`. This is positive evidence, not full coverage or permission to skip. |
| `execution`, `jev_requests` | `none`, `0`. Queries execute no application or test code and use no model. |

Each explanation records `input`, `snapshot` (`head` or `base`), `revision`,
`path` (test source through the dependency), and `edges` with `from`, `to`, `kind`
and `detail`. A test's own file has a one-node path and no edges. Multiple paths
can exist; one explanation does not enumerate every route or establish completeness.
Targets are configured source units, not a claim about every native test case.

Additive fields may appear; readers should ignore unknown fields. An incompatible
meaning or shape requires a schema version change. Target IDs and file paths are
opaque strings to consumers; do not reconstruct identities from colon splitting.

## Cache and change review

`graph build --output .faultline/graph.json` exports the full human/agent-readable
snapshot. Nodes, typed edges, target metadata, observations, gaps, revisions and
version metadata are ordinary JSON. Source facts and graph snapshots are also
stored under ignored `.faultline/dependency-graph/`. Do not hand-edit sealed cache
files: integrity and compatibility checks intentionally reject changed evidence.

`graph compare --base <commit> --head <commit>` reviews actual changed inputs,
added/removed edge counts, affected targets and runtime invalidation. Newly added
definitions can connect previously unchanged consumers, so the engine rebuilds
resolution while reusing exact-blob parsing. The graph's internal schema and
adapter versions may evolve independently of the versioned impact report.

A database is not required for the current JSON-backed implementation. Keep its
storage private and ignored; save selected synthetic reports for review when
needed. Baseline artifacts carry explicit source/engine identities and are
validated separately from the command output. Future storage or graph providers
must retain provenance and unknowns; inferred links must not become observed
test coverage merely through a format conversion.
