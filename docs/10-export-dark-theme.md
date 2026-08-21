# Export tab — dark theme (In-Budget Success Pool)

On-screen Export (`/export.html` and `/export/contractor.html`) injects `_SHEET_STYLE` in `extra_head` **after** `app.css`. Those rules keep mint/amber row fills (`#ecfdf5` / `#fff7ed`) and slate type (`#334155` on `.meta`). In `html.dark` the page body is `#e2e8f0` on `#0f172a`, so the success-pool table is light type on mint (or dark type on the dark page chrome) and is illegible.

Print stays light: do not change `@media print` or `_SHEET_STYLE` in `services.py`.

Fix in `static/app.css` only, with `!important` so it beats the later export `<style>`:

- `.export-report` headings `#f8fafc`; meta/key/empty/th `#cbd5e1`; sheet td `#e2e8f0`; sheet borders `#334155`.
- `tr.row.pool td` same as `html.dark .sub-in`: background `#052e16`, type `#e2e8f0`.
- `tr.row.excl td` same as `html.dark .sub-out`: background `#431407`, type `#e2e8f0`.
- Toolbar links `#a5b4fc`. Badges: pool `#bbf7d0` on `#052e16` / `#15803d`; excl `#fed7aa` on `#431407` / `#c2410c`.

Contractor rows also use `tr.row.pool`. Append only; do not rewrite `app.css`.
