# Implementation plan — rebuild Project Stack Ranker

**Status (2026-09-18):** the rebuild on `main` is done. This file is a
historical DAG for a from-scratch rebuild only. Day-to-day work: read
`stackrank_prompt.txt` and `docs/handoff.md`, then change the live tree.

Parent document. Pair with `stackrank_prompt.txt` (the product). Rebuild in
this order **only if the user asks to rebuild**. **Do not hand this file to
Qwen.** Each slice below is one worker prompt: one path, one check.

## Orchestration

- Helper: `qwen-coder` (`local-coder`) first. If it stalls (~15 min, no write)
  or truncates: cancel, same slice to `local-failover` (`gemma-crew`), then
  cut smaller and retry Qwen.
- One helper at a time. Parent does not do the helper’s file when the user
  said the helper should.
- Slice = one function **or** one route **or** one partial **or** one test
  **or** one docs paragraph. No “also update tests/docs”.
- Acceptance is exactly the named pytest or curl.
- Do not commit unless asked. App server: detached uvicorn, no `--reload`
  unless asked. No React / auth / live FX / second frontend.

A passing slice means the named check is green. Do not start the next slice
until then.

Python: 3.11+. Tests: `.venv/bin/python -m pytest <nodeid>`.

---

## Phase 0 — GitHub skeleton

| ID | File | Work | Acceptance |
|---|---|---|---|
| S001 | `.gitignore` | Ignore `.venv/`, `__pycache__/`, `data/*.db`, `data/*.log`, `.pytest_cache/`, `dist/`, `.DS_Store`. Keep `data/.gitkeep`. | `test -f .gitignore && rg -q 'data/\*\.db' .gitignore` |
| S002 | `LICENSE` | MIT, year 2026. | `rg -q 'MIT License' LICENSE` |
| S003 | `requirements.txt` | Pin FastAPI, uvicorn, Jinja2, python-multipart, pydantic (no pytest). | `rg -q '^fastapi==' requirements.txt` |
| S004 | `requirements-dev.txt` | `-r requirements.txt` plus pytest, httpx. Playwright optional. | `rg -q '^pytest==' requirements-dev.txt` |
| S005 | `pytest.ini` | `testpaths = tests`, `pythonpath = src`. | `rg -q 'pythonpath' pytest.ini` |
| S006 | `src/stackrank/__init__.py` | Empty package. | `test -f src/stackrank/__init__.py` |
| S007 | `data/.gitkeep` | Empty file. | `test -f data/.gitkeep` |
| S008 | `tests/conftest.py` | Fixtures: tmp `db_path`, `conn` (schema+seed), `app` with DB override, `client = TestClient`. | `.venv/bin/python -c "import tests.conftest"` |

---

## Phase 1 — Currency (`src/stackrank/currency.py`)

Constants: `CURRENCIES = ("SGD","USD","MYR")`, `SYMBOLS`, `BLEND_OUTCOME_WEIGHT=0.6`,
`BLEND_ELO_WEIGHT=0.4`, `ELO_SCALE=15.0`.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S010 | `src/stackrank/currency.py` | Create module with constants only. | `rg -q 'BLEND_OUTCOME_WEIGHT' src/stackrank/currency.py` |
| S011 | `src/stackrank/currency.py` | Add `to_usd(sgd, usd_per_sgd)`. | `.venv/bin/python -c "from stackrank.currency import to_usd; assert abs(to_usd(100,0.74)-74)<1e-9"` |
| S012 | `src/stackrank/currency.py` | Add `to_myr`. | `.venv/bin/python -c "from stackrank.currency import to_myr; assert abs(to_myr(100,3.45)-345)<1e-9"` |
| S013 | `src/stackrank/currency.py` | Add `from_usd`. | `.venv/bin/python -c "from stackrank.currency import from_usd,to_usd; assert abs(from_usd(to_usd(99,0.74),0.74)-99)<1e-9"` |
| S014 | `src/stackrank/currency.py` | Add `from_myr`. | `.venv/bin/python -c "from stackrank.currency import from_myr,to_myr; assert abs(from_myr(to_myr(50,3.45),3.45)-50)<1e-9"` |
| S015 | `src/stackrank/currency.py` | Add `to_sgd(amount, currency, usd, myr)` SGD/USD/MYR else ValueError. | `.venv/bin/python -c "from stackrank.currency import to_sgd; assert abs(to_sgd(74,'USD',0.74,3.45)-100)<1e-9"` |
| S016 | `src/stackrank/currency.py` | Add `blend(outcome, elo)`. | `.venv/bin/python -c "from stackrank.currency import blend; assert abs(blend(100,1500)-(0.6*100+0.4*100))<1e-9"` |
| S017 | `src/stackrank/currency.py` | Add `metric_value(metric, outcome, elo)` for outcome/elo/blend. | `.venv/bin/python -c "from stackrank.currency import metric_value; assert metric_value('elo',1,1500)==1500"` |
| S018 | `src/stackrank/currency.py` | Add `format_triple` / `format_money` (S$ US$ RM). | `.venv/bin/python -c "from stackrank.currency import format_money; t=format_money(1000,0.74,3.45); assert 'S$' in t and 'US$' in t and 'RM' in t"` |
| S019 | `tests/test_currency.py` | `test_from_usd_round_trips_to_original_sgd`. | `.venv/bin/python -m pytest tests/test_currency.py::test_from_usd_round_trips_to_original_sgd -q` |

---

## Phase 2 — Elo (`src/stackrank/elo.py`)

`K_FACTOR = 32`, `DEFAULT_ELO = 1500`.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S020 | `src/stackrank/elo.py` | `expected(a, b) = 1/(1+10**((b-a)/400))`. | `.venv/bin/python -c "from stackrank.elo import expected; assert abs(expected(1500,1500)-0.5)<1e-9"` |
| S021 | `src/stackrank/elo.py` | `update_ratings(a, b, score_a)` returns `(a', b')`. | `.venv/bin/python -c "from stackrank.elo import update_ratings; a,b=update_ratings(1500,1500,1); assert abs(a-1516)<0.1 and abs(b-1484)<0.1"` |
| S022 | `src/stackrank/elo.py` | `choose_pair(projects, history)` unseen closest Elo, shuffle sides. | `.venv/bin/python -c "from stackrank.elo import choose_pair"` |
| S023 | `tests/test_elo.py` | Equal 1500, A wins → ~1516 / ~1484. | `.venv/bin/python -m pytest tests/test_elo.py -k 1500 -q` |

---

## Phase 3 — Optimizer (`src/stackrank/optimizer.py`)

Exact ancestor-closed 0/1 DP. Costs integer SGD. Raise on cycles.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S030 | `src/stackrank/optimizer.py` | `optimize(projects, deps, budget_sgd, metric)` empty set → selected `[]`. | `.venv/bin/python -m pytest tests/test_optimizer.py -k empty -q` |
| S031 | `tests/test_optimizer.py` | Single cheaper than budget selected. | `.venv/bin/python -m pytest tests/test_optimizer.py -k single -q` |
| S032 | `src/stackrank/optimizer.py` | Too-costly singleton excluded. | `.venv/bin/python -m pytest tests/test_optimizer.py -k costlier -q` |
| S033 | `src/stackrank/optimizer.py` | A depends on B: selecting A implies B. | `.venv/bin/python -m pytest tests/test_optimizer.py -k depend -q` |
| S034 | `tests/test_optimizer.py` | Result ancestor-closed and `total_cost <= budget`. | `.venv/bin/python -m pytest tests/test_optimizer.py -k closed -q` |

If a test file does not exist yet, the slice that first needs it **creates only that one test**.

---

## Phase 4 — SQLite (`src/stackrank/db.py`)

Schema as in `docs/01-data-model.md` plus later columns: `projects.notes`,
`projects.cost_amount`, `projects.cost_currency`, `settings.project_name`,
`settings.last_optimize_json`, `settings.last_cost_currency`, `settings.theme`.

`apply_schema` uses `CREATE TABLE IF NOT EXISTS` then `ALTER` for missing
columns. `cost_amount` backfill: `UPDATE … SET cost_amount = cost_sgd` when
added. Default `cost_currency` SGD, `theme` system.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S040 | `src/stackrank/db.py` | `connect`, `resolve_db_path`, `DEFAULT_DB`, PRAGMA FK, Row factory, isolation_level None. | `.venv/bin/python -c "from stackrank.db import connect, apply_schema"` |
| S041 | `src/stackrank/db.py` | `SCHEMA` string: settings, projects, project_dependencies, pool_items, contest_matches. | `rg -q 'CREATE TABLE IF NOT EXISTS projects' src/stackrank/db.py` |
| S042 | `src/stackrank/db.py` | `apply_schema` CREATE + singleton settings insert if missing. | `.venv/bin/python -c "from stackrank.db import connect,apply_schema; c=connect(':memory:'); apply_schema(c); assert c.execute('select id from settings').fetchone()[0]==1"` |
| S043 | `src/stackrank/db.py` | ALTER notes, last_cost_currency, theme, cost_amount, cost_currency, project_name, last_optimize_json. | `rg -q 'cost_amount' src/stackrank/db.py` |
| S044 | `src/stackrank/seed.py` | `SEED_PROJECTS` 12 rows (Identity & SSO 18000 … Launch campaign 12000) + deps as in docs/01. | `rg -q 'Identity & SSO' src/stackrank/seed.py` |
| S045 | `src/stackrank/seed.py` | `seed_if_empty`: insert cost_sgd=cost_amount, cost_currency SGD, Elo 1500. | `.venv/bin/python -c "from stackrank.db import connect,apply_schema; from stackrank.seed import seed_if_empty; c=connect(':memory:'); apply_schema(c); seed_if_empty(c); assert c.execute('select count(*) from projects').fetchone()[0]==12"` |

---

## Phase 5 — Services: settings and CRUD (`src/stackrank/services.py`)

`ServiceError(message, status_code=422)`. `EPS = 1e-6`. Writes: `BEGIN IMMEDIATE`.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S050 | `src/stackrank/services.py` | Module + `class ServiceError` + `EPS`. | `rg -q 'class ServiceError' src/stackrank/services.py` |
| S051 | `src/stackrank/services.py` | `get_settings`, `list_projects`, `get_project`. | `.venv/bin/python -c "from stackrank.services import get_settings"` |
| S052 | `src/stackrank/services.py` | `dependencies_map`, `dependents_map`, `names_by_id`. | `rg -q 'def dependencies_map' src/stackrank/services.py` |
| S053 | `src/stackrank/services.py` | `_would_cycle`. | `rg -q 'def _would_cycle' src/stackrank/services.py` |
| S054 | `src/stackrank/services.py` | `_validate_project`, `_norm_cost_currency`. | `rg -q 'def _norm_cost_currency' src/stackrank/services.py` |
| S055 | `src/stackrank/services.py` | `create_project` (notes, cost_amount, cost_currency, cost_sgd, last_cost_currency). | `.venv/bin/python -m pytest tests/test_services.py::test_create_persists_entered_cost_and_currency -q` |
| S056 | `src/stackrank/services.py` | `update_project` same fields + last_cost_currency. | `.venv/bin/python -m pytest tests/test_services.py::test_update_unchanged_cost_keeps_entered_amount -q` |
| S057 | `src/stackrank/services.py` | `delete_project` cascades. | `rg -q 'def delete_project' src/stackrank/services.py` |
| S058 | `src/stackrank/services.py` | `update_project_name`. | `rg -q 'def update_project_name' src/stackrank/services.py` |
| S059 | `src/stackrank/services.py` | `update_budget` + `rebalance_pool` call. | `rg -q 'def update_budget' src/stackrank/services.py` |
| S060 | `src/stackrank/services.py` | `refresh_project_costs` + `update_rates` (recompute SGD, rebalance). | `.venv/bin/python -m pytest tests/test_services.py::test_rate_change_recomputes_cost_sgd_from_entered -q` |
| S061 | `src/stackrank/services.py` | `set_optimize_metric`, `set_pool_metric`, `set_theme`. | `rg -q 'def set_theme' src/stackrank/services.py` |
| S062 | `tests/test_services.py` | Circular dependency rejected. | `.venv/bin/python -m pytest tests/test_services.py::test_circular_dependency_rejected -q` |
| S063 | `tests/test_services.py` | Self-dependency rejected. | `.venv/bin/python -m pytest tests/test_services.py::test_self_dependency_rejected -q` |

---

## Phase 6 — Pool services

| ID | File | Work | Acceptance |
|---|---|---|---|
| S070 | `src/stackrank/services.py` | `pool_rows`, `budget_fill`. | `rg -q 'def budget_fill' src/stackrank/services.py` |
| S071 | `src/stackrank/services.py` | `rebalance_pool(conn, budget, protect_ids=None)`. | `rg -q 'def rebalance_pool' src/stackrank/services.py` |
| S072 | `src/stackrank/services.py` | `add_to_pool` (eject lowest unpinned; pull missing deps when possible; pin-block → 409). | `.venv/bin/python -m pytest tests/test_services.py::test_add_expensive_project_ejects_lowest_unpinned_by_pool_metric -q` |
| S073 | `src/stackrank/services.py` | `remove_from_pool` (block if pooled dependent remains). | `rg -q 'def remove_from_pool' src/stackrank/services.py` |
| S074 | `src/stackrank/services.py` | `reorder_pool`, `toggle_pin`. | `rg -q 'def toggle_pin' src/stackrank/services.py` |
| S075 | `src/stackrank/services.py` | `apply_optimize_to_pool`. | `rg -q 'def apply_optimize_to_pool' src/stackrank/services.py` |
| S076 | `src/stackrank/services.py` | `optimize_now`, `save_last_optimize`, `load_last_optimize`. | `rg -q 'def load_last_optimize' src/stackrank/services.py` |

---

## Phase 7 — Contest services

| ID | File | Work | Acceptance |
|---|---|---|---|
| S080 | `src/stackrank/services.py` | `start_contest`, `stop_contest`, `_advance_pair`. | `rg -q 'def start_contest' src/stackrank/services.py` |
| S081 | `src/stackrank/services.py` | `contest_choose`. | `rg -q 'def contest_choose' src/stackrank/services.py` |
| S082 | `src/stackrank/services.py` | `contest_skip` (shown++, no Elo). | `rg -q 'def contest_skip' src/stackrank/services.py` |
| S083 | `src/stackrank/services.py` | `contest_undo` (restore from last `contest_matches` row). | `rg -q 'def contest_undo' src/stackrank/services.py` |
| S084 | `src/stackrank/services.py` | `contest_last_match`, `contest_progress`. | `rg -q 'def contest_last_match' src/stackrank/services.py` |
| S085 | `src/stackrank/services.py` | `reset_elo(confirm="yes")`. | `rg -q 'def reset_elo' src/stackrank/services.py` |
| S086 | `tests/test_projects_chrome.py` | `test_contest_choose_then_undo_restores_elo` (or equivalent in test_api). | `.venv/bin/python -m pytest tests/test_projects_chrome.py::test_contest_choose_then_undo_restores_elo -q` |

---

## Phase 8 — FastAPI app (`src/stackrank/main.py`)

HTMX mutations return fragments. 422/409 → `_partials/errors.html`,
`HX-Retarget: #flash`. Never 500 on validation.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S090 | `src/stackrank/main.py` | FastAPI app, lifespan schema+seed, mount `/static`, Jinja templates. | `rg -q 'FastAPI' src/stackrank/main.py` |
| S091 | `src/stackrank/main.py` | `ServiceError` handler + generic handler. | `rg -q 'handle_service_error' src/stackrank/main.py` |
| S092 | `src/stackrank/main.py` | `GET /` → 307 `/projects`. | `.venv/bin/python -c "from stackrank.main import app"` |
| S093 | `src/stackrank/main.py` | `project_payload`, `read_body`, `to_number`. | `rg -q 'def project_payload' src/stackrank/main.py` |
| S094 | `src/stackrank/main.py` | `project_context` (q/pool/sort/dir, notes, entered cost fields, theme). | `rg -q 'def project_context' src/stackrank/main.py` |
| S095 | `src/stackrank/main.py` | `pool_context`, `contest_context`. | `rg -q 'def pool_context' src/stackrank/main.py` |
| S096 | `src/stackrank/main.py` | GET `/projects` + POST create/update/delete + GET edit. | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/projects` *(or TestClient)* |
| S097 | `tests/test_api.py` | GET `/projects` 200 contains a seeded name. | `.venv/bin/python -m pytest tests/test_api.py::test_projects_page_ok -q` |
| S098 | `src/stackrank/main.py` | POST `/settings/budget`, `/settings/rates`, `/settings/name`. | `rg -q 'settings/budget' src/stackrank/main.py` |
| S099 | `src/stackrank/main.py` | POST `/settings/theme` 303 to allowlisted `next` else `/projects`. | `.venv/bin/python -m pytest tests/test_projects_chrome.py::test_theme_post_stays_on_current_tab -q` |
| S100 | `src/stackrank/main.py` | Optimize GET/POST run/apply. | `rg -q 'optimize/run' src/stackrank/main.py` |
| S101 | `src/stackrank/main.py` | Pool add/remove/reorder/pin + pool-metric. | `rg -q 'pool/add' src/stackrank/main.py` |
| S102 | `src/stackrank/main.py` | Contest start/choose/skip/stop/reset/undo. | `rg -q 'contest/undo' src/stackrank/main.py` |
| S103 | `src/stackrank/main.py` | Export HTML/MD + contractor HTML/MD, `ccy` query. | `rg -q 'export/contractor.html' src/stackrank/main.py` |

---

## Phase 9 — Export (`services.py` helpers)

Compact tables. Contractor: in-pool only, no Budget in report body, Total =
sum of pool `cost_sgd` in selected ccy.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S110 | `src/stackrank/services.py` | `_export_snapshot` including currency, spent_sgd. | `rg -q 'def _export_snapshot' src/stackrank/services.py` |
| S111 | `src/stackrank/services.py` | `_cost_cell` / `_cost_of`. | `rg -q 'def _cost_of' src/stackrank/services.py` |
| S112 | `src/stackrank/services.py` | `export_markdown` pool table then excluded. | `.venv/bin/python -m pytest tests/test_export_markdown_leads_with_pool.py -k markdown -q` |
| S113 | `src/stackrank/services.py` | `_html_sheet`, `_SHEET_STYLE` print 8pt, `export_html_parts`. | `rg -q 'table.sheet' src/stackrank/services.py` |
| S114 | `src/stackrank/services.py` | Contractor markdown + HTML parts; no Budget in report slice. | `.venv/bin/python -m pytest tests/test_export_markdown_leads_with_pool.py -k contractor -q` |
| S115 | `tests/test_export_markdown_leads_with_pool.py` | `test_export_ccy_usd_converts_costs` (Identity 18000×0.74 → US$13,320). | `.venv/bin/python -m pytest tests/test_export_markdown_leads_with_pool.py::test_export_ccy_usd_converts_costs -q` |

---

## Phase 10 — Templates (one partial per slice)

Vendored assets already in `static/vendor/` (HTMX, Tailwind Play, SortableJS).
Do not fetch CDN at runtime.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S120 | `templates/base.html` | html data-theme, blocking dark script, Tailwind `darkMode:'class'`, sticky `site-top`, nav tabs with selected `nav-active rounded bg-indigo-600 text-white`, theme_switch include, `#flash`. | `rg -q 'nav-active rounded bg-indigo-600 text-white' templates/base.html` |
| S121 | `templates/_partials/theme_switch.html` | System/Light/Dark; selected `bg-indigo-600 text-white`; hidden `next={{ request.url.path }}`. | `rg -q 'name="next"' templates/_partials/theme_switch.html` |
| S122 | `templates/_partials/header_title.html` | Editable project name POST `/settings/name`. | `rg -q 'settings/name' templates/_partials/header_title.html` |
| S123 | `templates/_partials/errors.html` | Flash message markup. | `test -f templates/_partials/errors.html` |
| S124 | `templates/_partials/flash.html` | ok/error classes. | `test -f templates/_partials/flash.html` |
| S125 | `templates/_partials/budget_card.html` | Budget amount+currency + FX rates; `#header-budget` OOB. | `rg -q 'budget-rates-card' templates/_partials/budget_card.html` |
| S126 | `templates/projects.html` | `#projects-content`, budget include, `#project-list`. | `rg -q 'projects-content' templates/projects.html` |
| S127 | `templates/_partials/project_list.html` | Search/sort/filter GET form, add form (`last_cost_currency`), cards sub-in/sub-out, notes, efficiency, dep_sketch. | `rg -q 'last_cost_currency' templates/_partials/project_list.html` |
| S128 | `templates/_partials/project_edit.html` | `cost_amount` + `cost_currency` (not budget_currency, not reverse SGD). | `rg -q 'name="cost".*cost_amount' templates/_partials/project_edit.html` |
| S129 | `templates/_partials/dep_sketch.html` | Dynamic SVG width, no `[:14]` clip, class `dep-sketch`. | `.venv/bin/python -m pytest tests/test_projects_chrome.py::test_projects_page_includes_dep_sketch_svg -q` |
| S130 | `templates/_partials/empty_art.html` | One inline SVG style. | `test -f templates/_partials/empty_art.html` |
| S131 | `templates/optimize.html` | Metric radios + run + results include. | `test -f templates/optimize.html` |
| S132 | `templates/_partials/optimize_results.html` | Selected/excluded tables + apply. | `test -f templates/_partials/optimize_results.html` |
| S133 | `templates/pool.html` | `sticky_sub`: pool-split budget + pool_fill + pool_metric; board region. | `rg -q 'pool-split' templates/pool.html` |
| S134 | `templates/_partials/pool_board.html` | `#pool-totals`, available/pooled lists, Sortable ids. | `rg -q 'pool-totals' templates/_partials/pool_board.html` |
| S135 | `templates/_partials/pool_fill.html` | Duck pool HTML; `data-fill`; caption `% FULL`. | `.venv/bin/python -m pytest tests/test_pool_fill.py -q` |
| S136 | `templates/_partials/pool_metric.html` | Auto-eject radios. | `test -f templates/_partials/pool_metric.html` |
| S137 | `templates/contest.html` | `#contest-content` + board include. | `rg -q 'contest-content' templates/contest.html` |
| S138 | `templates/_partials/contest_board.html` | Two cards, buttons, undo, recap, leaderboard. | `rg -q 'contest/undo' templates/_partials/contest_board.html` |
| S139 | `templates/export.html` | Extends base; `export_style` + `export_body`. | `rg -q 'export_body' templates/export.html` |

---

## Phase 11 — CSS / JS / favicon

Play utilities lose to later `app.css` only with higher specificity or
`!important`. Dark rules must beat `bg-white` and export `_SHEET_STYLE`.

| ID | File | Work | Acceptance |
|---|---|---|---|
| S140 | `static/favicon.svg` | Stacked-bars indigo mark. | `test -f static/favicon.svg` |
| S141 | `static/app.js` | Sortable on `#available-list` / `#pool-list`; add/remove/reorder via htmx.ajax; disable while in flight. | `rg -q 'Sortable' static/app.js` |
| S142 | `static/app.css` | Light extras: sub-in/out, nav-active, site-top, pool-split, pool-fill, flash. | `rg -q 'sub-in' static/app.css` |
| S143 | `static/app.css` | `html.dark` page + site-top; `a.nav-active` indigo-600 + white. | `rg -q 'html.dark a.nav-active' static/app.css` |
| S144 | `static/app.css` | Dark contest + projects frames (`!important`). | `rg -q 'html.dark #contest-content' static/app.css` |
| S145 | `static/app.css` | Dark export-report pool/excl rows + meta. | `rg -q 'html.dark .export-report tr.row.pool td' static/app.css` |
| S146 | `static/app.css` | Dark `#budget-card`, `#budget-rates-card`, `#pool-totals`. | `rg -q 'html.dark #pool-totals' static/app.css` |
| S147 | `tests/test_projects_chrome.py` | Selected tab classes `bg-indigo-600 text-white`. | `.venv/bin/python -m pytest tests/test_projects_chrome.py::test_selected_tab_uses_theme_button_classes -q` |

Vendor files: copy HTMX 2, Tailwind Play, SortableJS into `static/vendor/` as in
`static/vendor/README.md`. That copy is a parent task, not a Qwen slice.

---

## Phase 12 — Launch scripts

| ID | File | Work | Acceptance |
|---|---|---|---|
| S150 | `run.sh` | Find Python ≥3.11, venv, pip `-r requirements.txt`, exec uvicorn `--app-dir src --host 127.0.0.1 --port 8000` **no --reload**; `open` URL. | `rg -q 'no --reload' run.sh \|\| rg -q 'uvicorn stackrank.main:app' run.sh` |
| S151 | `install.sh` | `exec` the same `run.sh`. | `rg -q 'run.sh' install.sh` |
| S152 | `scripts/pack.sh` | Zip without `.venv`, db, `.git`, handoff, implementation-summary. | `rg -q 'stackrank-YYYYMMDD' scripts/pack.sh \|\| rg -q 'STAMP' scripts/pack.sh` |

---

## Phase 13 — Docs (one paragraph per slice)

Keep existing numbered docs in `docs/`. Rebuilds may copy from the prompt
rather than rewrite history. Optional slices:

| ID | File | Work | Acceptance |
|---|---|---|---|
| S160 | `docs/00-overview.md` | Stack + tree + non-goals. | `rg -q 'No React' docs/00-overview.md` |
| S161 | `docs/01-data-model.md` | Tables including cost_amount / cost_currency / theme. | `rg -q 'cost_amount' docs/01-data-model.md` |
| S162 | `README.md` | Friend path `./run.sh`, pack.sh, pytest via `.venv/bin/python`. | `rg -q './run.sh' README.md` |

---

## Suggested worker prompt (copy per slice)

```
ONE FILE ONLY: {path}
ONE JOB: {work from the table}
Do not edit other files. Do not commit.

ACCEPTANCE: {acceptance command must succeed}
```

---

## Done when

This rebuild is **done** on `main` (https://github.com/feilipu/stackrank).
`./run.sh` serves `http://127.0.0.1:8000`, all five tabs load, seed 12
projects appear on an empty DB, dark theme keeps pool/export/contest/projects
type readable, edit form shows entered RM/USD/SGD, export contractor has
Total and no Budget in the report body.

GitHub: MIT `LICENSE`, no live `data/*.db` in git, no `.venv`. Origin is
`feilipu/stackrank`. pytest: 105 collected, 104 pass (see `docs/handoff.md`
for the one known test drift).
