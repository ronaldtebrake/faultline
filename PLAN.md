# Validation plan

Faultline can discover configured test source, accept verified context, obtain Jev judgments, recover incomplete scoring, and report proposals. The next goal is to establish whether those proposals retain useful regression detection at a worthwhile cost.

## 1. Compare evidence

Compare diff-only and enriched runs at the same revisions, inventory, policy, and model. Include ordinary code changes and dependency updates across text-based test frameworks. Record missing context, setup dependencies, inventory gaps, and agent costs.

Acceptance: every configured target is assessed or visibly unresolved. No candidate is silently excluded, and an empty suite cannot authorize skipping tests.

## 2. Check against outcomes

Freeze proposals and alternative policies before inspecting later CI outcomes. Import exact revisions and attempts; distinguish confirmed regressions, flakes, infrastructure problems, and unknown failures. Keep previously inspected tuning cases separate. Repeated attempts are not independent regression cases.

Acceptance: reproducible failing-change and failing-test recall with explicit denominators and uncertainty. Unexecuted tests are never counted as passing.

## 3. Measure value and cost

Collect test/job durations, setup overhead, selection latency, request counts, and tokens. Include retries, recovery, audits, and external agent costs where known. Use dated pricing; do not invent per-test costs from mixed batches.

Acceptance: compare detections and misses at equivalent measured execution cost. Keep relevance, regression recall, measured coverage, and savings separate. Smaller selections alone do not choose a winner.

## 4. Validate selective execution

Keep full CI execution during shadow adoption. Before implementing selection, verify exact selectors, datasets, outlines, variants, prerequisites, stale decisions, and unsupported runners. Require maintainer opt-in, preserve post-merge full runs and a deterministic outcome-independent audit sample, and suspend selection after a confirmed missed regression.

Acceptance: incomplete or invalid decisions never authorize running zero tests. No automatic promotion or coverage-preservation guarantee.

## Later work

Benchmark optimizations against frozen evidence before adopting them: batching, shared trusted caches, incremental preparation, setup context, and windowing. Add selective execution, CI comment publishing, versioned releases, and further result/coverage importers when the evidence supports them.
