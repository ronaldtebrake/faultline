# Task dependencies and successful-result caching

`faultline tasks plan` and `faultline tasks run` use framework-independent input
graphs. Shared component inputs, explicit dependencies and content fingerprints
allow reuse of successful checks without interpreting application hooks or
individual test scenarios.

The maintained [configuration and CI contract](../skills/faultline-tasks/references/task-contract.md)
contains the schema, CLI, cache trust rules and packaged action usage. The
[faultline-tasks skill](../skills/faultline-tasks/SKILL.md) helps agents establish
and maintain declarations when application or CI dependencies change.

This is separate from the source/parser cache. Full execution is the default:
`tasks run` records matches while running every requested check. `--reuse` is the
explicit adoption option. Existing source graph assessment guards are unchanged.

The initial implementation caches successful check results only. It does not
restore build outputs, infer complete declarations or avoid job provisioning.
Consumer validation retains full CI and measures matches before enabling reuse.
No framework adapter or Jev call is required.
