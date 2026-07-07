#!/bin/bash
set -euo pipefail

# Run the CLI through a local virtual environment.
# First run bootstraps .venv from requirements.txt.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"

if [ ! -x "$PY" ]; then
  python3 -m venv "$DIR/.venv"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r "$DIR/requirements.txt"
fi

exec "$PY" "$DIR/decast.py" "$@"
