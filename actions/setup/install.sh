#!/usr/bin/env bash
set -euo pipefail

# GitHub downloads the action and package together at the caller's pinned SHA.
# Do not install into, or change Python dependencies in, the consumer checkout.
faultline_environment=$(mktemp -d "${RUNNER_TEMP:?}/faultline.XXXXXXXX")
"${FAULTLINE_SETUP_PYTHON:-python3}" -m venv "$faultline_environment"
faultline_python="$faultline_environment/bin/python"
"$faultline_python" -m pip install --disable-pip-version-check --no-deps "${FAULTLINE_ACTION_PATH:?}/../.."
"$faultline_python" -m faultline.cli --help >/dev/null

{
  echo "python=$faultline_python"
  echo "cli=$faultline_environment/bin/faultline"
} >> "${GITHUB_OUTPUT:?}"
{
  echo "FAULTLINE_PYTHON=$faultline_python"
  echo "FAULTLINE_CLI=$faultline_environment/bin/faultline"
} >> "${GITHUB_ENV:?}"
