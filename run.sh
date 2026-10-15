#!/bin/bash
set -euo pipefail

# Run the CLI through a local virtual environment.
# First run bootstraps .venv from requirements.txt.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"

if [ ! -x "$PY" ]; then PY=python3; fi
exec "$PY" "$DIR/launcher.py" cli "$@"
