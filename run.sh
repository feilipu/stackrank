#!/usr/bin/env bash
# Start Stack Ranker for a technical friend on a Mac.
# Usage (from Terminal, in this folder):  ./run.sh
# Stop with Ctrl+C. Data lives in data/stackrank.db next to this script.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Double-click / GUI Terminal often has a tiny PATH (no Homebrew, no python.org).
export PATH="/usr/local/bin:/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"

HOST="${STACKRANK_HOST:-127.0.0.1}"
PORT="${STACKRANK_PORT:-8000}"
URL="http://${HOST}:${PORT}"

find_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

pause_if_needed() {
  echo
  read -r -p "Press Return to close this window..." _ || true
}

if ! PY="$(find_python)"; then
  echo "Stack Ranker needs Python 3.11 or newer on this Mac."
  echo "Install it from https://www.python.org/downloads/ then run ./run.sh again."
  echo "(The installer from python.org is enough; you do not need Xcode.)"
  pause_if_needed
  exit 1
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
  if ! "$ROOT/.venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "Existing .venv is older than Python 3.11; recreating it."
    rm -rf "$ROOT/.venv"
  fi
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Creating .venv with $PY ..."
  "$PY" -m venv "$ROOT/.venv"
fi

echo "Installing dependencies..."
"$ROOT/.venv/bin/python" -m pip install --upgrade pip >/dev/null
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use — opening $URL"
  open "$URL" 2>/dev/null || true
  echo "If that is not Stack Ranker, stop the other process or run:"
  echo "  STACKRANK_PORT=8001 ./run.sh"
  pause_if_needed
  exit 1
fi

echo "Starting Stack Ranker at $URL"
echo "Stop with Ctrl+C. Your data is saved in:"
echo "  $ROOT/data/stackrank.db"
echo

# Give uvicorn a moment, then open the default browser (not forced to Safari).
(
  sleep 1
  open "$URL" 2>/dev/null || true
) &

exec "$ROOT/.venv/bin/python" -m uvicorn stackrank.main:app \
  --app-dir "$ROOT/src" \
  --host "$HOST" \
  --port "$PORT"
