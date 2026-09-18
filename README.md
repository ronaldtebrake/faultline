# Faultline

Faultline is an experiment in using TypeSafe Jev to rank automated tests by their relevance to a software change. The goal is to surface regression failures earlier, with an approach that works across projects, programming languages, and test frameworks.

## The problem

An expensive test suite can take a long time to reveal a regression, even when a change affects only a small part of a system. The test that detects the problem may run near the end.

File paths, dependency graphs, and code coverage provide useful signals about which tests matter. But changes can also affect related behaviors across those boundaries. Faultline aims to capture those semantic relationships without requiring a manually maintained project taxonomy.

## The hypothesis

Does the behavior described by a test contain enough information to identify whether it could detect a regression introduced by a particular change?

Faultline will compare the intent and code diff of a change with descriptions of the behaviors protected by tests. If that comparison is useful, relevant tests should move toward the beginning of the ranked suite and provide failure signals sooner.

Or potentially be the only test that are going to run.

## Jev’s role

We intend to use Jev to answer a bounded question for each change–test pair: **How much regression-detection value does this test have for this change?**

The proposed approach uses probabilities over relevance levels, from irrelevant to direct, to calculate a ranking. Faultline will retain those judgments for inspection and use application code to determine the order. A relevance score describes the relationship between a change and a test; it is not a calibrated probability that the test will fail. Jev’s supported integration and probability output still need to be verified.

```text
Change intent + code diff + test behavior
                    ↓
             Jev relevance judgment
                    ↓
              Ranked test suite
                    ↓
       Comparison with historical failures
```

## How we’ll assess it

The first experiment will compare rankings with confirmed regressions in historical test results. We will measure where known failing tests appear and, where duration data supports a fair comparison, estimate how soon those failures could have been discovered.

Jev’s rankings will be compared with existing execution order, random order, path-based heuristics, and lexical similarity. The question is whether semantic judgment provides useful improvement over those simpler approaches.

Historical outcomes will remain separate from ranking inputs. Reports will highlight poor rankings, missing evidence, and changes in the test suite over time. Green runs can help assess how selective and stable the rankings are, but cannot prove that any tests were unnecessary. A negative result is useful if it shows that a simpler method is sufficient.

## Initial boundaries

The initial tool will perform local analysis and rank the complete test catalog. It will not skip tests, change CI, trigger workflows, or decide whether a change is safe to merge. Influencing execution order or selecting tests belongs to later work, if the evidence supports it.

Local analysis still involves sending selected change context and test descriptions to Jev. Historical data and reports will remain local by default.

## Status

Faultline is planned and unimplemented. The remaining work, technical requirements, and milestones are described in the [implementation plan](PLAN.md).
