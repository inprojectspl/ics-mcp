#!/usr/bin/env bash
# Run the test suite in the locked dev environment.
# Extra arguments go straight to pytest, e.g. scripts/test.sh tests/test_ics_client.py
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec uv run --frozen --extra dev pytest "$@"
