# Set up Faultline in CI

Reference this action at a reviewed, full commit SHA. GitHub downloads Faultline
once for the job; the action installs that same source revision in a fresh virtual
environment under the runner's temporary directory. Consumer repositories do not
need a copy of the Python engine, a wheel, or an engine manifest.

```yaml
- uses: actions/setup-python@v6
  with:
    python-version: '3.12'
- uses: ronaldtebrake/faultline/actions/setup@<reviewed-full-commit-sha>
  id: faultline
- run: '"$FAULTLINE_CLI" graph build'
```

The runner needs Git and Python 3.10+. The action supports Linux and macOS and
uses pip to build and install the package; pip may download its declared build
backend. PHP is also needed for PHP/Behat source analysis. Installation needs no
Jev key and performs no assessment or test execution.

`FAULTLINE_CLI` and `FAULTLINE_PYTHON` are available to subsequent steps. The
action also returns `cli` and `python` outputs. To run consumer-specific helpers
that import Faultline, use `"$FAULTLINE_PYTHON" path/to/helper.py`. The action does
not modify the consumer's dependencies or replace its default Python executable.

Pinning the action pins the engine. Update that SHA when adopting a new engine;
baseline compatibility still checks the installed engine's source fingerprint.
Keep `faultline.json` and runner-specific integration in the consumer repository.
