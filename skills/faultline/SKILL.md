---
name: faultline
description: Assess which tests a PR or MR should run using Jev, gather missing implementation evidence, configure source discovery, benchmark a cumulative diff within a spending budget, explain selections and costs, recover incomplete scoring, and compare frozen proposals with existing CI outcomes.
---

# Faultline

Use the bundled engine to score actual test source with Jev. Do not invent scores, generate test descriptions, or prefilter candidates. Resolve `<this-skill>` to this installed directory; run `python3 "<this-skill>/scripts/run.py" --root "<repo>" ...` or the equivalent `faultline` CLI. Change Faultline's source and reinstall; never patch installed copies.

For Jev question design, evidence shaping, score interpretation, or cost/performance work, use the installed `typesafe-ai` companion skill and [Faultline's Jev guidance](references/jev.md). If unavailable, follow the official-docs fallback there. Keep the bundled engine's current behavior separate from experiments.

## One PR or MR

1. Configure real test paths and variants using [the source workflow](references/workflow.md). `init` and `discover --revision <ref>` read Git source without starting the application. Keep missing and empty suites visible.
2. Resolve the cumulative diff base and exact tested head with Git/hosting tools. For historical or stacked PRs, use their actual revisions. Read Git objects without changing branches, tracked files, exclusions, or commits. Local configuration is recorded separately.
3. **Start with the diff.** Inspect each component for behavior the diff cannot explain: an external dependency, remote patch, inherited implementation, or opaque behavior switch. Ordinary API use and inline patches do not automatically need more source. Only when a specific gap exists, load [context gathering](references/context.md), collect the smallest verifiable evidence that addresses it, and freeze it. Mixed changes are handled component by component. Never copy the skill, investigation notes, or a codebase overview into Jev's input. The experimental Jev gate is not yet a shipped command.
4. Follow [the benchmark guide](references/benchmark.md). Prepare the exact inputs offline, then score within the shared spending/request budget. Use `--context <bundle>` only when evidence was collected. Keep every configured test eligible; if inputs or budgets cannot fit, preserve an explicit incomplete report.
5. Report RUN/OMIT proposals, assessed/unresolved counts, requests, tokens, and dated Jev costs. Show 10/25/50% alternatives with `benchmark-report --compare-policies`; these reuse saved judgments. Distinguish model suggestions from mandatory rules and fallbacks. State context gaps and unknown agent costs. Relevance is not failure probability, coverage, or measured savings.

Shadow analysis runs no tests and changes no CI. Native discovery and application startup need separate authorization. `run` previews unless explicitly given `--execute`; execution currently runs full suites. See [execution](references/execution.md) only when requested.

## Keep work bounded

Target **under $0.50 in Jev usage per PR snapshot; stop before $0.90**. Respect any smaller user budget. Count gates, scoring, retries, and recovery together, including earlier invocations. Use the pinned model's dated price and maximum billable input to translate the remaining amount into a conservative `--max-requests` allowance; see [budget arithmetic](references/benchmark.md#spending-budget). The CLI enforces request limits, not a persistent dollar limit. Never reset the allowance by restarting, silently omit evidence to fit, or count unknown usage as zero. If a complete assessment cannot fit, stop and report why.

Use `benchmark-recover --prepare` before recovery, within that same remaining allowance. Accepted evidence stays immutable. All parts need valid answers; invalid probabilities are never normalized. Zero new requests can mean cached answers, not zero work. Keep source gaps, unknown billed attempts, and external agent costs visible.

Credentials load from `TYPESAFE_API_KEY`, repository `.faultline/.env`, then root `.env`. The user enters keys locally; never request or display them. Selected change evidence and test source go to Jev. Never disable TLS verification.

## Compare outcomes afterwards

Freeze predictions and policy comparisons before inspecting CI outcomes. Previously inspected cases remain development cases. Import existing outcomes at exact tested revisions and attempts using [outcome assessment](references/benchmark.md#assess-outcomes). Unexecuted tests stay unknown; repeated attempts are not independent regression cases.

Use bounded hosting requests. Report generation does not trigger CI or publish comments. `--format comment` saves a preview; use only real HTTPS artifact links in published summaries. Never claim smaller selections establish better regression detection.
