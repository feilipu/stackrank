# Project Stack Ranker — Overview

**Status (2026-09-18):** implemented on `main` (https://github.com/feilipu/stackrank). This note is the design overview, not a to-do list.

Single-user local web app for ranking and funding sub-projects under a budget. The **overall project** has a user-editable name (default `Untitled project`). Sub-projects sit under that name.

Three complementary decision modes:

1. **Automatic optimize** — exact 0/1 knapsack with precedence constraints.
2. **In-budget success pool** — drag-and-drop ranking that never exceeds the budget.
3. **Elo beauty contest** — pairwise A/B comparisons that produce a live ranking.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| Persistence | SQLite (`data/stackrank.db`; override `STACKRANK_DB`) |
| Templates | Jinja2 |
| Front-end | Server-rendered HTML + vendored HTMX, Tailwind Play, SortableJS |
| Export | `GET /export.html` and contractor HTML; markdown aliases |
| Auth | None |
| Currency base | SGD; also display/set budget in USD and MYR |
| Theme | `system` / `light` / `dark` |

Friend-ready: `./run.sh` (creates `.venv`, installs `requirements.txt`, opens http://127.0.0.1:8000).

Dev with reload after `pip install -r requirements.txt`:

```bash
uvicorn stackrank.main:app --reload --app-dir src
```

Default URL: `http://127.0.0.1:8000`

## Package layout

```
src/stackrank/
  __init__.py          # __version__ = 1.0.0
  main.py              # FastAPI app, routers, static/templates
  db.py                # sqlite connection + schema + seed hook
  currency.py          # SGD/USD/MYR conversion
  optimizer.py         # topological + DP knapsack
  elo.py               # Elo update + pairing
  services.py          # CRUD, pool, contest, settings, export
  seed.py              # 12 realistic example projects
templates/
  base.html
  projects.html
  optimize.html
  pool.html
  contest.html
  export.html
  _partials/           # HTMX fragments
static/
  app.css              # thin extras on top of Tailwind
  app.js               # SortableJS + HTMX helpers
  vendor/              # HTMX, Tailwind Play, SortableJS
tests/
  conftest.py
  test_*.py            # unit, API, chrome, red-team
docs/                  # these design documents
```

There is **no** `models.py`. Rows are `sqlite3.Row` / dicts.

## Implementation order (historical)

These numbered notes were the original build order. They are now descriptions of the shipped app:

1. Data model + SQLite schema + seed (`01-data-model.md`)
2. Algorithms: knapsack, Elo, currency (`02-algorithms.md`)
3. FastAPI services + routes (`03-backend.md`)
4. Jinja/HTMX UI (`04-frontend.md`)
5. Tests matching these specs (`05-testing.md`)

Later notes (`06`–`10`) cover budget rebalance, pool-fill graphic, Projects notes/theme, and export dark theme — all shipped.

Do not introduce React, Node, or a separate API SPA. Tailwind, HTMX, and SortableJS are vendored in `static/vendor/`.
