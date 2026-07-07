#!/bin/bash
set -euo pipefail

# Start the local web UI. Optionally pass a folder path: ./gui.sh "/path/to/negatives"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
URL="http://127.0.0.1:8765"

if [ ! -x "$PY" ]; then
  python3 -m venv "$DIR/.venv"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r "$DIR/requirements.txt"
fi

if command -v open >/dev/null 2>&1; then
  ( sleep 1.5; open "$URL" >/dev/null 2>&1 ) &
fi

exec "$PY" "$DIR/gui.py" "$@"
