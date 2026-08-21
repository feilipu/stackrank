# Projects list, notes, efficiency, deps, contest undo, chrome

Status: Ready to implement (tiny slices, 20 min watch)
Date: 2026-08-19
Author: parent (for qwen38-coder)

No React, auth, live FX, or a second frontend. Do not commit. Do not start ollama.

## Schema (`src/stackrank/db.py` `apply_schema`)

ALTER if missing (same style as `project_name` / `last_optimize_json`):

- `projects.notes TEXT NOT NULL DEFAULT ''`
- `settings.last_cost_currency TEXT NOT NULL DEFAULT 'SGD'`
- `settings.theme TEXT NOT NULL DEFAULT 'system'`  -- `system` | `light` | `dark`

Default INSERT for new DBs must include the new settings columns (or rely on ALTER after CREATE). Existing DBs: ALTER only.

## 3 — Search / sort / filter (Projects tab)

`GET /projects` query params (all optional):

| Param | Values | Default |
|---|---|---|
| `q` | substring, case-insensitive, matches name, description, notes | `""` |
| `pool` | `all` / `in` / `out` | `all` |
| `sort` | `name` / `cost` / `outcome` / `elo` / `efficiency` | `name` |
| `dir` | `asc` / `desc` | `asc` (`desc` default only for `elo` and `efficiency`) |

Filter in `project_context`. Invalid sort/pool ignored → defaults. Form `GET /projects` above the list (`hx-get` targeting `#project-list` is OK if the add-form stays). Empty filter result: empty-state, not an error.

## 4 — Notes

`create_project` / `update_project` take `notes: str` (strip, max 500 chars, empty OK). Add textarea on add + edit forms. Show on project cards, pool cards, contest cards, export (markdown + HTML) when non-empty. Escape with Jinja `e` / existing export escape.

## Last cost currency

On successful `create_project`, persist `settings.last_cost_currency` from that form’s `cost_currency` (must be SGD/USD/MYR). Add-form `<select name="cost_currency">` defaults to `last_cost_currency` (fallback SGD). Edit form may keep current behaviour.

## 5 — Efficiency

On each project row: `outcome_per_sgd = outcome / cost_sgd`, `elo_per_sgd = elo_rating / cost_sgd` (cost_sgd > 0 always). Display two short figures on project cards (and pool cards): e.g. `outcome/S$ 0.012` · `Elo/S$ 0.13`. `efficiency` sort uses `outcome_per_sgd`.

## 6 — Dependency sketch

Partial `_partials/dep_sketch.html`: inline SVG, no JS. Current project on the right, each direct dependency as a box on the left, one line each. If no deps, omit the SVG. Include from project cards (and pool cards if space). Max ~6 dep boxes; if more, show first 5 + “+N”.

## 7 — Contest undo + recap

`contest_matches` already stores before/after Elo and nullable `winner_id`.

`contest_undo(conn)`:

1. Last row by `id DESC`. If none: `ServiceError("Nothing to undo.")`.
2. One `BEGIN IMMEDIATE`.
3. If `winner_id` is not NULL: restore both projects’ `elo_rating` from `*_elo_before`; decrement `matches_played`; reverse the win/loss increment; `contest_decided = max(0, contest_decided-1)`.
4. Always: `contest_shown = max(0, contest_shown-1)`; `DELETE` that match; set `contest_left_id`/`contest_right_id` to that pair; `contest_active = 1`.
5. COMMIT.

`POST /contest/undo` → `#contest-board` fragment (same as choose). Hide Undo when no matches.

Recap on the board: last match (after current action) — names, winner or “Skipped”, Elo deltas when decided.

`reset_elo` still deletes all matches (nothing to undo after).

## 8 — Dark mode, favicon, empty art

- `settings.theme`: `system` (default) / `light` / `dark`. `POST /settings/theme` (`theme=`).
- `base.html`: `<html data-theme="{{ theme }}">`. Tiny **blocking** script in `<head>` (not defer): if theme is `dark`, or `system` and `prefers-color-scheme: dark`, add class `dark` on `<html>`. Listen to `change` on the media query when theme is system.
- Tailwind Play config: `darkMode: 'class'`.
- `static/app.css`: `html.dark` overrides for page, header, cards, pool colours, flash (do not require rewriting every template).
- Header control: three options System / Light / Dark; current one marked.
- Favicon: `static/favicon.svg` (simple stacked-bars mark, indigo). `<link rel="icon">` in `base.html`.
- Empty-state SVG (inline, one style): Projects list empty; Pool Available empty; Contest idle. Keep existing sentences; add the drawing above the text.

## 9 — Leftover bugs

- Tailwind FOUC: load `app.css` first (already); **remove `defer`** from `tailwindcss.js` so utilities exist before first paint.
- Rates form: `hx-target="#budget-card"` (response is the whole card). Today it targets `#budget-rates-card` and can nest/break.
- `templates/projects.html` `{% block title %}`: use em dash and `project_name` like other pages (`{{ project_name }} — Projects — Stack Ranker`).
- Do not drive-by refactor `add_to_pool`.

## Tests (`tests/test_projects_chrome.py` new file, add tests one at a time)

1. Notes persist on create; appear in `GET /projects`.
2. `q=` hides non-matching names.
3. `pool=in` only lists in-pool names.
4. Create with USD then GET add-form has `USD` selected.
5. `GET /projects` includes `outcome/S$` (or `outcome/S`).
6. Project with a dep includes `<svg` in that card.
7. Contest choose then undo restores Elo and match count.
8. `GET /projects` includes `favicon.svg` and `data-theme=`.
9. Rates POST body still has `id="budget-card"` as the outer section (not nested).

## Slice order (one file, one check)

1. `src/stackrank/db.py` — ALTER three columns; default INSERT still works.
2. `src/stackrank/services.py` — `create_project`/`update_project` `notes`; write `last_cost_currency` on create.
3. `tests/test_projects_chrome.py` — test 1 (notes).
4. `src/stackrank/main.py` — `project_payload` notes; `project_context` notes + last_cost_currency + filter/sort + efficiency fields.
5. `templates/_partials/project_list.html` — filter form, notes field, last currency selected, efficiency, empty art hook.
6. Tests 2–4 (append one test per slice if the file would get big; otherwise 2 then 3 then 4).
7. `templates/_partials/project_edit.html` — notes textarea.
8. `templates/_partials/dep_sketch.html` — new SVG partial.
9. Include sketch from project_list card.
10. Pool board cards: notes + efficiency (one file).
11. Contest undo in `services.py`.
12. `POST /contest/undo` in `main.py`.
13. `contest_board.html` — Undo + recap + empty art.
14. Test 7.
15. Export HTML/MD notes line (one file: `services.py` export helpers — wait, services is large; add notes into the existing card detail lists only).
16. `static/favicon.svg`.
17. `base.html` — icon, theme script, darkMode config, theme control include.
18. `static/app.css` — `html.dark` + empty-state + FOUC-safe page bg.
19. `POST /settings/theme` in `main.py`.
20. `_partials/theme_switch.html`.
21. `budget_card.html` rates hx-target.
22. `projects.html` title.
23. Empty SVGs in pool + contest empty branches.
24. Docs paragraph `docs/04-frontend.md`.

Prefer pytest. Live uvicorn has no `--reload`.
