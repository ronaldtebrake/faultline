# Test catalog contract

`.faultline/index.jsonl` is UTF-8 JSON Lines: one object per executable test (or explicitly declared coarser unit). The input helper also accepts a JSON array. IDs must be unique across the repository and stable across unrelated line changes.

Required fields:

- `id`: exact namespaced runner identity; never a model-invented name.
- `source`: repository-relative source file, with no traversal or external symlink target.
- `description`: behavior supported by the source evidence.

Optional fields include `runner`, `locator`, `metadata`, and `context_sources` (a list of repository-relative setup/helper files). Use `metadata.granularity` when the unit is a file rather than a test case. Preserve runner parameters/project identity in `id` and `locator`.

The helper adds `source_hash` and `generated_by` (`faultline_skill_version`, `agent`). The hash covers the complete source file and each declared context file, including their paths. This conservative choice invalidates sibling cases when their shared file changes. Dependency discovery remains the agent's responsibility; undeclared helper changes cannot be detected automatically.

Example draft:

```json
{"id":"unit::RefundTest::partialRefund","source":"tests/RefundTest.php","runner":"phpunit","description":"A partial refund reduces the remaining balance and adds a refund record.","context_sources":["tests/fixtures/payment.php"],"locator":{"class":"RefundTest","method":"partialRefund"}}
```

Descriptions may quote readable test text directly. Avoid adding architecture assumptions, failure labels, or outcomes. Do not claim full suite coverage when discovery was restricted by tags, environment, project configuration, or missing dependencies.

Commands (replace `<helper>` with the absolute path to `scripts/run.py` inside this installed skill):

```bash
python3 <helper> --root <repo> index-status
python3 <helper> --root <repo> source-hash tests/RefundTest.php --context tests/fixtures/payment.php
python3 <helper> --root <repo> index --input <repo>/.faultline/index.draft.jsonl --agent codex
python3 <helper> --root <repo> index show
python3 <helper> --root <repo> explain-test 'unit::RefundTest::partialRefund'
```

`index-status` checks existing entries, not discovery completeness. Supply the full rediscovered inventory to remove obsolete cases. Hashes and cache validity are computed by code, never by judging whether two inputs seem similar.
