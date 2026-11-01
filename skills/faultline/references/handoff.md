# Prepare before pushing; execute in CI

The agent assesses the cumulative PR diff and publishes a small decision before pushing. CI retrieves it once, then runs selected files or falls back fully. CI needs no Jev key and never waits for scoring.

## Install the optional pilot

1. Review `faultline.json` and commit it on the default branch. Configure your actual runner commands, variants, prerequisites and source paths; see the [configuration reference](workflow.md).
2. Copy the [publisher](../assets/faultline-publish.yml) and [automatic PR workflow](../assets/faultline-pr.yml) into `.github/workflows/` on that branch. Set repository variable `FAULTLINE_REF` to a reviewed 40-character Faultline commit. While Faultline is private, its checkout needs a read-only `FAULTLINE_REPO_TOKEN`; this may be unavailable for fork PRs.
3. Supply the reviewed `.github/faultline-setup.sh` used by the templates. It receives the absolute target checkout path and prepares your existing runtime, services, dependencies and resets. It must fail on setup errors. Faultline does not choose application setup commands. Keep other runners and existing required checks unchanged.
4. Optionally merge an [agent hook template](hooks.md) into your agent configuration. This implementation ships templates only; installation never happens implicitly.

The publisher executes only reviewed default-branch code. It validates data and uploads two small JSON files, never application source, prompts or scores. It can publish a decision for a local commit that GitHub has not received yet. Publication needs an authenticated `gh` user with workflow-dispatch access; retrieval uses read-only Actions access.

The PR workflow handles opening, updates, reopening, readiness and target-branch changes. It checks out the **exact PR head**, computes the merge base against the event's target revision, and checks the publication. Existing required checks still test their usual merge revision. The pilot rejects an unreviewed or missing execution configuration instead of running arbitrary changed setup commands.

## Agent: assess and publish

Commit first. Resolve the actual target branch from the existing PR or the intended new PR; do not infer it from an upstream tracking branch. Fetch that branch, then use its merge base with `HEAD` as `<merge-base>`.

```bash
git fetch origin
# Resolve <merge-base> with: git merge-base origin/main HEAD
faultline assess --evaluator noul-v1 --base <merge-base> --head HEAD --prepare --max-cost 0.50
faultline assess --evaluator noul-v1 --base <merge-base> --head HEAD --max-cost 0.50
faultline ci-submit --run <run-id> --threshold 0.50 \
  --target-branch main --repository owner/project
```

Use the same verified `--context` bundle in preparation and scoring when evidence is needed. The existing budget includes retries and resumed attempts. Publication makes no Jev calls. It checks the target branch is current, exports required additions/fallbacks, and waits at most two minutes for a successful publisher run and matching artifact. Queue time is part of that limit. Only success creates a local readiness receipt.

After `published: true`, push in a **separate** tool call (`git push origin HEAD`), then open the PR if needed. Repeated attempts reuse the decision for the same snapshot; new commits, amendments, rebases, config changes and changed merge bases require a current decision. Target advancement that leaves the merge base unchanged leaves the cumulative diff unchanged too.

If scoring is unavailable or outside budget, explicitly publish full execution:

```bash
faultline ci-submit --full --head HEAD --target-branch main \
  --repository owner/project --reason 'Assessment budget exhausted'
```

If publication fails, no new readiness receipt is created. Inspect the publisher run, correct the problem and retry without rescoring unchanged inputs. The optional hook continues to block until publication succeeds; only the user can choose to disable it. Direct terminal pushes and other bypasses still receive CI's full fallback.

## CI: retrieve and execute

The complete templates handle checkout, configuration review and setup. These are the execution steps inside the prepared target checkout:

```bash
faultline ci-fetch --repository owner/project --target-branch main \
  --base-ref <exact-target-tip> --output .faultline/selection.json
faultline ci-run --selection .faultline/selection.json --runners phpunit behat playwright \
  --execute --output .faultline/pr-execution.json
```

Retrieval makes one bounded artifact-list query, inspects at most ten newest candidates, and spends at most 25 seconds on GitHub operations. It validates the publisher workflow, successful default-branch run, repository origin, ZIP digest and bounds, exact head, configuration and cumulative diff. It does not poll for an assessment. An expired artifact, unavailable token/API, malformed response or mismatch produces an explicit full manifest and a visible fallback reason. Artifact names alone confer no trust. These defaults target GitHub.com.

A valid `none` means every eligible test was assessed below the cutoff, after required additions. It still needs working application setup and native inventory validation. An empty or unverifiable inventory widens execution. Broken setup, missing configuration and runner failures fail visibly; they never become successful empty runs. An entirely absent agent assessment is therefore safe to handle immediately: run fully.

Artifacts expire after seven days in the template. Local hooks check the confirmed receipt and locally fetched target ref without network calls; they cannot notice remote artifact deletion, a retargeting they have not been told about, or every possible shell wrapper. CI revalidates independently. Refresh the hook's configured target when retargeting a PR. Full execution remains the fallback for uncertainty, not a claim that a 50% threshold preserves regression detection.

## Compare before making checks selective

Keep the [manual comparison pilot](../assets/faultline-pilot.yml) for selected-versus-full execution of the same revision:

```bash
faultline export-selection --run <run-id> --threshold 0.50 --output .faultline/selection.json
faultline ci-submit --selection .faultline/selection.json \
  --repository owner/project --workflow faultline-pilot.yml
```

It runs both selections, so it intentionally saves no execution time. Keep existing required checks while collecting actual outcomes. There is no automatic promotion to required selective CI. See the [execution reference](ci.md) for selectors, variants, prerequisites and receipts.
