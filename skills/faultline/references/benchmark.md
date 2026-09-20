# Benchmark one PR or MR with Jev

Use the installed `faultline` CLI or `python3 "<this-skill>/scripts/run.py" --root "<repo>"`. Configure actual test paths using [the source workflow](workflow.md).

## Gather context or retain a diff-only baseline

For normal agent use, follow [context gathering](context.md) to freeze product integration source and, where needed, upstream dependency changes. Add `--context <bundle.json>` to both preparation and scoring below. The engine validates the bundle against the exact change before inference. All tests remain eligible.

Commands without `--context` retain the diff/test-source baseline. They do not discover product callers or fetch dependency source automatically. Use that baseline for controlled comparisons; do not present it as an enriched assessment. Context bundles work with `adaptive`, `source`, and `whole` modes, not `file-pairs`. The older `select` receipt workflow does not consume bundles.

## Prepare, then score

Resolve the cumulative diff base and exact tested head through existing Git/hosting tools. Both revisions must be present locally. For a closed or merged PR, use its original base/tested head rather than current main; no checkout switch is necessary. Optional `--title` and `--description` must contain pre-outcome intent. Omit historical text whose earlier version cannot be verified.

```bash
faultline benchmark --base <actual-base> --head <tested-head> --prepare --max-requests 100
faultline benchmark --base <actual-base> --head <tested-head> --id PR-123 \
  --max-requests 100 --selection-seconds 120
```

Preparation reads Git sources and estimates uncached requests without Jev or test runners. Inspect `preparation.status`, blockers, eligible targets, and planned requests. A zero-request plan with zero eligible targets is blocked, not a completed free assessment. The example cap may not fit your suite; all attempts, including retries, share it. Do not loop to reset a user’s authorized task budget.

Live scoring writes immutable JSON evidence, Markdown, and a per-target CSV in `.faultline/benchmarks/`. `--output <fresh-path.json>` changes the destination. Partial assessments save their report and exit 2; unrecoverable command errors exit 1. No tests execute or CI settings change. A later identical invocation can reuse exact-input answers from `.faultline/jev-cache.sqlite` within remaining authorization.

Every readable configured test is eligible, including required tests. Files retain their datasets, scenarios, and examples. Configuration scope and mandatory rules are recorded independently of model judgments. Missing source or failed assessment stays RUN.

## Input scope and recovery

Default `--evidence-mode adaptive` shares change context across question-local test source. Whole inputs are preferred. When a diff/test pair exceeds local guards, the engine partitions it at complete lines and change-section boundaries. All source/change ranges are represented; it does not drop tests to make requests fit. Cross-window interactions and unsupplied external setup implementations remain outside the assessment. With a context bundle, the same planner covers the original diff plus labeled supporting evidence, preserving block provenance; larger context can increase requests and conservative selections.

A confirmed provider `max_tokens_exceeded` rejection splits batches of question-local tests into smaller groups. Shared change evidence and each complete test question are preserved; actual child requests receive their own cache identities. Attempts share the same limits. An oversized single question remains unresolved and needs smaller evidence windows. Rejected requests without token usage keep their cost unknown.

Each answer must be a valid five-level distribution. One invalid-response retry is enabled by default and counts against the same limits. Accepted sibling answers are preserved. Unknown network outcomes, mismatched models, and cache failures do not trigger paid validation retries. Invalid probabilities are never silently normalized.

For an incomplete saved source/adaptive case:

```bash
faultline benchmark-recover --benchmark .faultline/benchmarks/<case>.json \
  --prepare --max-requests 100 --selection-seconds 120
faultline benchmark-recover --benchmark .faultline/benchmarks/<case>.json \
  --max-requests 100 --selection-seconds 120
```

Recovery saves a new case with parent provenance and accepted judgments intact. It preserves the original batch membership so accepted answers remain reusable. Collected context is recovered from the frozen benchmark; no new collection or upstream checkout is needed. Declared context gaps continue to require full suites. The main report includes cumulative original and recovery usage; current-invocation usage is separate. A target is fully assessed only after every part has a valid answer. Windowed relevance is the maximum plausible-or-stronger part statistic. Conservative omission requires every part to meet the irrelevant cutoff. Neither is a calibrated probability for the whole change.

A single indivisible line or required context that cannot fit stays blocked. Smaller batches or more requests cannot fix an oversized individual question. `--max-state-bytes` and `--max-batch-bytes` override local byte guards for one invocation; these are not exact provider token counts. Inspect the provider’s current model limits before changing them; never disable response validation.

Other evidence modes are explicit experiments:

- `source`: full cumulative diff plus whole test file; oversized inputs stay unresolved.
- `whole`: additionally supplies complete configured setup source; can need larger requests.
- `file-pairs`: whole test files against bounded groups of complete changed-file sections; cross-section interactions are not assessed. It cannot supply cumulative-change probabilities for the offline threshold comparison.

## Read decisions and costs

`benchmark-report` regenerates saved evidence offline:

```bash
faultline benchmark-report --benchmark .faultline/benchmarks/<case>.json \
  --output .faultline/reports/pr-review.md
```

The report compares the full configured suite with Jev’s RUN/OMIT proposal. Reasons distinguish required tests, policy choices, and unresolved fallbacks. The model’s most likely label is separate: an irrelevant label can still produce RUN below the configured omission cutoff.

The default omits non-required tests at `P(irrelevant) ≥ 0.95`. This retains weak-or-higher relevance **above 5%** when no other rule applies. It is not the same statistic as plausible-or-stronger relevance, which excludes weak.

Requests, input tokens, cache hits, and pricing are reported separately. Supply a report-only `--pricing <file.json>` override with the pinned model, ISO `as_of` date, and verified `input_usd_per_million` rate; an HTTPS `source` is optional. Missing usage or a missing dated price stays unknown. Estimated input cost excludes output and external agent costs. A cached or partial run does not establish the price of a new complete PR, and mixed-suite batches do not provide per-test cost attribution.

The CSV keeps exact decisions, probabilities, and a `review_notes` column. Regenerating the same case preserves notes; reusing that notes file for another case is rejected. Frozen inputs and judgments are unchanged.

## Compare policies offline

```bash
faultline benchmark-report --benchmark .faultline/benchmarks/<case>.json \
  --compare-policies --relevance-thresholds 0.10 0.25 0.50 \
  --file-budgets 100 250 500 --output .faultline/reports/pr-review.md
```

These experiments use the same saved probabilities with zero new inference. Relevance is `P(plausible) + P(strong) + P(direct)`. Required targets, full-suite obligations, and unresolved evidence remain RUN at every threshold or budget. Prerequisites expand transitively. Infeasible budgets and stable-ID tie-breaks are disclosed.

Defaults are 10%, 25%, and 50% relevance and 10%, 25%, and 50% of enumerated file count. File budgets are not runtime budgets. Markdown, CSV columns, and a `.policies.json` record exact actions and differences from the saved policy. Freeze comparisons before outcome inspection; no lowest-count winner is automatically selected.

## Prepare a PR comment

```bash
faultline benchmark-report --benchmark .faultline/benchmarks/<case>.json \
  --format comment --output .faultline/reports/pr-comment.md
```

This creates a compact preview with RUN/OMIT counts, incomplete assessments, tokens, and cost assumptions. Add a real HTTPS `--report-url` for a published artifact and `--compare-policies` for the optional threshold table. It excludes source bodies and local filesystem paths. Nothing is posted to the hosting platform. Existing CI stays unchanged.

## Assess outcomes

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

To assess previously frozen threshold and budget alternatives alongside the original decisions:

```bash
faultline benchmark-report --benchmark .faultline/benchmarks/<case>.json \
  --outcomes .faultline/ci-outcomes.json \
  --policy-comparison .faultline/reports/pr-review.policies.json
```

The policy artifact must have been generated from this exact case before outcomes were inspected. Do not tune it after reading failures and then claim an outcome-blind assessment.

Observed failed tests are shown with their RUN/OMIT actions even when their cause is unknown. Unknown failures are not confirmed regressions; unmatched identities remain UNMAPPED. The assessment JSON includes these observations for each frozen experimental policy.

Import is offline and saves one assessment JSON plus Markdown. It checks the benchmark ID, repository, base/head, duplicate results, and declared inventory. Missing/unmatched tests, skipped/unknown results, partial benchmarks, or `outcome_blind: false` prevent comparative recall claims. Never assert outcome blindness if the agent or operator already inspected failures. A green run has no regression denominator.

Natural-policy recall uses shared mandatory execution rules. Equal-sized raw ranking cuts are separate diagnostics and do not represent executable selections with prerequisite scheduling. Duration sums estimate serial test work; they exclude setup, parallelism, indexing, inference, and audit overhead. Coverage and measured CI savings remain unknown without their own measurements. Treat repeated attempts as related observations and keep tuning cases separate from assessment cases.

Without `--outcomes`, `benchmark-report --benchmark <path>` regenerates the Markdown report from its frozen case without indexing or inference.

## Storage and reuse

New answers are stored in one `.faultline/jev-cache.sqlite` database. Cache identity still covers the complete transmitted request, model, and evaluator. Stored answers are validated and immutable; arbitrary similar descriptions never justify reuse. The cache contains hashes and answers, not repeated request source bodies. Older JSON answer caches remain readable. Run `faultline cache compact` to migrate verified answers into SQLite and remove their old JSON cache files. Unrecognized or invalid batches remain untouched and are counted in the result. This command makes no API calls. Do not delete saved benchmark evidence to clear disposable caches.

Copy the SQLite cache only after the process has finished, and restore it only from trusted artifact producers. The benchmark JSON retains common source evidence once, Jev judgments, exact Git revision identities, and a request manifest. Storage changes must not change inference inputs. New retrieval, summarization, batch membership, model, or evaluator choices require a separately versioned experiment against the saved reference cases.
