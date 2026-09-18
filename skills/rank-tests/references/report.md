# Historical evidence and reports

A normal request such as “analyze PR 123 with Faultline” is one agent workflow. The skill prepares/finalizes predictions, then collects outcomes, calls `evaluate`, and presents its automatically saved report. The user does not need a sequence of manual CLI steps. A later `report` call is an offline convenience.

## Outcome input

Use hosting tools and project knowledge to interpret existing results. Native reports, JUnit XML, logs, and external CI systems can all supply evidence; the agent normalizes them into this contract. Faultline does not infer test failures from a workflow's red/green status.

```json
{
  "schema_version": 1,
  "prediction_id": "ID returned by rank",
  "collected_at": "timestamp after the complete prediction was frozen, including timezone",
  "reviewer": "agent or human reviewer name",
  "runs": [
    {
      "id": "workflow-run/job-id",
      "attempt": 1,
      "snapshot": "same exact tested revision as prediction",
      "status": "completed",
      "started_at": "2026-01-01T12:00:00+00:00",
      "execution": "unknown",
      "order_verified": false,
      "tests": [
        {
          "id": "exact catalog ID",
          "status": "failed",
          "duration_seconds": 42.0,
          "classification": "confirmed_regression",
          "evidence": "artifact/log location and why this is attributable to the change"
        }
      ],
      "notes": ["Artifact coverage and any collection gaps"]
    }
  ]
}
```

`runs` may be empty when no evidence is available. Each run/attempt pair is unique. Use job-qualified run IDs when a workflow contains multiple instances of the same test; do not invent deduplication by display name. The script will reject duplicate test IDs within one run. Retain unmatched exact IDs to expose suite drift rather than silently dropping failures.

Run status is `completed` only when execution completed; cancelled, queued, timed-out, or unavailable runs remain incomplete. Test statuses: `passed`, `failed`, `error`, `skipped`, `unknown`. Failure labels: `confirmed_regression`, `likely_flake`, `infrastructure`, `baseline`, `unknown`. Any label except unknown requires evidence and a failed/error outcome. Passing on retry alone does not establish flakiness. One run can include confirmed failures and unrelated failures.

Missing/expired artifacts are unavailable evidence, not green results. Preserve collection limitations in `notes`. Unknown labels never contribute to confirmed-regression metrics. The agent can investigate labels after prediction; new labels produce a new evaluation without new inference.

## Timing and order

`execution` is `serial`, `parallel`, or `unknown`. Only set `order_verified: true` and provide `execution_order: ["test-id", ...]` when actual execution order is supported by evidence and covers the whole ranked catalog. XML document order is not automatically execution order. Absent comparable order, the historical-order baseline is unavailable.

Durations are nonnegative seconds. Time to Semantic Failure is the serial cumulative duration through the first confirmed failure, and is omitted if any needed duration is unknown. This is a simulation for parallel or unknown CI scheduling, not a claim about wall-clock speedup. Never include queueing or CI downtime as a benefit from ranking.

## Evaluation

```bash
python3 <helper> --root <repo> evaluate --prediction <id-or-file> --outcomes <outcomes.json>
python3 <helper> --root <repo> report --prediction <id-or-file>
python3 <helper> --root <repo> report
```

`evaluate` validates the prediction integrity and input schema, requires outcomes collected after the complete freeze, computes lexical/path/seeded-random baselines plus historical order when available, and writes `findings.json`, `report.json`, and `report.md` under `.faultline/evaluations/<evaluation-id>/`. It preserves the supplied `outcomes.json`. Rankings and measurements are code-generated; the agent may add explanatory prose separately, with links to evidence.

Eligible runs require a matching tested snapshot, outcome-blind verified historical context, a complete ranking, and at least one confirmed regression. A confirmed failure absent from the catalog excludes that run's metrics to avoid optimistic recall. Missing unrelated tests are counted in coverage. All exclusions remain visible.

Reports separate hit rate (at least one failure in the first K) from failing-test recall (fraction of known failures in the first K), for K = 1, 5, 10, 20, 50. The first eligible run by reported start time is selected within a prediction. Supply accurate timestamps; missing times fall back to deterministic identifiers and must be disclosed as a limitation.

Aggregates select one earliest eligible saved case per PR/MR, ignoring scores when choosing it. Repeated attempts/reviews never increase the number of independent changes. Different repositories, evaluator configurations, and random seeds form separate groups. Recall is macro-averaged across cases. Median/worst first-failure ranks are included; p90 is omitted for fewer than ten eligible cases. Timing remains per-run to avoid comparing unmatched schedules or denominators.

A report with no eligible failures says performance cannot be assessed. A one-PR report is a case study, not a representative benchmark. Explain poor ranks, missing context, suite drift, and classification uncertainty. If descriptions are improved after inspecting outcomes, retain the original frozen experiment and evaluate future untouched cases separately.

## Collection discipline

Cache inputs incrementally under `.faultline/history/`, namespaced by repository/PR/snapshot/run/attempt. Collect only one PR/MR unless the user requests a sample. Rank the chosen snapshots before reading conclusions or downloading results. Use serial authenticated hosting requests, track an explicit request ceiling, respect rate-limit/reset responses, and resume cached work. Do not start workflows or alter CI. The helper has no GitHub client: it cannot enforce the agent's hosting-request budget or verify the truth of source provenance.
