#!/usr/bin/env bash
# Same as ./run.sh: create .venv, install runtime packages, start the app.
# Usage (from this folder):  ./install.sh
exec "$(cd "$(dirname "$0")" && pwd)/run.sh" "$@"
