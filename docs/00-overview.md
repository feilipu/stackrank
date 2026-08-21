# Project Stack Ranker — Overview

Single-user local web app for ranking and funding sub-projects under a budget. The **overall project** has a user-editable name (default `Untitled project`). Sub-projects sit under that name.

Three complementary decision modes:

1. **Automatic optimize** — exact 0/1 knapsack with precedence constraints.
2. **In-budget success pool** — drag-and-drop ranking that never exceeds the budget.
3. **Elo beauty contest** — pairwise A/B comparisons that produce a live ranking.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| Persistence | SQLite (`data/stackrank.db`) |
| Templates | Jinja2 |
| Front-end | Server-rendered HTML + vendored HTMX, Tailwind Play, SortableJS |
| Export | `GET /export.html` (coloured HTML) and `GET /export.md` (markdown with the same green/amber grouping) |
| Auth | None |
| Currency base | SGD; also display/set budget in USD and MYR |

Friend-ready: `./run.sh` (creates `.venv`, installs `requirements.txt`, opens http://127.0.0.1:8000).

Dev with reload after `pip install -r requirements.txt`:

```bash
uvicorn stackrank.main:app --reload --app-dir src
```

Default URL: `http://127.0.0.1:8000`

## Package layout

```
src/stackrank/
  __init__.py
  main.py              # FastAPI app, routers, static/templates
  db.py                # sqlite connection + schema + seed hook
  models.py            # row dataclasses / typed helpers
  currency.py          # SGD/USD/MYR conversion
  optimizer.py         # topological + DP knapsack
  elo.py               # Elo update + pairing
  services.py          # CRUD, pool, contest, settings
  seed.py              # 12 realistic example projects
templates/
  base.html
  projects.html
  optimize.html
  pool.html
  contest.html
  _partials/           # HTMX fragments
static/
  app.css              # thin extras on top of Tailwind
  app.js               # SortableJS + HTMX helpers
tests/
  test_optimizer.py
  test_elo.py
  test_currency.py
  test_services.py
  test_api.py
docs/                  # these design documents
```

## Implementation order

1. Data model + SQLite schema + seed (`01-data-model.md`)
2. Algorithms: knapsack, Elo, currency (`02-algorithms.md`)
3. FastAPI services + routes (`03-backend.md`)
4. Jinja/HTMX UI (`04-frontend.md`)
5. Tests matching these specs (`05-testing.md`)

Do not introduce React, Node, or a separate API SPA. Tailwind, HTMX, and SortableJS are vendored in `static/vendor/`.
