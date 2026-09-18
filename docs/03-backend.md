# Backend (FastAPI)

**Status (2026-09-18):** routes below are live on `stackrank.main:app`.

App object: `stackrank.main:app`.

On startup: ensure `data/` exists, apply schema, seed if empty.

Templates from `templates/`. Static from `static/` at `/static`.

HTML pages use Jinja. Mutations that the UI follows with HTMX return HTML fragments.

## Pages (GET)

| Path | Template | Purpose |
|---|---|---|
| `/` | redirect `/projects` | |
| `/projects` | `projects.html` | CRUD list + budget card |
| `/optimize` | `optimize.html` | metric picker + results |
| `/pool` | `pool.html` | two columns + totals |
| `/contest` | `contest.html` | two cards + leaderboard |
| `/export.html` | coloured HTML report (inline) | green = in pool, amber = excluded |
| `/export.md` (alias `/export`) | markdown attachment | same grouping |
| `/export/contractor.html` | accepted (in-pool) only | Total = pool cost in `?ccy=` |
| `/export/contractor.md` | contractor markdown | same |

Shared chrome in `base.html`: editable overall project name, nav tabs, **Export** link, budget chip (3 currencies), flash/error region (`#flash`).

## Project routes

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/projects` | query `q`, `pool`, `sort`, `dir` | full page |
| POST | `/projects` | form: name, description, notes, cost, cost_currency, outcome, depends_on (multi), excludes (multi) | redirect or fragment list |
| GET | `/projects/{id}/edit` | | edit form fragment |
| POST | `/projects/{id}` | same as create | replace row + close form |
| POST | `/projects/{id}/delete` | | refresh list |
| POST | `/settings/budget` | amount, currency | refresh budget card |
| POST | `/settings/rates` | usd_per_sgd, myr_per_sgd | refresh conversions |
| POST | `/settings/name` | `name` (1–80 chars) | persist overall title; HTMX returns `#header-title` fragment, else 303 `/projects` |
| POST | `/settings/theme` | `theme`, optional `next` | `system` / `light` / `dark`; stay on allowlisted tab |
| GET | `/export.html` | `?ccy=` | `text/html` inline; filename from slugged `project_name` |
| GET | `/export.md` | `?ccy=` | `text/markdown` attachment; filename from slugged `project_name` |
| GET | `/export/contractor.html` | `?ccy=` | in-pool only; Total in selected currency |
| GET | `/export/contractor.md` | `?ccy=` | contractor markdown |

Cost may be entered in SGD/USD/MYR; convert to SGD before store.

Validation errors: HTTP 422 with an HTML `_partials/errors.html` fragment (`HX-Retarget` `#flash`).

## Optimize routes

| Method | Path | Notes |
|---|---|---|
| GET | `/optimize` | last run from `LAST_OPTIMIZE` and `settings.last_optimize_json` |
| POST | `/optimize/run` | form `metric=outcome\|elo\|blend` — persist metric on settings, return results fragment |
| POST | `/optimize/apply` | write selected ids into pool, then 303 / `HX-Redirect` to `/pool?applied=N` |

## Pool routes

| Method | Path | Notes |
|---|---|---|
| GET | `/pool` | two lists |
| POST | `/pool/add/{id}` | add with ejection |
| POST | `/pool/remove/{id}` | remove if safe |
| POST | `/pool/reorder` | `ids` in order (form list) |
| POST | `/pool/pin/{id}` | toggle pin |
| POST | `/settings/pool-metric` | `elo\|outcome\|blend` |

All pool POSTs return `_partials/pool_board.html` (both columns + totals) so HTMX can swap `#pool-board`.

On block (cannot fit / dependents still pooled / pinned exclusive): 409 + error fragment. Missing deps are pulled in when they fit.

Adding a project that **excludes** one already in the pool ejects that alternative (and its unpinned pooled dependents) and OOB-swaps `#flash` naming what left. Budget ejections on add or on `POST /settings/budget` do the same.

## Contest routes

| Method | Path | Notes |
|---|---|---|
| GET | `/contest` | cards + table |
| POST | `/contest/start` | pick first pair |
| POST | `/contest/choose` | `winner_id` |
| POST | `/contest/skip` | |
| POST | `/contest/undo` | restore Elo/W-L from last `contest_matches` row |
| POST | `/contest/stop` | |
| POST | `/contest/reset` | confirm via `confirm=yes` hidden field |

Return `_partials/contest_board.html`.

## Markdown export

`services.export_markdown(conn)` and `services.export_html(conn)` share the same grouping and Pool-board colours (green `#ecfdf5` / `#047857` = in pool, amber `#fff7ed` / `#c2410c` = excluded).

```
# {project_name}

Budget: S$…  ·  US$…  ·  RM…
Pool: N of M in pool · remaining S$…  ·  US$…  ·  RM…

Colour key + count table

## In-Budget Success Pool
(green banner, name index, then cards in pool order — or “_None selected._”)
- Status: In pool (pinned) | In pool

## Excluded
(amber banner, name index, then cards in `list_projects` order — or “_None excluded._”)
- Status: Excluded
```

Groups are exclusive: a sub-project appears in only one section. Markdown embeds `<style>` plus inline-styled badges/cards so VS Code / Typora / Obsidian previews show colour. User text inside HTML cards is escaped. Nav **Export** opens `/export.html` (inline); that page links to `/export.md`.

## Error policy

- Never 500 on user validation. Cycle, missing deps, empty name → 422/409 + readable message.
- SQL constraint failures map to the same fragments.
- Log unexpected exceptions; show “Something went wrong” in `#flash`.

## Connection helper

`get_db()` yields a `sqlite3.Connection` with `row_factory = sqlite3.Row`, `isolation_level = None` + explicit `BEGIN IMMEDIATE` for writes (pool add/eject must be one transaction).
