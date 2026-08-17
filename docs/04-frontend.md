# Frontend

Server-rendered. No build step. No Node required.

## Assets

In `base.html` `<head>`:

- Tailwind CSS Play CDN (`https://cdn.tailwindcss.com`) with a small `tailwind.config` for brand colors.
- HTMX 2 from jsDelivr.
- SortableJS from jsDelivr.

`static/app.css` only for things Tailwind CDN cannot express (card min-heights, contest progress bar).

`static/app.js`:

- Init Sortable on `#available-list` and `#pool-list`.
- On add (Available → Pool): `POST /pool/add/{id}` via `htmx.ajax`.
- On remove (Pool → Available): `POST /pool/remove/{id}`.
- On pool reorder: `POST /pool/reorder` with the new id order.
- Disable Sortable while an HTMX request is in flight.

## Visual design

Clean, modern, readable. Light page (`slate-50` background, white cards, `slate-900` text, indigo accent). Large tap targets. Tab nav with the active route underlined.

Every money amount uses a helper macro:

```
S$12,000  ·  US$8,880  ·  RM41,400
```

## Projects tab

- Left or top: budget card (amount + currency select + rates editor).
- Table/cards of projects: name, description, cost (3 fx), outcome, Elo, matches W-L, dependency chips.
- “Add project” form: name, description, cost + currency, outcome, multi-select checkboxes of other projects for dependencies.
- Edit in place (HTMX swap a form into the row).
- Delete with `hx-confirm`.

## Optimize tab

- Metric radio: Outcome / Elo / Blend.
- Primary button “Optimize”.
- Results: selected table, excluded table, totals (cost 3 fx, remaining, outcome, value).
- Button “Apply selection to pool”.

## Pool tab

Two equal columns on desktop, stacked on mobile (`md:grid-cols-2`).

- Available: projects not in pool.
- In-Budget Success Pool: ordered list, pin button on each card, drag handle.
- Sticky totals bar: cost, remaining, outcome, Elo, count.
- Metric select for auto-eject.
- Over-budget never appears; blocked actions flash in `#flash`.

## Contest tab

- Two large cards side by side (`md:grid-cols-2`), each with name, description, cost, outcome, current Elo, W-L.
- Buttons: “A is better”, “Skip”, “B is better”.
- Progress bar + “N / M pairs decided” + Start / Stop.
- “Reset Elo to 1500” with confirm.
- Leaderboard table under (or right column on xl): rank, name, Elo (1 decimal), matches, W-L.

## Accessibility

- Buttons have visible labels (not icon-only).
- Color is not the only status signal (text for errors).
- Contest buttons are real `<button>` elements, keyboard reachable.
