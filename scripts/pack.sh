#!/usr/bin/env bash
# Build a friend-ready zip: no venv, no live DB, no logs, no .git.
# Usage: ./scripts/pack.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
STAMP="$(date +%Y%m%d)"
OUT="$ROOT/dist/stackrank-$STAMP.zip"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/stackrank-pack.XXXXXX")"
DEST="$STAGE/stackrank"

cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p "$ROOT/dist" "$DEST"

copy_tree() {
  local src="$1"
  rsync -a \
    --exclude '__pycache__' \
    --exclude '*.py[cod]' \
    --exclude '.DS_Store' \
    --exclude 'handoff.md' \
    --exclude 'implementation-summary.md' \
    --exclude 'stackrank_prompt.txt' \
    --exclude 'implementation_plan.md' \
    "$ROOT/$src" "$DEST/"
}

copy_tree src
copy_tree templates
copy_tree static
copy_tree tests
copy_tree scripts
copy_tree docs

cp "$ROOT/README.md" \
   "$ROOT/LICENSE" \
   "$ROOT/run.sh" \
   "$ROOT/install.sh" \
   "$ROOT/requirements.txt" \
   "$ROOT/requirements-dev.txt" \
   "$ROOT/pytest.ini" \
   "$ROOT/.gitignore" \
   "$DEST/"

chmod +x "$DEST/run.sh" "$DEST/install.sh" "$DEST/scripts/pack.sh" "$DEST/scripts/smoke_tabs.py"
mkdir -p "$DEST/data"

# Do not copy data/stackrank.db or logs — first launch seeds the 12 examples.
( cd "$STAGE" && zip -qry "$OUT" stackrank )

echo "Wrote $OUT"
echo "Unzip on the other Mac, then:  cd stackrank && ./run.sh"
echo "To also share your current projects, copy data/stackrank.db into their data/ folder."
