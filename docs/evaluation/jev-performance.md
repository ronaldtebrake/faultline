# Jev performance milestone

A fresh-call experiment assessed 1,025 configured test files in 24.2 seconds of Jev scoring for $0.1320. This is a promising transport result, not the complete time from asking an agent to review a PR to receiving a report.

These are aggregate observations from a private assessment case. Repository identity, PR number, source, paths, revisions and per-test details are omitted. The source evidence and experiment scripts remain outside this repository.

## What this commit implements

- `context --compact` preserves exact source and full local provenance while removing repeated audit metadata from Jev inputs. Windowed requests carry the labels relevant to their source ranges. The format is frozen for recovery and has its own cache identity.
- Agent instructions start with the diff and collect focused evidence for specific gaps, including inherited behavior and external implementation. They use TypeSafe guidance for Jev design and keep spending limits across attempts.
- Timing guidance distinguishes complete agent workflows from scripted preparation and scoring. Unknown collection time and cost remain unknown.

The production benchmark still uses five-level Choice judgments and its existing transport. The pooled client, mixed request layout and Noul scorer below are separate experiments; they are not enabled by installing this commit. Compact context labels and mixed request layouts are different changes.

## Fresh comparison

All three arms used the same experimental Noul question: whether a change affects behavior actually exercised by a test, including its setup. All 1,025 known files and 1,048 source-range questions were assessed. No cached predictions, retries or invalid answers were involved.

| Experiment | Scoring time | Input tokens | Input cost | Requests | Proposed RUN at 10% / 25% / 50% |
| --- | ---: | ---: | ---: | ---: | ---: |
| Serial requests | 96.7s | 3,155,427 | $0.1325 | 78 | 335 / 18 / 1 |
| Pooled requests | 26.0s | 3,155,427 | $0.1325 | 78 | 335 / 18 / 3 |
| Pooled + mixed layout | 24.2s | 3,143,745 | $0.1320 | 72 | 329 / 23 / 2 |

Serial and pooled requests contained identical inputs. Reusing a client with up to four concurrent requests delivered a **3.71x measured speedup** at the same token cost. Mixed layout preserved the original evidence pairs while saving a further **0.37% of tokens**. On this small change, transport delivered most of the benefit.

The model was pinned to `jev-1.13.0`, with `typesafe-sdk==0.7.0` for pooled calls. Cost uses reported input tokens at $0.042 per million, with free outputs, checked on 2026-09-22 against [provider pricing](https://docs.typesafe.ai/models). Total Jev input cost across the 228 requests was $0.3971; agent and infrastructure costs are excluded.

TLS remained enabled, SDK automatic retries were disabled, and all workers shared rate and spending controls. There was one full run per arm, in mixed-layout, serial, pooled order. Service conditions and model variability can affect a single comparison; these are observations, not a latency guarantee.

## What the clock includes

| Measured stage | Time |
| --- | ---: |
| Read source and extract already-selected context | 13.9s |
| Prepare and verify both comparison layouts | 23.0s |
| Score the mixed-layout candidate, including client setup | 24.2s |
| Sum of those stages | 61.1s |

The agent's investigation to identify context, environment setup, hosting collection and report generation were not included. Git objects were already local. Neither 24.2 nor 61.1 seconds is an end-to-end measurement. A normal run would not need to prepare both comparison layouts, but its complete timing has not been established.

## What remains unproven

Identical serial and pooled inputs changed 40, six and two file decisions at the 10%, 25% and 50% cutoffs. The mean absolute score difference was 0.52 percentage points. Thresholds can amplify small differences; smaller selections alone do not establish better quality.

These Noul scores are impact signals, not predicted test failures or the production Choice relevance statistic. Taking the maximum over source fragments does not create a calibrated whole-change probability. The run assessed all known source files, but did not prove exhaustive runner discovery; an empty configured suite remained unresolved.

No tests were executed and no outcomes supplied to scoring. Regression recall, preserved coverage and actual CI savings remain unmeasured. Before adoption, integrate and test bounded transport in the shared engine, keep scorer and layout versions explicit, measure complete agent-to-report latency, and compare frozen proposals with outcomes from later assessment cases.
