# Pool tab: fix fill graphic, hash-boxes, sticky 50/50 chrome

Status: Implemented (shipped on `main`, 2026-09-18). Historical spec.
Date: 2026-08-19
Author: parent (for qwen38-coder)
Supersedes placement/visual parts of `docs/07-pool-fill-animation.md`. Fill math (`budget_fill`) stays.

## Bugs (confirmed)

1. **Black / empty pool, no blue water, duck clipped.**
   `#pool-fill` is an SVG whose colours and water height are CSS `fill` + `transform: translateY(...)` on a `<g>`. SVG default fill is black. Safari / Tailwind Play often ignore those CSS fills, and the clipPath cuts the duck’s head. Playwright WebKit showed colour; the user’s browser does not.
2. **Two hash-boxes above Budget.**
   `templates/pool.html` contains ASCII `0x01` and `0x02` after `{% block content %}` and `{% endif %}`. Browsers draw them as ☒☒. Also a stray `</article>` with no opener.
3. **Wrong placement.** Graphic sits beside `#pool-totals`. User wants Budget + FX on the left half and the duck pool on the right half.
4. **Chrome does not stay put.** Tab nav, Budget, FX rates, and Auto-eject metric scroll away.

## Goals

- Visible terracotta deck, cyan basin, **blue water** whose height is `totals.fill_pct` (min visual puddle 14%). Waves animate. Duck sits **on** the surface, never clipped. Over-budget tints water rose.
- No ☒☒ / control characters on `/pool`.
- Site tab menu is sticky at the top of the viewport on every tab.
- On the Pool tab only, **one** sticky stack under the tabs: left = Budget + FX rates, right = duck pool, then Auto-eject metric under that row. 50%/50% when wide. On a narrow display, Budget+FX keep a readable min width (~18rem) and the duck stacks below (do not squash the form).
- HTMX add/remove/pin/reorder/budget still updates the water level.
- No React, no new JS library, no schema change, do not commit.

## Visual rewrite (do not keep CSS-styled SVG water)

Replace `templates/_partials/pool_fill.html` with **HTML + CSS boxes**. Duck may be a tiny inline SVG but every shape must have a `fill="#..."` attribute (not a CSS class). Water height is a CSS `height` on a `div`, not an SVG transform.

```html
<figure id="pool-fill"{% if pool_fill_oob %} hx-swap-oob="true"{% endif %}
        class="pool-fill{% if totals.over_budget %} pool-fill--over{% endif %}"
        style="--pool-fill-pct: {{ totals.fill_pct }};"
        data-fill="{{ totals.fill_pct }}"
        aria-label="Success pool is {{ totals.fill_pct }} percent of budget">
  <div class="pool-fill-deck">
    <div class="pool-fill-basin">
      <div class="pool-fill-water">
        <div class="pool-fill-wave pool-fill-wave-a"></div>
        <div class="pool-fill-wave pool-fill-wave-b"></div>
      </div>
    </div>
    <span class="pool-fill-duck" aria-hidden="true">
      <svg viewBox="0 0 36 20" width="36" height="20">
        <ellipse cx="14" cy="13" rx="11" ry="6.5" fill="#f5c518"/>
        <ellipse cx="11" cy="13.5" rx="5" ry="3.2" fill="#eab308"/>
        <circle cx="24" cy="8" r="5.5" fill="#f5c518"/>
        <polygon points="29,8 36,10.5 29,13" fill="#f97316"/>
        <circle cx="26" cy="6.5" r="1.1" fill="#1e293b"/>
      </svg>
    </span>
  </div>
  <figcaption class="pool-fill-caption">{{ totals.fill_pct }}% full</figcaption>
</figure>
```

CSS in `static/app.css` (replace the docs/07 SVG-fill / `translateY` rules):

- `.pool-fill-deck` — orange (`#fdba74`) padding, rounded.
- `.pool-fill-basin` — relative, overflow hidden, cyan (`#e0f2fe`) background, min-height ~8rem.
- `.pool-fill-water` — `position:absolute; left:0; right:0; bottom:0; height: max(14%, calc(var(--pool-fill-pct, 0) * 1%)); background:#38bdf8;` plus `transition: height 0.7s ease`.
- Waves: two extra-wide strips at the top of the water, `background` radial-gradient ellipses, `@keyframes` `translateX` as today.
- Duck: **sibling** of `.pool-fill-basin` (not inside overflow:hidden). `position:absolute; left:16%; bottom: max(14%, calc(var(--pool-fill-pct, 0) * 1%)); transform: translateY(45%);` so the body sits on the waterline. Keep the bob/drift keyframes.
- `.pool-fill--over .pool-fill-water` background `#fb7185`.
- `prefers-reduced-motion`: no wave/duck animation; height still correct.

## Sticky chrome

`templates/base.html` site `<header>`:

- class `site-top` + existing indigo styles.
- `position: sticky; top: 0; z-index: 40;` (in `app.css`).
- After the header-budget line, add `{% block sticky_sub %}{% endblock %}`.

Pool tab fills that block (`templates/pool.html`). **Do not** put Budget/fill/metric only inside `#pool-board` — they would unstick when the board is long, and a second `top:0` sticky would cover the tabs.

```
{% block sticky_sub %}
<div id="pool-sticky" class="mx-auto max-w-6xl px-4 pb-3">
  <div class="pool-split">
    <div class="pool-split-budget">{% include "_partials/budget_card.html" %}</div>
    {% include "_partials/pool_fill.html" %}
  </div>
  {% include "_partials/pool_metric.html" %}
</div>
{% endblock %}
```

`pool.html` content block: applied flash (if any) + `#pool-board-region` include + footer line. **Delete** the `0x01` / `0x02` bytes and the stray `</article>`. **Delete** the old Budget `<header>` from the content block (it now lives in `sticky_sub`).

`.pool-split` in `app.css`:

```
display: grid;
grid-template-columns: minmax(18rem, 1fr) minmax(12rem, 1fr);
gap: 0.75rem;
align-items: stretch;
```

`@media (max-width: 40rem)` → one column (Budget+FX first, duck below). Never shrink the budget form below 18rem.

Extract the Auto-eject `<form>` from `pool_board.html` into `templates/_partials/pool_metric.html` (same fields, same POST `/settings/pool-metric`, still `hx-target="#pool-board"`). `#pool-board` then starts at `#pool-totals` + columns. Remove `.pool-fill-row`.

## HTMX: water level after mutations

`#pool-fill` now lives outside `#pool-board`. Every HTML response that used to return only `pool_board.html` must also append the fill partial with `pool_fill_oob=True` so HTMX swaps `#pool-fill`.

Add `pool_board_html(ctx, *, oob=False) -> str` in `src/stackrank/main.py` and use it from:

- `POST /settings/budget` (oob=True for the board fragment)
- `POST /pool/add`, `/remove`, `/reorder`, `/pin`
- `POST /settings/pool-metric`

`pool_context` must also expose the budget-card keys (today `/pool` has no `budget_amount`, so the amount input is empty):

```
budget_currency, budget_amount (via sgd_display + round, same as project_context),
usd_per_sgd, myr_per_sgd
```

`GET /projects` must not render `#pool-fill` (no `sticky_sub` there).

## Tests (`tests/test_pool_fill.py` — add, do not delete math tests)

5. `test_pool_page_has_no_control_char_glyphs` — `GET /pool` body has no `\x01` or `\x02`.
6. `test_pool_page_uses_html_water_not_svg_basin` — `GET /pool` contains `class="pool-fill-water"` and `class="pool-fill-duck"`.
7. `test_pool_page_budget_and_fill_are_split` — `GET /pool` contains `id="pool-sticky"`, `id="budget-card"`, `id="pool-fill"`, and `name="metric"`.
8. `test_pool_add_returns_fill_oob` — add a seed project; response contains `id="pool-fill"` and `hx-swap-oob`.
9. `test_projects_page_has_no_pool_fill` — `GET /projects` has no `id="pool-fill"`.

Existing `test_pool_page_renders_fill_graphic` stays valid (`id="pool-fill"`, `data-fill`, `% full`).

## Docs

Update the Pool tab bullets in `docs/04-frontend.md` (sticky split, HTML water). One extra line in `docs/05-testing.md`.

## Slice order (parent orchestrates; one file each)

1. `src/stackrank/main.py` — add `budget_amount` / `budget_currency` / rates to `pool_context` only.
2. `templates/_partials/pool_fill.html` — rewrite to the HTML above.
3. `static/app.css` — replace SVG-fill rules with deck/basin/water/wave/duck + `.site-top` + `.pool-split`.
4. `templates/_partials/pool_metric.html` — new file, form copied from pool_board.
5. `templates/base.html` — `site-top` class + `{% block sticky_sub %}`.
6. `templates/pool.html` — strip control chars; `sticky_sub` with budget + fill + metric; content is board only.
7. `templates/_partials/pool_board.html` — drop metric form and `.pool-fill-row` / fill include.
8. `src/stackrank/main.py` — `pool_board_html` + switch the six call sites.
9. `tests/test_pool_fill.py` — tests 5–9.
10. `docs/04-frontend.md` — one updated paragraph.

Do not start ollama. Do not commit. Prefer pytest. Live uvicorn has no `--reload`.
