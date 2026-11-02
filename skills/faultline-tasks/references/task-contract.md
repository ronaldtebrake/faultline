# Task input contract, version 1

Use a reviewed Faultline commit containing `tasks plan` and `tasks run`. Older
graph-only pins do not include task-result caching. Install through an existing
dependency environment or `ronaldtebrake/faultline/actions/setup@<full-commit-sha>`.
Git and Python 3.10+ are required.

## Configuration

This synthetic example can stand alone; existing `suites`, `scope` and `evaluator`
fields can coexist unchanged:

```json
{
  "schema_version": 2,
  "repository": "example/product",
  "task_graph": {
    "version": 1,
    "context": {"runtime": "node-22.20.0", "fixtures": "tracked-local-only"},
    "global_inputs": [".github/**", "package.json", "package-lock.json"],
    "ignored_inputs": [],
    "env": [],
    "tasks": {
      "shared": {"inputs": ["packages/shared/**"]},
      "api-tests": {
        "inputs": ["apps/api/**"],
        "depends_on": ["shared"],
        "cwd": "apps/api",
        "command": ["npm", "test"],
        "env": ["TEST_MODE"],
        "cache": true
      },
      "docs-check": {
        "inputs": ["docs/**", "tools/check-docs.mjs"],
        "command": ["node", "tools/check-docs.mjs"],
        "env": [],
        "cache": true
      }
    }
  }
}
```

Versions above are illustrative, not runtime recommendations. Record actual
runtime/OS image, dependency installation and fixture identities. For mutable CI
runner images, declare a version/digest via `env`, or leave caching disabled.
Environment variables must be present, even with empty values. Values are hashed
together and never written into plans or cache records. Command logs need the
same access restrictions as normal CI logs; they can contain command output.

| Field | Meaning |
| --- | --- |
| `version` | Exactly `1`. |
| `context` | String-to-string runtime/fixture identity map, shared by all tasks. Required and nonempty for cacheable checks. Declarations do not verify installed runtimes automatically. |
| `global_inputs` | Additional tracked input patterns affecting every task. |
| `ignored_inputs` | Exempts otherwise unmapped files from global fallback; cannot remove explicitly owned/global inputs. Default empty. |
| `env` | Environment names affecting every task. Default empty. |
| task `inputs` | Positive repository-relative patterns. Default `['**']`; empty allowed for aggregation nodes. |
| `depends_on` | IDs whose fingerprints are included transitively. Dependencies execute first; cycles/missing IDs are errors. |
| `command` | Argument array executed directly. Omit for an input-only node. Shell syntax requires an explicit shell. |
| `cwd` | Repository-relative working directory, default `.`. |
| `cache` | Executable checks default `false`. Opt in only for deterministic checks with no required output side effects. |
| task `env` | Additional environment names. Must be explicitly present, including `[]`, for cacheable checks. |
| `timeout_seconds` | 1–86400, default 3600. |
| `description` | Optional metadata. The committed configuration still participates in every fingerprint. |

Patterns use case-sensitive shell-style matching on repository-relative paths:
`*` can cross `/`, `app/**` includes descendants. No negative patterns, brace
expansions or implicit cwd prefixes. Tracked path names, contents and executable
modes participate. Added/deleted/renamed files change fingerprints. Internal
symlinks include their tracked targets and linked-directory membership. External,
untracked or cyclic symlink targets and submodule inputs disable reuse for their
task and dependents.

`faultline.json` always affects every task. Every tracked file not owned by any
task, covered by global inputs or explicitly ignored becomes a global input.
This catches unclassified configuration. It cannot detect missing edges between
two already-owned components; review those relationships explicitly.

Input nodes need no runtime adapters. Splitting Behat into jobs does not make
their application inputs independent. All can depend on one application node.

Fingerprints also bind repository identity, task definitions, transitive hashes,
OS family/architecture and engine identity. Commit SHA is provenance, not a cache
key: unchanged tasks can reuse successes after other components change. Set a
stable repository ID when remote URLs differ across clones. Planning reads Git
trees and supports sparse checkouts; execution needs clean materialized inputs.

## Commands and evidence

```sh
faultline tasks plan --base <merge-base> --output .faultline/tasks-plan.json
faultline tasks run --task api-tests
faultline tasks plan --task api-tests
faultline tasks run --task api-tests --reuse
```

`plan` executes nothing. The optional base compares exact commits; resolve the
merge base yourself. An unavailable base is reported without suppressing tasks.
Checks report `run`/`reuse`, fingerprints, changed inputs/dependencies, reasons
and prior successful revision/duration. Input nodes report `inputs`. A matching
plan does not authorize execution changes. `--github-summary` appends a table.

`run` executes every requested check and prerequisite, including cache hits.
It freezes a plan, captures command logs and records outcomes under ignored
`.faultline/task-runs/`. Stable successful cacheable checks create sealed records
under `.faultline/task-results/`. Failed dependencies block dependent commands;
independent checks can continue. Failures return a nonzero CLI exit code.

`run --reuse` skips only matching successful checks. Missing, invalid and
incompatible records execute the full command. Shadow failures replace local
successes with rejections. Remote snapshots are immutable; investigate any
contradiction before adoption. This is input-contract caching, not protection
against flaky or incompletely declared behavior.

`--cache-dir` accepts a trusted directory. Seals detect corruption, not ownership.
Never restore arbitrary PR artifacts into privileged caches. Records contain
metadata, not source or environment values. Build outputs are not restored.

## GitHub integration

Keep existing runtime, dependencies and services. Replace the full command step
with the action in `shadow` mode, rather than running the same command twice.
Preserve matrices and required checks. Planning can run in a separate job.

```yaml
- uses: actions/checkout@v5
  with:
    fetch-depth: 0
- uses: actions/setup-python@v6
  with:
    python-version: '3.12'
# Keep existing runtime/dependency/service preparation here.
- uses: ronaldtebrake/faultline/actions/tasks@<reviewed-full-commit-sha>
  with:
    tasks: api-tests
    mode: shadow
  env:
    TEST_MODE: integration
```

`plan` restores/previews only; `shadow` always runs; `reuse` explicitly adopts
reuse. The action restores a recent GitHub cache archive, validates individual
records, saves an updated snapshot including rejections and uploads reports/logs.
Job summaries show decisions and actual outcomes. Restore misses run cold.

GitHub cache branch access rules apply: PRs can read eligible base/default branch
caches; unrelated branches may be inaccessible. A sibling-branch miss does not
mean fingerprints are wrong. Keep publishers under normal repository trust
rules. Never execute untrusted checkout commands in `pull_request_target`.

Task reuse occurs after runtime setup in this first action. Avoiding runner
provisioning is separate scheduling work; do not claim those savings yet.
Source graph baselines and JUnit files do not automatically become successful
task records: the wrapper binds an actual command run to its inputs.
