# Selector comparison: anonymized historical results

This record preserves aggregate results from one previously inspected private change. Repository names, PR identifiers, paths, symbols, revisions, timestamps, and CI links are omitted. No source, raw model inputs, or per-test identities are included.

**Decision:** simplify Faultline to source-based Jev assessment. The extra graph pipeline did not demonstrate enough routing value in this case to justify retaining it. This is a product direction, not proof that graphs are generally ineffective or that Jev has validated regression recall.

## PHPUnit candidate sets

The same 354 configured PHPUnit source files were compared against the union of exact base and tested-head snapshots. The native CodeGraph 1.6.0 query used the generic `*Test.php` filter.

| Approach | Candidate files | Files without a suggested path |
| --- | ---: | ---: |
| Native graph query, depth 5 | 246 | 108 |
| Native graph query, depth 16 | 339 | 15 |
| Native query after verified invalid-call cleanup, either depth | 3 | 351 |
| Changed/new-test rule | 3 | 351 |

Faultline’s conservative graph policy retained **354 / 354 files**, including 15 without a positive path. The diagnostic cleanup removed only verified invalid function-to-method edges in temporary copies. Name collisions and broad file propagation had produced excessive connections. The three surviving candidates were exactly the changed/new tests: zero additional native candidates beyond that rule.

Missing paths are not evidence of irrelevance. Dynamic configuration, services, inheritance, and indirect calls can be absent from static evidence. The cleaned candidate count therefore does not justify running only three files.

## Saved Jev proposals

These are existing frozen judgments restricted to PHPUnit. No new inference was performed for this audit.

| Policy | CodeGraph RUN / OMIT | Jev RUN / OMIT | CodeGraph + Jev RUN / OMIT |
| --- | ---: | ---: | ---: |
| Saved omission policy | 354 / 0 | 94 / 260 | 339 / 15 |
| Relevance ≥ 10% | 354 / 0 | 17 / 337 | 58 / 296 |
| Relevance ≥ 25% | 354 / 0 | 8 / 346 | 15 / 339 |
| Relevance ≥ 50% | 354 / 0 | 5 / 349 | 4 / 350 |

Mandatory rules are retained. The saved policy omits at `P(irrelevant) ≥ 95%`, equivalent to retaining weak-or-higher relevance **above 5%**, absent other requirements. The experimental thresholds use `P(plausible + strong + direct)`, excluding weak relevance. Windowed targets use maximum-part relevance, not a calibrated whole-change probability.

Adding graph context often broadened this saved selection. That is consistent with noisy context, but this case does not establish causation or comparative accuracy. Smaller Jev selections are also unvalidated for regression recall.

## Runtime and cost evidence

The observed PHPUnit work comprised **62 successful jobs**, approximately **694 aggregate job-minutes**. Explicit test-running steps accounted for approximately **566 minutes across 60 steps**. The longest job was approximately 73 minutes; the observed job span was approximately 78 minutes. Whole-job sums include setup and parallel work. Two different job layouts were not assigned invented test-only durations.

There are no confirmed PHPUnit regression failures in this case. Successful jobs are not converted into per-file pass records. No authoritative mapping from these file proposals to avoided jobs or test durations was available, so **regression recall and actual savings are unknown**.

New inference cost for this audit was **$0**. Exact PHPUnit-only Jev cost is unavailable because the original requests included multiple suites. Dividing batch cost by file count would invent attribution. Graph analysis also consumes local compute and storage even without an inference API fee.

## What this establishes

This inspected tuning case exposed excessive graph routing and motivated a simpler Jev-only reference. It does not validate a deployment threshold, a typical per-PR price, or coverage preservation. Later, uninspected changes with confirmed outcomes and execution timings are needed to assess detection and economic value. All new Faultline reports use the Jev-only workflow; this table is a historical comparison.
