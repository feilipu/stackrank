# Pool tab: swimming-pool fill graphic

Status: Math shipped. Placement/visual superseded by `docs/08-pool-fill-layout-fix.md`.
Date: 2026-08-19
Author: parent (for qwen38-coder)

## Problem

The Pool tab shows Spent / Remaining as numbers only. There is no visual of how full the Success Pool is versus the budget.

## Goal

On the **Pool tab only**, next to the budget totals (`#pool-totals`), show a small swimming-pool graphic whose water height is the used fraction of the budget. The water has animated waves. A small duck floats on the surface.

## Non-goals

- Do not show this graphic on Projects, Optimize, Contest, or Export.
- No React, no new JS library, no canvas, no video, no live FX rates.
- No schema change. No change to rebalance / eject / pin behaviour.
- Do not commit.

## Fill math

Add `budget_fill(cost_sgd: float, budget_sgd: float) -> dict` in `src/stackrank/services.py` (next to `EPS`).

```
if budget_sgd <= EPS:
    raw = 0.0
else:
    raw = cost_sgd / budget_sgd
clamped = min(1.0, max(0.0, raw))
return {
    "fill_ratio_raw": raw,          # may be > 1 when over budget
    "fill_ratio": clamped,          # 0.0 .. 1.0
    "fill_pct": int(round(clamped * 100)),  # 0 .. 100
}
```

`pool_context` in `src/stackrank/main.py` merges those three keys onto `totals` (alongside `over_budget`).

Visual water height uses `fill_ratio`, but never less than `0.08` so the duck always has a puddle (caption and `data-fill` stay honest, including `0`).

## Placement (HTMX-safe)

The graphic lives **inside** `#pool-board`, in a flex row with `#pool-totals`:

```
[ In pool | Spent | Remaining | Outcome | Elo sum ]   [ pool graphic ]
```

On narrow screens the graphic stacks under the totals. Because it is inside `#pool-board`, add / remove / pin / reorder / budget-shrink OOB already refresh the water level. Do not put it only in `pool.html`’s header — that would go stale after HTMX.

New partial: `templates/_partials/pool_fill.html`.
Include it from `templates/_partials/pool_board.html` only.

## Markup (this exact shape)

```html
<figure id="pool-fill"
        class="pool-fill{% if totals.over_budget %} pool-fill--over{% endif %}"
        style="--pool-fill-ratio: {{ totals.fill_ratio }}; --pool-fill-pct: {{ totals.fill_pct }};"
        data-fill="{{ totals.fill_pct }}"
        aria-label="Success pool is {{ totals.fill_pct }} percent of budget">
  <svg class="pool-fill-svg" viewBox="0 0 200 120" role="img" aria-hidden="true">
    <!-- terracotta deck, cyan basin, clipped water + two wave paths + duck; see CSS file notes -->
  </svg>
  <figcaption class="pool-fill-caption">{{ totals.fill_pct }}% full</figcaption>
</figure>
```

`id="pool-fill"` and `data-fill` are the test hooks. Escape nothing extra; `fill_pct` is an int.

## Motion (CSS only)

All rules go in `static/app.css` (Tailwind Play cannot do keyframes well).

- `--pool-fill-ratio` drives a `translateY` on the water group so the surface rises from the basin floor. `transition: transform 0.7s ease` when the HTMX swap replaces the node.
- Two wave paths, extra-wide, `translateX` looping in opposite directions (`pool-wave-a` ~2.4s, `pool-wave-b` ~3.6s reverse).
- Duck: yellow body, orange beak, dark eye. `@keyframes` bob + a slow left-right drift on the surface (~4s ease-in-out infinite).
- `.pool-fill--over` tints the water rose/red.
- `@media (prefers-reduced-motion: reduce)`: no wave or duck animation; water still sits at the correct height.

Do not add JavaScript. `static/app.js` stays unchanged.

## Tests (one file: `tests/test_pool_fill.py`)

1. `test_budget_fill_half` — `budget_fill(50, 100)` → `fill_pct == 50`, `fill_ratio == 0.5`.
2. `test_budget_fill_over_clamps_pct` — `budget_fill(150, 100)` → `fill_pct == 100`, `fill_ratio_raw == 1.5`.
3. `test_budget_fill_zero_budget` — `budget_fill(10, 0)` → `fill_pct == 0`.
4. `test_pool_page_renders_fill_graphic` — `GET /pool` is 200, body contains `id="pool-fill"` and `data-fill="` plus `% full`.

## Docs

One short paragraph on the Pool tab in `docs/04-frontend.md`. One line in `docs/05-testing.md`.

## Slice order (parent orchestrates; one file each)

1. `src/stackrank/services.py` — add `budget_fill`.
2. `tests/test_pool_fill.py` — math tests (1–3).
3. `src/stackrank/main.py` — attach fill keys on `totals`.
4. `static/app.css` — basin, water, waves, duck, reduced-motion.
5. `templates/_partials/pool_fill.html` — SVG + caption.
6. `templates/_partials/pool_board.html` — flex row + include.
7. `tests/test_pool_fill.py` — add test 4.
8. `docs/04-frontend.md` — one paragraph.

Do not start ollama. Do not commit. Prefer pytest over curling the live uvicorn (it has no `--reload`).
