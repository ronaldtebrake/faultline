# Install Faultline

## 1. Check the prerequisites

You need Python 3.10+, Git, Node.js/npm, and a coding agent that supports Agent Skills. Test runners and application dependencies are needed when you execute tests; they are not required for source analysis.

Faultline is currently private, so your GitHub account needs access to the repository through SSH.

## 2. Install CodeGraph

```bash
npm install -g @colbymchenry/codegraph@1.6.0
codegraph --version
```

The version should be `1.6.0`. Faultline uses this CLI directly; no CodeGraph agent or MCP setup is needed.

## 3. Install the Faultline skill

Run this from the repository you want to analyze:

```bash
npx skills add git@github.com:ronaldtebrake/faultline.git --skill faultline
```

Choose your coding agent when prompted, then start a new agent session in that repository.

To test unpublished changes, replace the Git URL with your local Faultline checkout:

```bash
npx skills add /path/to/faultline --skill faultline
```

Use one of these commands. The skill includes its Python scripts; no separate Python package installation is required.

## 4. Initialize your project

Ask your agent:

> Set up Faultline for this repository. Configure its test source patterns and build a reusable CodeGraph baseline from the default branch. Reuse a trusted baseline if one is available. Do not generate a separate test catalog, call Jev, run tests, or start the application.

Commit `faultline.json` to share test source patterns and policies. After configuring it, `faultline init --baseline <default-branch>` creates the primary source/test index in `.faultline/graphs/<hash>/graph.sqlite`. It includes CodeGraph relationships and file targets for tests CodeGraph cannot parse, such as Gherkin. There is no separate catalog to maintain.

Each revision has an immutable snapshot. Ordinary indexing can reuse a compatible ancestor. The reference benchmark builds fresh graphs for missing revisions and accepts trusted artifacts for its exact base and tested head. Teammates can import a trusted baseline with `faultline graph import <artifact-directory>`; the [workflow guide](../skills/faultline/references/graph-workflow.md#shared-baselines-and-branches) describes export/import. Local credentials, graph artifacts, caches, and reports stay in ignored `.faultline/`.

If you run `init` before creating `faultline.json`, it prepares storage and asks you to configure suites; run it again after configuration to build the graph.

## 5. Configure the Jev API key

After initialization, create `.faultline/.env` in the repository you want to analyze:

```dotenv
TYPESAFE_API_KEY="your-key"
```

Faultline reads this file automatically, including when invoked from an IDE. Keep it out of Git and do not paste the key into your agent conversation. An existing `TYPESAFE_API_KEY` environment variable takes precedence.

The key is needed for live Jev judgments. Selected change context, test source, and graph evidence are sent to Jev.

## 6. Try a PR or MR

Ask your agent, replacing `123` with your PR or MR number:

> Use Faultline to benchmark PR 123 with CodeGraph, Jev, and CodeGraph plus Jev. Prepare the graphs and show the estimated scoring work first. Use at most 10 Jev HTTP requests in total for this task; do not raise or reset that budget. Save the three-way shadow comparison report. Do not execute tests or change CI.

Your agent needs access to the PR/MR through your existing hosting tools. Faultline saves the would-run report without executing tests. Use [the benchmark guide](../skills/faultline/references/benchmark.md) to assess the frozen proposals against existing CI outcomes; keep your existing CI test jobs unchanged.

See the [workflow guide](../skills/faultline/references/graph-workflow.md) for configuration and command details.

## Optional: standalone CLI for CI

To use Faultline without a coding agent, install the Python package in a virtual environment:

```bash
python3 -m venv ~/.venvs/faultline
~/.venvs/faultline/bin/pip install 'git+ssh://git@github.com/ronaldtebrake/faultline.git'
~/.venvs/faultline/bin/faultline --help
```

CodeGraph is required for indexing. Your project's test runners and application environment are required for execution. For CI, pin the installation to a reviewed Git commit. Follow the same project configuration and API-key setup above, then use the commands in the [workflow guide](../skills/faultline/references/graph-workflow.md).

## Updating an existing installation

Reinstall/update the skill or plugin using the same method used above, then start a new agent session so it reads the new instructions. For a standalone checkout installation, reinstall from that checkout. Confirm the active engine with `faultline --version`, or `python3 "<installed-skill>/scripts/run.py" --version`: this source version is **0.5.0**. A Git-based installation receives it only after these changes are published to that Git revision.

Version 0.3.0 uses a new graph artifact schema. Re-run `init --baseline <default-branch>` or import a baseline produced by this version. Old catalogs are ignored by the graph workflow; old artifacts are not overwritten.

## TLS certificate errors

An `SSL: CERTIFICATE_VERIFY_FAILED` error concerns Python's HTTPS trust store, not Git SSH or your Jev key. Faultline uses verified TLS and honors `SSL_CERT_FILE` / `SSL_CERT_DIR`. Where Python's certificate bundle is missing, install `certifi` in the **same Python environment that runs the skill**, for example `python3 -m pip install certifi` inside its virtual environment. Faultline automatically supplements default roots with that bundle unless explicit certificate paths are configured. Use an organization-approved CA bundle for enterprise proxies. Never disable certificate verification or edit installed skill copies as a workaround.

Version 0.5.0 adds the three-way reference benchmark. Existing compatible graph artifacts and selection answer caches remain readable. Benchmark requests have a separate input contract, so their answers cannot be substituted for earlier selection judgments. New answers are stored in one SQLite file; identical benchmark inputs resume from that cache.
