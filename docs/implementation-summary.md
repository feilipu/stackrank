# Implementation summary

Canonical next-session notes: **[handoff.md](handoff.md)**. Product spec:
**[stackrank_prompt.txt](../stackrank_prompt.txt)**.

**Status (2026-09-18):** shipped on `main` (https://github.com/feilipu/stackrank).
Do not rebuild. Version `1.0.0`.

## What landed (beyond the original 12-project seed app)

- Overall project rename, in/out colour, notes, search/filter/sort, dep sketch.
- Mutually exclusive sub-projects (symmetric `project_exclusions`).
- Entered cost amount + currency; rate changes recompute `cost_sgd` and rebalance.
- Budget shrink rebalances the pool; over-budget when pins block eject.
- Pool fill (HTML water + duck), sticky 50/50 chrome.
- Theme: system / light / dark.
- Contest undo + recap.
- Export HTML/markdown + contractor list; dark-theme report CSS.
- Friend launch (`run.sh` / `install.sh`) and `scripts/pack.sh`.
- Red-team tests for hostile names, costs, and ids.

## Tests

`.venv/bin/python -m pytest` from the repo root: **105 collected, 104 passed**.

Known drift: `test_missing_dependency_blocks_add_to_pool` (see handoff).

## How to run

```bash
./run.sh
# or
STACKRANK_DB="$PWD/data/stackrank.db" \
  .venv/bin/python -m uvicorn stackrank.main:app --app-dir src \
  --host 127.0.0.1 --port 8000
```

http://127.0.0.1:8000
