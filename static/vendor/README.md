# Vendored front-end (no CDN at runtime)

Pinned copies so a friend’s Mac does not need the public internet after install.

| File | Version | Upstream |
|---|---|---|
| `tailwindcss.js` | 3.4.17 Play CDN | https://cdn.tailwindcss.com/3.4.17 |
| `htmx.min.js` | 2.0.4 | https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js |
| `Sortable.min.js` | 1.15.2 | https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js |

Refresh (from this directory):

```bash
curl -fsSL -o tailwindcss.js "https://cdn.tailwindcss.com/3.4.17"
curl -fsSL -o htmx.min.js "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"
curl -fsSL -o Sortable.min.js "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"
```

Still no Node / npm. A later `.app` bundle can ship this folder as-is.
