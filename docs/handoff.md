# Handoff — Project Stack Ranker

**Date:** 2026-09-18
**Repo:** https://github.com/feilipu/stackrank (`main`)
**Local:** `/Users/phillip/Projects/stackrank`
**Status:** Shipped. Do not rebuild. Extend only if asked.

This is the living status note for the next session. Product spec:
[`stackrank_prompt.txt`](../stackrank_prompt.txt). Design detail:
[`00-overview.md`](00-overview.md) … [`10-export-dark-theme.md`](10-export-dark-theme.md).
Rebuild DAG (historical): [`implementation_plan.md`](../implementation_plan.md).

---

## What this is

Single-user local web app for ranking sub-projects under a budget. Five tabs:

1. **Projects** — CRUD, notes, search/filter/sort, dep sketch, excludes.
2. **Optimize** — exact 0/1 knapsack over ancestor-closed sets (`outcome` / `elo` / `blend`). Apply replaces the pool and redirects to `/pool`.
3. **Pool** — drag or click into an In-Budget Success Pool. Missing deps are pulled in when they fit. Lowest-metric unpinned items eject; pinned stay. Exclusives cannot both sit in the pool. Duck fill graphic.
4. **Contest** — pairwise Elo (K = 32), skip, undo last match, reset.
5. **Export** — coloured HTML + markdown; contractor list of accepted (in-pool) items; `?ccy=SGD|USD|MYR`.

Money is stored in **SGD**. USD and MYR are display/input only (“foreign per 1 SGD”, defaults `0.74` / `3.45`). Empty DB seed: 12 example projects, budget **S$250,000**. Theme: system / light / dark.

There is **no** `models.py`. Rows are `sqlite3.Row` / dicts.

---

## How to run

Friend path: `./run.sh` (or `./install.sh`). Detached uvicorn, **no `--reload`**.

```bash
cd /Users/phillip/Projects/stackrank
STACKRANK_DB="$PWD/data/stackrank.db" \
  .venv/bin/python -m uvicorn stackrank.main:app --app-dir src \
  --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 (redirects to `/projects`).

Env: `STACKRANK_DB` (default `data/stackrank.db`), `STACKRANK_HOST`, `STACKRANK_PORT`.
Live data is gitignored. Do not commit it. Do not put a user’s catalogue in docs.

Tests:

```bash
.venv/bin/python -m pytest
```

Temp SQLite only. They never touch `data/stackrank.db`.

---

## Tests (2026-09-18)

`.venv/bin/python -m pytest` collects **105** tests. **104 pass**.

Known drift (do not “fix” unless asked):

- `tests/test_services.py::test_missing_dependency_blocks_add_to_pool` expects `ServiceError` 409 when A depends on B and B is not pooled.
- Live `add_to_pool` **recursively adds missing deps** first. Align the test with that behaviour, or change the product — not both silently.

Red-team files: `tests/test_bad_*.py` (empty/huge/XSS/SQL-ish names, bad cost, bad ids, budget SQL).

Optional UI smoke (not in pytest): `scripts/smoke_tabs.py` (Playwright WebKit).

---

## Layout

```
src/stackrank/
  __init__.py      __version__ = 1.0.0
  main.py          FastAPI routes, Jinja context, LAST_OPTIMIZE
  db.py            SQLite connect + schema + seed hook
  services.py      CRUD, pool, contest, settings, export
  optimizer.py     ancestor-closed exact search (cycle → OptimizerError)
  elo.py           K=32 update + pair picker
  currency.py      SGD/USD/MYR + blend scoring
  seed.py          12 example projects
templates/         pages + _partials/ fragments
static/            app.css, app.js, favicon.svg, vendor/ (no CDN)
tests/             conftest + unit/api/chrome/red-team
docs/              design + this file
```

Stack: FastAPI + Jinja2 + HTMX 2 + Tailwind Play + SortableJS, all vendored.
No Node build. No auth.

---

## Behaviour that is in

| Area | Notes |
|---|---|
| Project CRUD | Create / in-place edit / delete. Unique name. Cost/outcome > 0. Notes max 500. No self-deps or cycles. Symmetric excludes. |
| Search | `q`, `pool=all\|in\|out`, `sort`, `dir` on GET `/projects`. |
| Budget / rates | `POST /settings/budget`, `POST /settings/rates`. Shrink rebalances the pool. Header chip OOB. |
| Optimize | Metric radios. Last run in `settings.last_optimize_json`. Apply → `/pool?applied=N`. |
| Pool | Add pulls deps; eject unpinned; exclusives eject the other side; pin; reorder; HTML duck fill. |
| Contest | Start / A-or-B / skip / undo / stop / reset (`confirm=yes`). |
| Export | `/export.html`, `/export.md`, `/export/contractor.html`, `/export/contractor.md`. |
| Theme | `POST /settings/theme`; stays on current tab. |
| Seed | Only when `projects` is empty. |

Blend: `0.6 * outcome + 0.4 * (elo / 15)`.

---

## Quick route map

| Method | Path | Result |
|---|---|---|
| GET | `/` | 307 → `/projects` |
| GET/POST | `/projects`, `/projects/{id}`, `/projects/{id}/edit`, `/projects/{id}/delete` | CRUD + search |
| POST | `/settings/budget`, `/settings/rates`, `/settings/pool-metric`, `/settings/name`, `/settings/theme` | settings |
| GET | `/export.html`, `/export.md`, `/export`, `/export/contractor.html`, `/export/contractor.md` | reports |
| GET/POST | `/optimize`, `/optimize/run`, `/optimize/apply` | knapsack |
| GET/POST | `/pool`, `/pool/add/{id}`, `/pool/remove/{id}`, `/pool/reorder`, `/pool/pin/{id}` | pool board |
| GET/POST | `/contest`, `/contest/start`, `/contest/choose`, `/contest/skip`, `/contest/undo`, `/contest/stop`, `/contest/reset` | contest |

Validation: `ServiceError` → `_partials/errors.html` + `HX-Retarget: #flash` (422/409). Unexpected exceptions → 503 + same fragment.

---

## Helpers (current)

omlx on `127.0.0.1:11435` (user starts it). Types: `qwen-coder` / `local-coder`, failover `gemma-crew` / `local-failover`. Tiny slices only: one file, one acceptance check. Do not start or restart omlx. Do not start Ollama. Do not auto-restart uvicorn unless asked.

Older notes below mentioned Ollama `qwen38-coder`. That path is retired.

---

## Open polish (only if asked)

- Align `test_missing_dependency_blocks_add_to_pool` with pull-in-deps.
- n>24 ILP fallback (not implemented; same recursion).
- Tailwind Play `defer` can FOUC.

Do **not** add React, auth, a live FX API, or a second frontend.

---

## History (do not re-litigate)

**2026-08:** P0 Projects 503 after Optimize → Apply. `project_context` read `r["project_id"]` from `pool_rows()` which keys `id`. Fix: `pool_ids = {int(r["id"]) …}`. HTMX `request.state.is_hx` middleware. Rename, in/out colour, markdown export.

**2026-08-19+:** Budget rebalance, pool-fill duck, notes, search/sort, theme, contest undo, contractor export, dark export CSS, mutually exclusive excludes, red-team tests.

**2026-09-18:** Docs and `stackrank_prompt.txt` brought in line with the shipped tree. Public remote is `feilipu/stackrank`.

Commands the next agent should run first:

```bash
.venv/bin/python -m pytest -q
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/projects
```

If port 8000 is down and the user wants the server: detached uvicorn as above, with `STACKRANK_DB` if they have a personal database. If they want Safari: `open -a Safari http://127.0.0.1:8000`.
