# Handoff — Project Stack Ranker

**Date:** 2026-08-17  
**Repo:** `/Users/phillip/Projects/stackrank` (`main`)  
**Status:** Spec is implemented. pytest **33 passed**. Suggested next-work items **1–6 are done**. Repo is git `main` @ `9e762c5` plus a follow-up docs commit. Do not rebuild the app.

This document is for the next session or agent. Read this first, then the design docs only if you need algorithm or route detail.

---

## Fixed (P0) — returning to Projects was a server error

**Was.** After Optimize → Apply (11 `pool_items`), Projects and `GET /` showed HTTP **503** and `#flash`: “Something went wrong. See the server logs.” `/optimize`, `/pool`, `/contest` stayed 200. Empty pool hid the bug (that is why the first WebKit pass looked fine).

**Root cause.** `services.pool_rows()` is `SELECT p.*, i.position, i.pinned` — keys are `id` (from `projects`), not `project_id`. `project_context` read `r["project_id"]`. `sqlite3.Row` raised `IndexError: No item with that key`. `handle_unexpected` mapped that to 503.

**Original log** (`data/uvicorn.log`):

```
INFO:     127.0.0.1:53685 - "POST /optimize/apply HTTP/1.1" 200 OK
INFO:     127.0.0.1:53685 - "GET /pool HTTP/1.1" 200 OK
ERROR:stackrank.main:unexpected error handled by request
Traceback (most recent call last):
  File ".../src/stackrank/main.py", line 414, in projects_page
    ctx = project_context(conn, page="projects")
  File ".../src/stackrank/main.py", line 205, in project_context
    pool_ids = {int(r["project_id"]) for r in services.pool_rows(conn)}
                    ~^^^^^^^^^^^^^^
IndexError: No item with that key
INFO:     127.0.0.1:53686 - "GET /projects HTTP/1.1" 503 Service Unavailable
```

**Fix applied** (Qwen38 Coder 27B worker `01a0100c-900a-71e1-809a-89765af96e2c`, then parent verified):

```python
# src/stackrank/main.py — project_context
pool_ids = {int(r["id"]) for r in services.pool_rows(conn)}
```

Also wired `request.state.is_hx` from the `HX-Request` header. `POST /projects` now returns the list fragment under HTMX (303 for a normal form post). Delete already branched on `is_hx`.

**Regression tests** in `tests/test_api.py`:

- `test_projects_page_ok_when_pool_nonempty` — add seed to pool, `GET /projects` is 200 and shows “In pool”
- `test_htmx_delete_returns_list_fragment` — `HX-Request: true` delete is 200 fragment, not 303
- `test_pool_add_returns_both_columns` — now asserts 200 + `#available-list` + `#pool-list`

**Re-verified 2026-08-17** (live DB still has 11 pool rows including “Air Conditioning”):

```
/            307 → /projects
/projects    200  title “Projects -- Stack Ranker”, 11× “In pool”, no flash error
/optimize    200
/pool        200
/contest     200
```

Playwright WebKit: `/pool` → click Projects → `/projects` with `#project-list` and 11 badges; Optimize then back to Projects still 200.

---

## What this is

Single-user local web app for ranking sub-projects under a budget. Three modes:

1. **Optimize** — exact 0/1 knapsack over ancestor-closed sets (`outcome` / `elo` / `blend`).
2. **Pool** — drag or click into an In-Budget Success Pool. Lowest-metric unpinned items eject; pinned items stay. Missing dependencies block add.
3. **Contest** — pairwise Elo (K = 32) with a live leaderboard.

Money is stored in **SGD**. USD and MYR are display/input only, using configured “foreign per 1 SGD” rates (defaults `0.74` / `3.45`). Seed: 12 projects, budget **S$250,000**.

Original prompt: `stackrank_prompt.txt`. Design specs: `docs/00-overview.md` … `docs/05-testing.md`.

---

## How to run

```bash
cd /Users/phillip/Projects/stackrank
source .venv/bin/activate
uvicorn stackrank.main:app --reload --app-dir src --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 (redirects to `/projects`).

```bash
source .venv/bin/activate
pytest
```

Tests use a temp SQLite file. They never touch `data/stackrank.db`.

As of this handoff:

| Process | PID (may change) | Port |
|---|---|---|
| uvicorn (reload parent) | 2909 | `127.0.0.1:8000` |
| ollama serve | 2568 | `127.0.0.1:11434` |

Uvicorn log: `data/uvicorn.log`. Dev DB: `data/stackrank.db`.

Leave the venv with `deactivate`.

---

## Layout

```
src/stackrank/
  main.py          FastAPI routes, Jinja context, LAST_OPTIMIZE (in-memory)
  db.py            SQLite connect + schema + seed hook
  services.py      CRUD, pool, contest, settings, optimize apply
  optimizer.py     ancestor-closed exact search (cycle → OptimizerError)
  elo.py           K=32 update + pair picker
  currency.py      SGD/USD/MYR + blend scoring
  seed.py          12 example projects
templates/         pages + _partials/ fragments
static/            app.css, app.js (SortableJS ↔ HTMX)
tests/             conftest + optimizer/elo/currency/services/api
docs/              design + this file
```

There is **no** `models.py`. Rows are `sqlite3.Row` / dicts. Design listed it; it was never needed.

Stack: FastAPI + Jinja2 + HTMX 2 + Tailwind Play CDN + SortableJS CDN. No Node build. No auth.

---

## Behaviour that is in

| Area | Notes |
|---|---|
| Project CRUD | Create (303 to `/projects`), edit fragment, update (list fragment), delete. Unique name. Cost/outcome > 0. No self-deps or cycles. |
| Budget / rates | `POST /settings/budget`, `POST /settings/rates`. Amount may be typed in SGD/USD/MYR. |
| Optimize | Metric radios + native `method=post action=/optimize/run` (works if HTMX fails). Apply writes selected ids into the pool, positions by descending value, unpinned. Result lives in `LAST_OPTIMIZE` only. |
| Pool | Add / remove / reorder / pin. Auto-eject by pool metric. Block missing deps; block remove if dependents remain. |
| Contest | Start / A-or-B / skip / stop / reset (`confirm=yes`). Pairing prefers unseen closest-Elo pairs. |
| Seed | Only when `projects` is empty. Names include `Identity & SSO` (HTML shows `Identity &amp; SSO`). |

Blend: `0.6 * outcome + 0.4 * (elo / 15)`.

---

## What the last session already verified

- `pytest` from repo root: **30 passed** (includes `/projects` with a non-empty pool, HTMX delete, completed pool-add markup asserts).
- `/`, `/projects`, `/optimize`, `/pool`, `/contest` all 200 with 11 pool rows in `data/stackrank.db`.
- WebKit: Pool → Projects and Optimize → Projects both land on the list with “In pool” badges and no flash error.
- System Safari WebDriver is still off (`safaridriver --enable` needs an admin password). `open -a Safari http://127.0.0.1:8000` works for a manual look.

---

## Known gaps / polish (do not treat as “unbuilt”)

1. ~~**`request.state.is_hx` is never set.**~~ Fixed: middleware sets it; HTMX create/delete return the list fragment.
2. ~~**Writes are autocommit.**~~ Remaining service writes + `seed_if_empty` now use `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`. `_end_contest_sql` and `_advance_pair` stay bare so they are not nested. Parent fixed a Gemma typo in `seed.py` (`ROLLback` / missing `ServiceError`).
3. **n > 24 ILP fallback** not implemented. Recursion is exact for the seed (n = 12). Fine unless someone adds many projects.
4. ~~**Pool remaining** SGD only.~~ Remaining uses `totals.remaining.text` (SGD · USD · MYR). Live pool: `S$9,463  ·  US$7,003  ·  RM32,649`.
5. **Optimize apply** still returns a one-line HTML note, not a redirect to `/pool`. (Not in suggested 1–6.)
6. ~~**Header budget chip** static.~~ `#header-budget` + `hx-swap-oob` on `budget_card.html` after budget/rates POSTs.
7. **Tailwind** is loaded with `defer`. Possible unstyled flash.
8. ~~**`playwright` missing from requirements.**~~ `playwright==1.62.0` plus `scripts/smoke_tabs.py` (WebKit, four tabs). Not in pytest.
9. ~~**No git.**~~ `git init -b main`; initial commit `9e762c5`. `data/*.db` is ignored.
10. Leftover: `data/ollama-serve.log`. Safe to delete (ignored by `data/*.log`).

Template history (already fixed — do not reintroduce):

- Jinja `str()` / `'%,.0f' %` crashes.
- Fake HTMX `integrity=` on the CDN script blocked HTMX (Optimize button did nothing until it was removed).
- Seed assertion must look for `Identity` + `SSO`, not the raw `&`.

---

## Qwen / Ollama — do not repeat

The original prompt asked to use **Qwen38 Coder 27B via Ollama** as a worker.

What happened:

- Grok mapped `qwen38-coder` → local Ollama `qwen38-coder`.
- Earlier workers hung (`waiting_for_model`), then looped rereading files for hours (one run ~6.4 h). Context mismatch: Grok runner ~200k vs Ollama ~32k.
- `ollama serve` sat in `Stopping…` at ~104% CPU. Kill the runner **and** `ollama serve`, then start a fresh serve.
- First useful output: the **pytest suite**. Parent wrote/repaired the UI, README, and templates.
- Bug-fix worker `01a0100c-900a-71e1-809a-89765af96e2c` (tight prompt): applied the P0 one-liner, HTMX middleware, create-project fragment, and two new API tests in ~30 min. It then kept tool-calling after pytest was already green (6 failed edits). Parent killed it, finished the truncated `test_pool_add_returns_both_columns` asserts, and verified in curl + WebKit.

`~/.grok/config.toml` maps:

- `qwen38-coder` → `qwen38-coder`
- `qwen3-coder` → `qwen3-coder:30b`
- `gemma4-coder` → `gemma4-coder:26b` (created with `ollama cp gemma-coder:26b gemma4-coder:26b`)

**Recommendation (after items 1–6):** prefer **Qwen38 Coder 27B** for one-item, few-file prompts with a hard stop. It shipped items 3–6 cleanly. Use **Gemma4 Coder 26B** as the fallback when Qwen makes no file edits in ~15 minutes (that is how item 2 landed). Never run both at once. Never hand either the whole repo.

If Ollama is sick again:

```bash
pkill -f 'ollama serve' || true
# kill any leftover llama runner
ollama serve
```

Do not treat a hung local worker as unfinished product work.

---

## Suggested next work (only if asked)

Priority order if the user wants more:

1. ~~**Fix the Projects 503**~~ and ~~wire `HX-Request`~~ — done.
2. ~~Wrap remaining writes in `BEGIN IMMEDIATE`.~~ Done (Gemma after Qwen stalled).
3. ~~Refresh the header budget chip.~~ Done (Qwen, HTMX OOB).
4. ~~Remaining budget as a three-currency triple.~~ Done (Qwen).
5. ~~Playwright smoke + four-tab script.~~ Done (Qwen): `scripts/smoke_tabs.py`.
6. ~~`git init`.~~ Done (Qwen): `main` @ `9e762c5`.

If more polish is wanted later: n>24 ILP fallback, optimize-apply redirect to `/pool`, Tailwind FOUC.

Do **not** add React, auth, a live FX API, or a second frontend.

---

## Quick route map

| Method | Path | Result |
|---|---|---|
| GET | `/` | 307 → `/projects` |
| GET/POST | `/projects`, `/projects/{id}`, `/projects/{id}/edit`, `/projects/{id}/delete` | CRUD |
| POST | `/settings/budget`, `/settings/rates`, `/settings/pool-metric` | settings fragments |
| GET/POST | `/optimize`, `/optimize/run`, `/optimize/apply` | knapsack |
| GET/POST | `/pool`, `/pool/add/{id}`, `/pool/remove/{id}`, `/pool/reorder`, `/pool/pin/{id}` | pool board |
| GET/POST | `/contest`, `/contest/start`, `/contest/choose`, `/contest/skip`, `/contest/stop`, `/contest/reset` | contest board |

Validation: `ServiceError` → `_partials/errors.html` + `HX-Retarget: #flash` (422/409). Unexpected exceptions → 503 + same fragment.

---

## Commands the next agent should run first

```bash
source .venv/bin/activate
pytest -q
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/projects
```

If port 8000 is down, start uvicorn as above. If the user wants Safari: `open -a Safari http://127.0.0.1:8000`.
