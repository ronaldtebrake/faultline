# Reference benchmark

Use this workflow to establish what CodeGraph and Jev contribute before changing retrieval, evidence size, or selection behavior. The commands use the installed `faultline` CLI; an agent can invoke the same commands through `python3 "<this-skill>/scripts/run.py" --root "<repo>"`.

## Prepare one PR or MR

Configure test source patterns and variants in `faultline.json` using [the setup reference](graph-workflow.md). Resolve the cumulative change's actual diff base and tested head through existing Git/hosting tools. Do not substitute current main for an older or stacked PR base. Full Git objects for both revisions must be available. Optional `--title` and `--description` provide the same pre-outcome intent to both Jev approaches. Omit historical PR text that was edited after outcomes or cannot be verified.

```bash
faultline benchmark --base <actual-base> --head <tested-head> --prepare --max-requests 100
```

Preparation builds fresh graphs for missing revisions and estimates uncached work for both Jev approaches. Inspect `preparation.status`, `preparation.blockers`, `preparation.eligible_targets`, and `graph_builds`. Exit 2 means the planned comparison is incomplete: graph failures, oversized evidence, incomplete inventory, or insufficient requests are visible before inference. A zero-request estimate with zero eligible targets is blocked, not a free completed benchmark. It invokes neither Jev nor a test runner. The estimate lists oversized or unreadable targets separately; they are not silently removed. The example request ceiling is shared across both approaches and is not a promise that 100 requests can finish the case.

When live inference is authorized within the configured or user-specified budget:

```bash
faultline benchmark --base <actual-base> --head <tested-head> --id PR-123 \
  --max-requests 100 --selection-seconds 120
```

Requests, including HTTP retries, share one ceiling. The inference deadline is also shared. Test cohorts use the same membership in both approaches when their whole inputs fit. The first approach alternates by cohort; a partial run never qualifies as a complete comparison. A fatal transport failure or interruption stops further network work. Identical subsequent invocations reuse exact-input cached answers; do not loop to reset a user's total authorized budget.

The reference sends whole supplied diffs, test files, and source matched by each suite's `description_inputs`. Graph-enriched assessments also receive all paths returned by the bounded graph query. Test source and setup are not summarized or split into arbitrary fragments. An oversized target stays unassessed. Jev handles bounded relevance judgments; it does not generate descriptions or establish measured coverage.

Reports distinguish configured source targets from native test cases. A file may contain datasets or scenarios. Native runners are unnecessary for analysis. Both Jev approaches assess all readable targets, including mandatory tests and sources without graph paths. Shared mandatory rules and prerequisites affect selections; positive structural hints alone do not force either semantic policy to select a target.

The command writes one immutable JSON case and one Markdown report in `.faultline/benchmarks/`. `--output <fresh-path.json>` selects another location without creating a second canonical copy. Exit 2 means an incomplete comparison was saved. Exit 1 indicates an error that prevented normal completion. Reports include exact versions, input evidence, request identities, probabilities, and limitations. The reference is an experimental comparator, not ground truth.

## When whole inputs do not fit

The default `--evidence-mode whole` preserves the whole-input comparator. Smaller batches cannot make a single oversized change/test/setup combination fit. Raising the request count cannot repair that failure either.

Use `--evidence-mode file-pairs` for a separately labeled experiment:

```bash
faultline benchmark --base <actual-base> --head <tested-head> \
  --evidence-mode file-pairs --prepare --max-requests 100

faultline benchmark --base <actual-base> --head <tested-head> \
  --evidence-mode file-pairs --max-requests 100 --selection-seconds 120
```

This mode groups complete `diff --git` sections into bounded change windows. Every eligible test is compared with every window. Each Jev question carries its own whole test source and, for the hybrid approach, the bounded file/symbol relationship context. Questions share the change state. Setup source identities are retained; their implementation bodies are not sent. Whole-input and file-pairs judgments have separate contracts and cache identities.

A target that cannot fit with even one complete changed-file section remains unassessed; no file or diff section is split at an arbitrary byte offset. A target is fully assessed only when all its planned windows return valid answers. Partial targets remain would-run. The diagnostic score is the strongest observed window judgment. Proposed omission requires every window's irrelevant probability to meet the policy threshold. This is not a calibrated cumulative-change probability: interactions across windows and unprovided setup implementations can be missed. Treat this as a distinct experiment, not a complete substitute for whole-input evidence.

A large suite may still need more than 100 requests. Preparation exposes that cost; it never raises the ceiling or authorizes repeated runs. Oversized test files remain blocked regardless of the request allowance. Keep the comparison partial until its declared evidence requirements are actually satisfied.

Graph snapshot preparation checks Git object sizes before exporting files. If it exceeds the configured local graph budget, the error names required and allowed bytes/files. Review `graph.max_source_bytes` and `graph.max_files` against the available local resources, or supply compatible exact-revision artifacts. Graph resource limits and Jev request limits are separate. Do not drop suites or source paths merely to clear a warning.

## CodeGraph without Jev

```bash
faultline select --base <actual-base> --head <tested-head> --graph-only
```

This saves a CodeGraph-only shadow proposal with zero Jev calls. Positive graph matches, mandatory rules, and graph gaps are shown separately. Missing structural evidence keeps affected targets would-run; a target with no graph match is labeled not suggested by the baseline. This report is not an execution plan. The ordinary `select` workflow retains its existing policy; use `benchmark` for the three-way reference comparison.

## Shared main-branch baseline

A trusted CI job can run this after a merge or push to main, with Python, Faultline, CodeGraph 1.6.0, and the committed suite configuration installed:

```bash
faultline graph build --revision HEAD --fresh --output .faultline/main-graph
```

`--fresh` disables incremental seeding. Reusing an already built fresh artifact for the same exact revision is allowed. An existing output for another revision or an incremental graph is rejected. Faultline publishes a closed SQLite snapshot and manifest; those two files are the baseline artifact.

A copyable [GitHub Actions example](../assets/github-main-graph.yml) builds and publishes the baseline. Configure its pinned Faultline ref and repository access before adopting it. The example is not installed into the consuming repository automatically. Other CI platforms can run the same command and publish the same files.

Restore a trusted artifact using your CI platform's artifact tools. If its revision matches the PR's exact base, pass it explicitly:

```bash
faultline benchmark --base <actual-base> --head <tested-head> \
  --base-graph .faultline/restored-main --prepare
```

`--head-graph` similarly accepts an exact tested-head artifact. Faultline checks repository identity, revision, settings, and integrity. An old or newer main artifact cannot stand in for the PR base. Missing graphs are built for the correct revisions; `--no-build` instead reports available evidence and any gaps. Incompatible explicitly supplied artifacts produce visible incomplete graph evidence, not a successful baseline comparison.

Use artifacts from trusted main jobs; hashes detect modification but do not authenticate producers. Keep PR-specific artifacts separate. A baseline does not require Jev credentials. Retain the specific baseline versions needed by saved benchmark cases; do not commit graph databases to Git.

## Import existing full-suite results

Freeze the benchmark before reading outcomes. Normalize one CI attempt into the JSON contract below, using exact source-unit IDs from the case and native IDs from the runner's inventory/results. Existing hosting and result tooling performs collection; Faultline does not trigger CI or invent test identities.

```json
{
  "schema_version": 2,
  "benchmark_id": "<integrity from the frozen benchmark>",
  "repository": "<repository identity from the benchmark>",
  "base": "<exact base SHA>",
  "head": "<exact tested SHA>",
  "attempt_id": "<CI run and attempt identity>",
  "outcome_blind": true,
  "complete": true,
  "inventory": {
    "unit:default:tests/AccessTest.php": ["AccessTest::testDenied"]
  },
  "tests": [{
    "unit_id": "unit:default:tests/AccessTest.php",
    "test_id": "AccessTest::testDenied",
    "status": "failed",
    "failure_kind": "regression",
    "evidence": "<evidence supporting this classification>",
    "duration_seconds": 1.2
  }]
}
```

Include every configured execution unit and all its native members in `inventory`; provide each result once. Allowed statuses are `passed`, `failed`, `skipped`, and `unknown`. Failed tests can be classified as `regression`, `flake`, `infrastructure`, `baseline`, or `unknown`. Classified failures require evidence. For frameworks with repeated names, preserve native identity including datasets/scenarios so members remain unique within the unit. Keep variants as separate unit IDs. A complete producer inventory is a declared input that Faultline cannot independently prove.

```bash
faultline benchmark-report --benchmark .faultline/benchmarks/<id>.json \
  --outcomes .faultline/ci-outcomes.json
```

Import is offline and saves one assessment JSON plus Markdown. It checks the benchmark ID, repository, base/head, duplicate results, and declared inventory. Missing/unmatched tests, skipped/unknown results, partial benchmarks, or `outcome_blind: false` prevent comparative recall claims. Never assert outcome blindness if the agent or operator already inspected failures. A green run has no regression denominator.

Natural-policy recall uses shared mandatory execution rules. Equal-sized raw ranking cuts are separate diagnostics and do not represent executable selections with prerequisite scheduling. Duration sums estimate serial test work; they exclude setup, parallelism, indexing, inference, and audit overhead. Coverage and measured CI savings remain unknown without their own measurements. Treat repeated attempts as related observations and keep tuning cases separate from assessment cases.

Without `--outcomes`, `benchmark-report --benchmark <path>` regenerates the Markdown report from its frozen case without indexing or inference.

## Storage and reuse

New answers are stored in one `.faultline/jev-cache.sqlite` database. Cache identity still covers the complete transmitted request, model, and evaluator. Stored answers are validated and immutable; arbitrary similar descriptions never justify reuse. The cache contains hashes and answers, not repeated request source bodies. Older JSON answer caches remain readable. Run `faultline cache compact` to migrate verified answers into SQLite and remove their old JSON cache files. Unrecognized or invalid batches remain untouched and are counted in the result. This command makes no API calls. Do not delete saved benchmark evidence to clear disposable caches.

Copy the SQLite cache only after the process has finished, and restore it only from trusted artifact producers. The benchmark JSON retains common source evidence once, the two policies' judgments, and a request manifest. Graph artifacts keep their own immutable revision identities. Storage changes must not change inference inputs. New retrieval, summarization, batch membership, model, or evaluator choices require a separately versioned experiment against the saved reference cases.
