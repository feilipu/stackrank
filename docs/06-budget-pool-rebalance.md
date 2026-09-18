# Budget shrink must rebalance the Success Pool

Status: Implemented (shipped on `main`, 2026-09-18). Historical spec.
Date: 2026-08-19
Author: parent (for qwen38-coder)

## Problem

Reducing the budget below the current Success Pool cost does nothing. `update_budget` only writes `settings.budget_sgd`. Ejection exists only inside `add_to_pool`. The pool can silently sit over budget. `pool_context` already computes `totals.over_budget` but the template never shows it, and Remaining is clamped to zero.

The user requires one of: auto-eject the lowest-metric items, or a visible warning/error. This spec does both: eject when possible, warn when pins make ejection impossible.

## Goals

1. After any successful budget write, the pool is rebalanced against the new budget.
2. Unpinned items leave the pool (lowest `pool_eject_metric` first) until cost ≤ budget or nothing ejectable remains.
3. If pinned (or pin-protected) items still exceed the budget, keep the new budget and show a clear over-budget error.
4. The Pool board and totals refresh when the budget form is submitted on `/pool`.
5. Existing tests that assumed `update_budget` does not touch the pool are updated.

## Non-goals

- No schema / migration.
- No change to optimize knapsack, Elo, currency conversion, or export grouping.
- Do not refuse a lower budget (the number the user typed always persists if it is > 0).
- Do not rebuild the app. Do not add React/auth/live FX.

## Current code (do not regress)

| Piece | Where | Today |
|---|---|---|
| Budget write | `services.update_budget` | `BEGIN IMMEDIATE`; update settings; `COMMIT`. No pool I/O. |
| Ejection | `services.add_to_pool` | While `sum(cost) > budget + EPS`, eject unpinned member ≠ incoming with lowest `(value, -position, -id)`. If none, `ServiceError` 409 and no write. |
| Budget HTTP | `POST /settings/budget` | Returns `_partials/budget_card.html` + `#header-budget` OOB. Does not refresh `#pool-board` or `#flash`. |
| Pool totals | `pool_context` in `main.py` | `over_budget = remaining < -1e-9` exists; remaining display uses `max(remaining, 0)`. Unused in template. |
| Pins | `pool_items.pinned` | Never auto-ejected. |
| Metric | `settings.pool_eject_metric` | `outcome` / `elo` / `blend` via `metric_value`. |
| Flash | `#flash` in `base.html`; `_partials/errors.html` | 409/422 retarget here. CSS: `.flash-ok`, `.flash-error`. |
| HTMX budget form | `templates/_partials/budget_card.html` | `hx-post="/settings/budget" hx-target="#budget-card" hx-swap="outerHTML"`. |

`docs/02-algorithms.md` says missing deps block add; live `add_to_pool` auto-pulls deps. Implement against **live code**.

Existing test `test_add_expensive_project_ejects_lowest_unpinned_by_pool_metric` adds two 100-cost items, then `update_budget(150)`, then adds a 1-cost item. After this change the budget drop itself ejects one item. Rewrite that test.

## Behaviour

```
user POSTs a new budget
  persist budget (unchanged validation: amount > 0)
  rebalance pool against new budget
  respond with budget card + header OOB
           + pool-board OOB (HTMX ignores if #pool-board absent)
           + flash OOB when ejected and/or still over
```

### Rebalance algorithm

Extract `rebalance_pool(conn, budget: float, *, protect_ids: set[int] | None = None) -> list[int]` in `services.py`.

Members are current `pool_rows` (id, cost, pinned, position, value from `pool_eject_metric`).

`protect_ids`: items that must not be chosen as the *primary* victim while any other ejectable item exists. `add_to_pool` passes `{incoming_id}` so behaviour matches today.

Loop while `sum(cost) > budget + EPS` (`EPS = 1e-6`):

1. **Primary candidates** = members that are:
   - not pinned
   - not in `protect_ids` unless no other candidate exists (then still do not eject pinned)
   - **not required by a pinned member still in the pool** (direct or transitive dependent is pinned). Same idea as `remove_from_pool`: you cannot pull out B while pinned A depends on B.
2. If no primary candidates: **stop**. Leave remaining members. Caller treats this as over-budget (do not raise from `update_budget`).
3. Primary victim = `min(candidates, key=lambda m: (m["value"], -m["position"], -m["id"]))` — same key as `add_to_pool`.
4. Also remove every **unpinned** pooled transitive dependent of the victim (keep ancestor-closed). Pinned dependents cannot exist here because of step 1.
5. Record ejected ids (victim + those dependents).

Then persist: `DELETE FROM pool_items` and re-insert remaining members in current relative order, positions 0..n-1, pins unchanged.

`update_budget` must run settings write + rebalance in **one** `BEGIN IMMEDIATE` transaction.

Return value of `update_budget`: a small result the route can flash, e.g. a dict or named tuple:

```python
{"ejected_ids": [...], "ejected_names": [...], "over_budget": bool, "pool_cost_sgd": float, "budget_sgd": float}
```

`over_budget` is true iff remaining pool cost > new budget + EPS after rebalance.

### `add_to_pool` must call the same helper

After building the tentative member list (including auto-pulled deps as today):

- Call the same loop / helper with `protect_ids={project_id}`.
- If still over after the loop: raise `ServiceError("Does not fit even after ejecting unpinned projects.", 409)` and do not write — same as today.
- Otherwise persist as today.

Do not change add/remove/reorder/pin HTTP contracts except that add now stays ancestor-closed when it ejects a dependency (dependents leave with it).

### UI

**`POST /settings/budget`** (`main.py`):

1. Call `update_budget`.
2. Build `project_context` **and** `pool_context` (pool_context already exists).
3. Primary swap stays `#budget-card` (form target unchanged).
4. Append OOB `#pool-board` by rendering `_partials/pool_board.html` with pool_context (include `hx-swap-oob="true"` on the `<section id="pool-board">` when rendered as an extra fragment, **or** a dedicated wrapper). When this fragment is the main `/pool/*` response, do **not** add oob (those routes still swap `#pool-board` as the target).
5. Append OOB `#flash`:
   - Ejected only: `.flash-ok` (or a new `.flash-warn` if you add one — ok or warn, not silent). Message: `Removed from the success pool to fit the new budget: Name1, Name2.`
   - Still over-budget: `.flash-error`. Message: `Budget is below the cost of pinned items in the success pool. Unpin or remove them, or raise the budget.`
   - Both: one `#flash` block, error style, both sentences.
   - Neither: OOB empty `<div id="flash"></div>` so a previous message clears.

**Pool totals** (`pool_board.html`):

- If `totals.over_budget`: Remaining label becomes **Over by**, value is `abs(remaining)` in three currencies, text `text-red-700`. Show a one-line banner above the two columns: `Over budget — pinned items exceed the allowance.`
- Stop clamping remaining to 0 when computing the over-by amount. Keep `totals.remaining` as the non-negative remainder for the in-budget case.

**Projects page**: budget form still works. OOB `#pool-board` is a no-op (element absent). Flash still appears in the header.

### Flash partial

Add `_partials/flash.html` (or extend `errors.html`) that renders `#flash` with a `kind` of `ok` / `error` / empty. Reuse `.flash-ok` / `.flash-error` in `static/app.css`. Escape names (`e` filter), do not mark user-facing names `| safe`.

## Tests (required)

`tests/test_services.py`

1. **Budget shrink ejects lowest unpinned by pool metric.** Two unpinned items cost 100 each, outcomes 10 and 90, metric=`outcome`, budget 250. Set budget to 150. Pool contains only the outcome-90 item.
2. **Pinned survives a shrink that it still fits.** Cost 3 pinned, budget 5 after drop from 1000. Pool still has it, not over-budget.
3. **Pinned set exceeds new budget.** One pinned cost 100, budget set to 40. Budget persists at 40, item stays in pool, result `over_budget` is true.
4. **Ancestor-closed eject.** B in pool, A depends on B, both unpinned. B is the lower metric. Shrink so only one fits. Both leave (cannot keep A without B).
5. **Cannot eject a dependency of a pinned item.** B unpinned, A pinned depends on B. Shrink below A+B. Neither is ejected; `over_budget` true.
6. Rewrite `test_add_expensive_project_ejects_lowest_unpinned_by_pool_metric` so it no longer relies on a silent over-budget window between `update_budget` and `add_to_pool`.

`tests/test_api.py`

7. `POST /settings/budget` that forces an eject: 200, still includes `#header-budget` OOB, response contains `#pool-board` OOB and a flash naming the ejected project.
8. `POST /settings/budget` that leaves pinned over-budget: 200 (not 409), flash contains “pinned”, pool board OOB still lists the pinned name.

## Docs to touch (short)

- `docs/02-algorithms.md` — add a “Budget change” paragraph under Pool ejection.
- `docs/04-frontend.md` — over-budget *can* appear after a budget shrink when pins block eject; flash + Over-by totals.
- `docs/05-testing.md` — list the new cases.

Do not commit.

Follow-on (Pool tab graphic, not part of rebalance): `docs/07-pool-fill-animation.md`.

## Implementation notes for qwen38-coder

- Read the live functions before editing. Match transaction / `ServiceError` style.
- One `rebalance_pool` used by `update_budget` and `add_to_pool`. Do not copy-paste two loops.
- Do not start systemd/launchd. Do not restart `ollama`. The app server is a one-off uvicorn; after code change, tests do not need it. If you curl `:8000`, know it will not pick up edits unless reloaded — prefer pytest.
- Run `pytest tests/test_services.py tests/test_api.py -q` from the repo with `.venv`.
- Keep comments factual and short. No placeholders. No drive-by refactors.
