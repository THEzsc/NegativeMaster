#!/bin/bash
set -euo pipefail

# Start the local web UI using the same dependency checks as Windows.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then PY=python3; fi
exec "$PY" "$DIR/launcher.py" gui "$@"
