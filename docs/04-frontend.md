# Frontend

**Status (2026-09-18):** this is the live UI. Tailwind, HTMX, and SortableJS are vendored (no CDN at runtime).

Server-rendered. No build step. No Node required.

## Assets

In `base.html` `<head>`:

- Tailwind CSS Play 3.4.17 from `static/vendor/tailwindcss.js` with a small `tailwind.config` for brand colors.
- HTMX 2.0.4 from `static/vendor/htmx.min.js`.
- SortableJS 1.15.2 from `static/vendor/Sortable.min.js`.

No CDN at runtime. Refresh URLs are in `static/vendor/README.md`.

`static/app.css` only for things the Tailwind Play build cannot express (card min-heights, contest progress bar).

`static/app.js`:

- Init Sortable on `#available-list` and `#pool-list`.
- On add (Available → Pool): `POST /pool/add/{id}` via `htmx.ajax`.
- On remove (Pool → Available): `POST /pool/remove/{id}`.
- On pool reorder: `POST /pool/reorder` with the new id order.
- Disable Sortable while an HTMX request is in flight.

## Visual design

Clean, modern, readable. Light page (`slate-50` background, indigo-tinted header, `slate-900` text, indigo accent). Large tap targets. Tab nav with the active route underlined and `nav-active` (lavender chip).

**In vs out of pool** uses colour *and* text:

| Class | Meaning | Colour |
|---|---|---|
| `sub-out` / `col-available` | not in the pool | amber (`#fff7ed` / `#fdba74`) |
| `sub-in` / `col-pooled` | in the pool | green (`#ecfdf5` / `#6ee7b7`) |
| `sub-pinned` | pinned in the pool | amber inset rail |
| `nav-active` | current tab | indigo-100; dark: indigo-600 fill + white type (same as theme buttons) |

The Projects list still shows an “In pool” badge. Pool columns still say Available Pool / In-Budget Success Pool.

Defined in `static/app.css` so they work even if the Tailwind Play script is slow.

Header: editable overall project name (`#header-title`, `POST /settings/name`) plus a small “Stack Ranker” product mark. Nav tabs (Projects, Optimize, Pool, Contest, Export) live in the sticky `site-top` bar on every page, including `/export.html`. Export is the same chrome plus the coloured report; it links to `/export.md`.

Every money amount uses a helper macro:

```
S$12,000  ·  US$8,880  ·  RM41,400
```

## Projects tab

- Left or top: budget card (amount + currency select + rates editor).
- Search / pool filter / sort (`q`, `pool`, `sort`, `dir`) above the list.
- Table/cards of projects: name, description, notes, cost (3 fx), outcome, Elo, matches W-L, efficiency (`outcome/S$`, `Elo/S$`), dependency sketch, dependency chips.
- “Add project” form: name, description, notes, cost + currency (defaults to `last_cost_currency`), outcome, and a two-column pair of `<select multiple>` lists for **Depends on** and **Excludes** (⌘/Ctrl-click). Lists scroll inside the widget so a long catalogue does not stretch the page.
- Cards list “Excludes: …” next to “Depends on: …”.
- Edit in place (HTMX swap a form into the row). The edit form shows the **entered** amount and currency, not a reverse conversion from SGD.
- Delete with `hx-confirm`.

## Optimize tab

- Metric radio: Outcome / Elo / Blend.
- Primary button “Optimize”.
- Results: selected table, excluded table, totals (cost 3 fx, remaining, outcome, value).
- Button “Apply selection to pool”.

## Pool tab

Two equal columns on desktop, stacked on mobile (`md:grid-cols-2`).

- Available Pool: projects not in the success pool.
- In-Budget Success Pool: ordered list, pin button on each card, drag handle.
- Sticky totals bar: cost, remaining, outcome, Elo, count.
- Metric select for auto-eject.
- Over-budget can appear after a budget shrink when pins block eject (flash + Over-by totals). Blocked actions still flash in #flash.
- Adding an exclusive alternative, shrinking the budget, or a rate change that forces ejections OOB-swaps `#flash` with the names that left the pool.
- Site tabs are sticky (`site-top`). On the Pool tab, `#pool-sticky` under the tabs is 50/50 Budget+FX (left) and the duck pool (right); Auto-eject metric sits under that row. Narrow viewports stack; Budget+FX keep a min width of 18rem.
- `#pool-fill` is HTML water. Height is `calc(var(--pool-fill-ratio) * 100%)` from the basin floor (side view). At 100% the water and duck sit at the top of the frame. Empty interior is transparent. Caption is `N% full`. Over-budget tints the water red. HTMX OOB-swaps `#pool-fill`.

## Contest tab

- Two large cards side by side (`md:grid-cols-2`), each with name, description, cost, outcome, current Elo, W-L.
- Buttons: “A is better”, “Skip”, “B is better”, **Undo last match**.
- Progress bar + “N / M pairs decided” + Start / Stop.
- Recap of the last action.
- “Reset Elo to 1500” with confirm.
- Leaderboard table under (or right column on xl): rank, name, Elo (1 decimal), matches, W-L.

## Accessibility

- Buttons have visible labels (not icon-only).
- Color is not the only status signal (text for errors).
- Contest buttons are real `<button>` elements, keyboard reachable.

## Export tab

Same sticky chrome. Full report then contractor list. Toolbar `?ccy=SGD|USD|MYR`. Nav **Export** opens `/export.html`; that page links to markdown and contractor views.

## Theme, favicon, empty art

`settings.theme` is `system` (default), `light`, or `dark`. `POST /settings/theme` stores it. `base.html` sets `data-theme` on `<html>` and a blocking script in the document adds class `dark` when the theme is `dark`, or when it is `system` and `prefers-color-scheme: dark`. Tailwind Play uses `darkMode: 'class'`. Header control is `_partials/theme_switch.html` (System / Light / Dark). Favicon is `static/favicon.svg`. Empty lists (Projects, Available Pool, Contest idle) keep their sentences and draw `_partials/empty_art.html` above the text. `html.dark` overrides live in `static/app.css`.
