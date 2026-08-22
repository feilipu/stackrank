"""CRUD, settings, pool, contest, and optimize apply."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque

from stackrank.currency import (
    CURRENCIES,
    metric_value,
    to_myr,
    to_sgd,
    to_usd,
)
from stackrank.elo import (
    DEFAULT_ELO,
    K_FACTOR,
    choose_pair,
    shown_set_from_rows,
    unique_pair_count,
    update_ratings,
)
from stackrank.optimizer import optimize as run_optimize
from stackrank.seed import utcnow

EPS = 1e-6


def budget_fill(cost_sgd: float, budget_sgd: float) -> dict:
    """Used-budget fraction for the Pool tab fill graphic."""
    if budget_sgd <= EPS:
        raw = 0.0
    else:
        raw = float(cost_sgd) / float(budget_sgd)
    clamped = min(1.0, max(0.0, raw))
    return {
        "fill_ratio_raw": raw,
        "fill_ratio": clamped,
        "fill_pct": int(round(clamped * 100)),
    }


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_settings(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()


def list_projects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE"))


def get_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def dependencies_map(conn: sqlite3.Connection) -> dict[int, list[int]]:
    mapping: dict[int, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT project_id, depends_on_id FROM project_dependencies"):
        mapping[int(row["project_id"])].append(int(row["depends_on_id"]))
    return mapping


def dependents_map(conn: sqlite3.Connection) -> dict[int, list[int]]:
    mapping: dict[int, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT project_id, depends_on_id FROM project_dependencies"):
        mapping[int(row["depends_on_id"])].append(int(row["project_id"]))
    return mapping


def dependency_pairs(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    return [
        (int(r["project_id"]), int(r["depends_on_id"]))
        for r in conn.execute("SELECT project_id, depends_on_id FROM project_dependencies")
    ]


def exclusions_map(conn: sqlite3.Connection) -> dict[int, list[int]]:
    """Undirected: an exclude on A is also visible on B."""
    mapping: dict[int, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT project_id, excludes_id FROM project_exclusions"):
        a, b = int(row["project_id"]), int(row["excludes_id"])
        if a == b:
            continue
        if b not in mapping[a]:
            mapping[a].append(b)
        if a not in mapping[b]:
            mapping[b].append(a)
    return mapping


def exclusion_pairs(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    return [
        (int(r["project_id"]), int(r["excludes_id"]))
        for r in conn.execute("SELECT project_id, excludes_id FROM project_exclusions")
    ]


def names_by_id(conn: sqlite3.Connection) -> dict[int, str]:
    return {int(r["id"]): r["name"] for r in conn.execute("SELECT id, name FROM projects")}


def export_filename(conn: sqlite3.Connection, ext: str = "md") -> str:
    """Safe download name from the overall project title."""
    settings = get_settings(conn)
    try:
        raw = (settings["project_name"] or "").strip()
    except (IndexError, KeyError):
        raw = ""
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    ext = (ext or "md").lstrip(".") or "md"
    return f"{slug or 'stackrank'}.{ext}"


# Pool board colours (docs/04-frontend.md): green = in, amber = excluded.
_POOL_FG, _POOL_BG, _POOL_BD = "#047857", "#ecfdf5", "#6ee7b7"
_EXCL_FG, _EXCL_BG, _EXCL_BD = "#c2410c", "#fff7ed", "#fdba74"

_EXPORT_STYLE = f"""\
<style>
/* Colours match the Pool board. Shown by VS Code, Typora, Obsidian, and most HTML-capable Markdown previews. */
.sr-key-pool, .sr-badge-pool {{ color: {_POOL_FG}; background: {_POOL_BG}; border-color: {_POOL_BD}; }}
.sr-key-excl, .sr-badge-excl {{ color: {_EXCL_FG}; background: {_EXCL_BG}; border-color: {_EXCL_BD}; }}
.sr-banner-pool {{ background: {_POOL_BG}; border-left: 6px solid {_POOL_BD}; color: {_POOL_FG}; }}
.sr-banner-excl {{ background: {_EXCL_BG}; border-left: 6px solid {_EXCL_BD}; color: {_EXCL_FG}; }}
.sr-badge {{ display: inline-block; padding: 1px 8px; border-radius: 999px; border: 1px solid; font-weight: 600; font-size: 0.85em; }}
.sr-banner {{ padding: 0.55rem 0.85rem; border-radius: 0.375rem; margin: 0.35rem 0 0.85rem; }}
.sr-card-pool {{ background: {_POOL_BG}; border: 1px solid {_POOL_BD}; border-left: 6px solid #34d399; }}
.sr-card-excl {{ background: {_EXCL_BG}; border: 1px solid {_EXCL_BD}; border-left: 6px solid #fb923c; }}
.sr-card {{ padding: 10px 14px; border-radius: 6px; margin: 0 0 1rem; }}
.sr-card p {{ margin: 0.25em 0; }}
</style>
"""


def _md_badge(label: str, kind: str) -> str:
    cls = "sr-badge sr-badge-pool" if kind == "pool" else "sr-badge sr-badge-excl"
    fg, bg, bd = (_POOL_FG, _POOL_BG, _POOL_BD) if kind == "pool" else (_EXCL_FG, _EXCL_BG, _EXCL_BD)
    return (
        f'<span class="{cls}" style="display:inline-block;color:{fg};background:{bg};'
        f'border:1px solid {bd};padding:1px 8px;border-radius:999px;'
        f'font-weight:600;font-size:0.85em">{label}</span>'
    )


def _md_banner(kind: str, html: str) -> str:
    cls = "sr-banner sr-banner-pool" if kind == "pool" else "sr-banner sr-banner-excl"
    fg, bg, bd = (_POOL_FG, _POOL_BG, _POOL_BD) if kind == "pool" else (_EXCL_FG, _EXCL_BG, _EXCL_BD)
    return (
        f'<p class="{cls}" style="background:{bg};border-left:6px solid {bd};'
        f'color:{fg};padding:0.55rem 0.85rem;border-radius:0.375rem">{html}</p>'
    )


def _md_card_open(kind: str) -> str:
    cls = "sr-card sr-card-pool" if kind == "pool" else "sr-card sr-card-excl"
    bg, bd, accent = (
        (_POOL_BG, _POOL_BD, "#34d399") if kind == "pool" else (_EXCL_BG, _EXCL_BD, "#fb923c")
    )
    return (
        f'<div class="{cls}" style="background:{bg};border:1px solid {bd};'
        f'border-left:6px solid {accent};padding:10px 14px;border-radius:6px;margin:0 0 1rem">'
    )


def _md_card_close() -> str:
    return "</div>"


def _md_html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _norm_export_ccy(ccy: str | None) -> str:
    c = (ccy or "SGD").strip().upper()
    return c if c in CURRENCIES else "SGD"


def export_currency(ccy: str | None) -> str:
    return _norm_export_ccy(ccy)


def _export_snapshot(conn: sqlite3.Connection, currency: str | None = "SGD") -> dict:
    settings = get_settings(conn)
    try:
        project_name = (settings["project_name"] or "").strip() or "Untitled project"
    except (IndexError, KeyError):
        project_name = "Untitled project"
    usd, myr = settings["usd_per_sgd"], settings["myr_per_sgd"]
    budget_sgd = float(settings["budget_sgd"])
    all_projects = list_projects(conn)
    pooled = list(pool_rows(conn))
    pool_ids = {int(r["id"]) for r in pooled}
    spent_sgd = sum(float(r["cost_sgd"]) for r in pooled)
    remaining = max(0.0, budget_sgd - spent_sgd)
    names = names_by_id(conn)
    deps = dependencies_map(conn)
    excluded = [p for p in all_projects if int(p["id"]) not in pool_ids]
    return {
        "project_name": project_name,
        "usd": usd,
        "myr": myr,
        "currency": _norm_export_ccy(currency),
        "budget_sgd": budget_sgd,
        "spent_sgd": spent_sgd,
        "all_projects": all_projects,
        "pooled": pooled,
        "pool_ids": pool_ids,
        "remaining": remaining,
        "names": names,
        "deps": deps,
        "excluded": excluded,
    }


def _one_line(text) -> str:
    s = " ".join(str(text or "").split())
    return s or "—"


def _cost_cell(sgd, currency, usd, myr) -> str:
    c = _norm_export_ccy(currency)
    amount = float(sgd)
    if c == "USD":
        return f"US${to_usd(amount, usd):,.0f}"
    if c == "MYR":
        return f"RM{to_myr(amount, myr):,.0f}"
    return f"S${amount:,.0f}"


def _cost_of(snap: dict, sgd) -> str:
    return _cost_cell(sgd, snap["currency"], snap["usd"], snap["myr"])


def _dep_cell(pid: int, names: dict, deps: dict) -> str:
    items = [names.get(d, "?") for d in deps.get(int(pid), [])]
    return ", ".join(items) if items else "—"


def _notes_of(row) -> str:
    raw = (row["notes"] if "notes" in row.keys() else "") or ""
    return _one_line(raw)


def _md_cell(text) -> str:
    return _one_line(text).replace("|", "\\|")


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def _pool_sheet_rows(snap: dict) -> list[list[str]]:
    names, deps = snap["names"], snap["deps"]
    rows = []
    for i, p_row in enumerate(snap["pooled"], start=1):
        pid = int(p_row["id"])
        pin = " (pinned)" if int(p_row["pinned"]) else ""
        rows.append(
            [
                str(i),
                f"{names.get(pid, '?')}{pin}",
                _cost_of(snap, p_row["cost_sgd"]),
                p_row["outcome"],
                round(float(p_row["elo_rating"])),
                _dep_cell(pid, names, deps),
                _notes_of(p_row),
            ]
        )
    return rows


def _excl_sheet_rows(snap: dict) -> list[list[str]]:
    names, deps = snap["names"], snap["deps"]
    rows = []
    for i, row in enumerate(snap["excluded"], start=1):
        pid = int(row["id"])
        rows.append(
            [
                str(i),
                row["name"],
                _cost_of(snap, row["cost_sgd"]),
                row["outcome"],
                round(float(row["elo_rating"])),
                _dep_cell(pid, names, deps),
                _notes_of(row),
            ]
        )
    return rows


def _contractor_sheet_rows(snap: dict) -> list[list[str]]:
    names, deps = snap["names"], snap["deps"]
    rows = []
    for i, p_row in enumerate(snap["pooled"], start=1):
        pid = int(p_row["id"])
        pin = " (pinned)" if int(p_row["pinned"]) else ""
        rows.append(
            [
                str(i),
                f"{names.get(pid, '?')}{pin}",
                _one_line(p_row["description"]),
                _cost_of(snap, p_row["cost_sgd"]),
                _dep_cell(pid, names, deps),
                _notes_of(p_row),
            ]
        )
    return rows


def export_markdown(conn: sqlite3.Connection, currency: str | None = "SGD") -> str:
    """Compact markdown: one table row per sub-project."""
    snap = _export_snapshot(conn, currency)
    headers = ["#", "Project", "Cost", "Outcome", "Elo", "Depends on", "Notes"]
    pool_rows_md = _pool_sheet_rows(snap)
    excl_rows_md = _excl_sheet_rows(snap)

    lines = [
        f"# {snap['project_name']}",
        "",
        _EXPORT_STYLE.rstrip(),
        "",
        f"Budget: {_cost_of(snap, snap['budget_sgd'])}",
        (
            f"Pool: {len(snap['pool_ids'])} of {len(snap['all_projects'])} in pool · "
            f"remaining {_cost_of(snap, snap['remaining'])}"
        ),
        "",
        (
            "**Colour key:** "
            f"{_md_badge('In pool', 'pool')} selected under budget · "
            f"{_md_badge('Excluded', 'excl')} not in the success pool"
        ),
        "",
        "| Group | Items |",
        "| --- | ---: |",
        f"| {_md_badge('In-Budget Success Pool', 'pool')} | {len(snap['pooled'])} |",
        f"| {_md_badge('Excluded', 'excl')} | {len(snap['excluded'])} |",
        "",
        "## In-Budget Success Pool",
        "",
    ]
    if pool_rows_md:
        lines.extend(_md_table(headers, pool_rows_md))
        lines.append("")
    else:
        lines.extend(["_None selected._", ""])
    lines.extend(["## Excluded", ""])
    if excl_rows_md:
        lines.extend(_md_table(headers, excl_rows_md))
        lines.append("")
    else:
        lines.extend(["_None excluded._", ""])
    return "\n".join(lines).rstrip() + "\n"


def _html_sheet(kind: str, headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        empty = {
            "pool": "None selected.",
            "excl": "None excluded.",
            "accepted": "None accepted.",
        }.get(kind, "None.")
        return f'<p class="empty">{empty}</p>'
    row_class = "excl" if kind == "excl" else "pool"
    bits = ['<table class="sheet"><thead><tr>']
    for h in headers:
        bits.append(f"<th>{_md_html_escape(h)}</th>")
    bits.append("</tr></thead><tbody>")
    for cells in rows:
        bits.append(f'<tr class="row {row_class}">')
        for i, cell in enumerate(cells):
            cls = ' class="clip"' if i >= 1 else ""
            bits.append(f"<td{cls}>{_md_html_escape(str(cell))}</td>")
        bits.append("</tr>")
    bits.append("</tbody></table>")
    return "".join(bits)


def _export_toolbar(*, contractor: bool, currency: str = "SGD") -> str:
    currency = _norm_export_ccy(currency)
    q = f"?ccy={currency}"
    action = "/export/contractor.html" if contractor else "/export.html"
    md = ("/export/contractor.md" if contractor else "/export.md") + q
    full_cls = ' class="current"' if not contractor else ""
    con_cls = ' class="current"' if contractor else ""
    options = []
    for c in CURRENCIES:
        sel = " selected" if c == currency else ""
        options.append(f'<option value="{c}"{sel}>{c}</option>')
    return (
        f'<form class="toolbar" method="get" action="{action}">'
        f'<a href="/export.html{q}"{full_cls}>Full report</a>'
        " · "
        f'<a href="/export/contractor.html{q}"{con_cls}>Contractor list</a>'
        " · "
        f'<a href="{md}">Download Markdown</a>'
        ' · <label>Currency <select name="ccy" onchange="this.form.submit()">'
        f"{''.join(options)}</select></label>"
        "</form>"
    )


_SHEET_STYLE = f"""
.export-report {{ max-width: 58rem; font-size: 0.875rem; }}
.export-report header.report {{ margin-bottom: 0.75rem; }}
.export-report h1 {{ font-size: 1.35rem; margin: 0 0 0.35rem; }}
.export-report h2 {{ font-size: 1rem; margin: 0 0 0.35rem; }}
.export-report .meta {{ color: #334155; margin: 0.15rem 0; }}
.export-report .toolbar {{ font-size: 0.875rem; margin: 0 0 0.75rem; }}
.export-report .toolbar a {{ color: #4338ca; }}
.export-report .toolbar a.current {{ font-weight: 700; }}
.export-report .toolbar label {{ margin-left: 0.15rem; }}
.export-report .toolbar select {{ margin-left: 0.25rem; }}
.export-report .meta.total {{ font-weight: 700; }}
.export-report .key {{ margin: 0.4rem 0; }}
.export-report table.summary {{ border-collapse: collapse; margin: 0.4rem 0 0.6rem; }}
.export-report table.summary th, .export-report table.summary td {{
  text-align: left; padding: 0.15rem 0.6rem 0.15rem 0;
}}
.export-report table.summary th {{
  color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
}}
.export-report section {{ margin: 0.65rem 0; }}
.export-report table.sheet {{
  width: 100%; border-collapse: collapse; font-size: 0.8rem;
}}
.export-report table.sheet th, .export-report table.sheet td {{
  border-bottom: 1px solid #e2e8f0; padding: 0.18rem 0.35rem;
  text-align: left; vertical-align: top;
}}
.export-report table.sheet th {{
  font-size: 0.65rem; text-transform: uppercase; color: #64748b; letter-spacing: 0.03em;
}}
.export-report tr.row.pool td {{ background: {_POOL_BG}; }}
.export-report tr.row.excl td {{ background: {_EXCL_BG}; }}
.export-report td.clip {{
  max-width: 11rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.export-report .empty {{ color: #64748b; font-style: italic; }}
@media print {{
  .export-report .toolbar {{ display: none; }}
  .export-report {{ max-width: none; font-size: 8.5pt; }}
  .export-report table.sheet {{ font-size: 8pt; }}
  .export-report table.sheet th, .export-report table.sheet td {{ padding: 0.08rem 0.2rem; }}
  .export-report h1 {{ font-size: 13pt; }}
  .export-report h2 {{ font-size: 10pt; }}
  .export-report section {{ margin: 0.4rem 0; }}
  tr.row {{ page-break-inside: avoid; }}
}}
"""


def export_html_parts(
    conn: sqlite3.Connection, currency: str | None = "SGD"
) -> tuple[str, str]:
    """Compact coloured tables for on-screen report and print."""
    snap = _export_snapshot(conn, currency)
    title = _md_html_escape(snap["project_name"])
    headers = ["#", "Project", "Cost", "Outcome", "Elo", "Depends on", "Notes"]
    money = _md_html_escape(_cost_of(snap, snap["budget_sgd"]))
    remain = _md_html_escape(_cost_of(snap, snap["remaining"]))
    inner = f"""<article class="export-report">
  {_export_toolbar(contractor=False, currency=snap["currency"])}
  <header class="report">
    <h1>{title}</h1>
    <p class="meta">Budget: {money}</p>
    <p class="meta">Pool: {len(snap["pool_ids"])} of {len(snap["all_projects"])} in pool · remaining {remain}</p>
    <p class="key"><strong>Colour key:</strong> {_md_badge("In pool", "pool")} selected under budget · {_md_badge("Excluded", "excl")} not in the success pool</p>
    <table class="summary">
      <tr><th>Group</th><th>Items</th></tr>
      <tr><td>{_md_badge("In-Budget Success Pool", "pool")}</td><td>{len(snap["pooled"])}</td></tr>
      <tr><td>{_md_badge("Excluded", "excl")}</td><td>{len(snap["excluded"])}</td></tr>
    </table>
  </header>
  <section>
    <h2>In-Budget Success Pool</h2>
    {_html_sheet("pool", headers, _pool_sheet_rows(snap))}
  </section>
  <section>
    <h2>Excluded</h2>
    {_html_sheet("excl", headers, _excl_sheet_rows(snap))}
  </section>
</article>
"""
    return _SHEET_STYLE, inner


def export_contractor_markdown(
    conn: sqlite3.Connection, currency: str | None = "SGD"
) -> str:
    """Accepted-pool list for a contractor: no Elo, no budget, no excluded set."""
    snap = _export_snapshot(conn, currency)
    headers = ["#", "Project", "Description", "Cost", "Depends on", "Notes"]
    total = _cost_of(snap, snap["spent_sgd"])
    lines = [
        f"# {snap['project_name']} — accepted projects",
        "",
        f"Accepted: {len(snap['pooled'])}",
        f"Total: {total}",
        "",
    ]
    rows = _contractor_sheet_rows(snap)
    if rows:
        lines.extend(_md_table(headers, rows))
        lines.append("")
        lines.append(f"Total: {total}")
        lines.append("")
    else:
        lines.extend(["_None accepted._", ""])
    return "\n".join(lines).rstrip() + "\n"


def export_contractor_html_parts(
    conn: sqlite3.Connection, currency: str | None = "SGD"
) -> tuple[str, str]:
    """Clean accepted-project table for contractors."""
    snap = _export_snapshot(conn, currency)
    title = _md_html_escape(snap["project_name"])
    headers = ["#", "Project", "Description", "Cost", "Depends on", "Notes"]
    total = _md_html_escape(_cost_of(snap, snap["spent_sgd"]))
    inner = f"""<article class="export-report">
  {_export_toolbar(contractor=True, currency=snap["currency"])}
  <header class="report">
    <h1>{title} — accepted projects</h1>
    <p class="meta">Accepted: {len(snap["pooled"])}</p>
    <p class="meta total">Total: {total}</p>
  </header>
  <section>
    {_html_sheet("accepted", headers, _contractor_sheet_rows(snap))}
    <p class="meta total">Total: {total}</p>
  </section>
</article>
"""
    return _SHEET_STYLE, inner


def export_html(conn: sqlite3.Connection, currency: str | None = "SGD") -> str:
    """Self-contained HTML report; green = in pool, amber = excluded."""
    settings = get_settings(conn)
    try:
        project_name = (settings["project_name"] or "").strip() or "Untitled project"
    except (IndexError, KeyError):
        project_name = "Untitled project"
    title = _md_html_escape(project_name)
    style, inner = export_html_parts(conn, currency)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; margin: 0; background: #f8fafc; color: #0f172a; line-height: 1.5; }}
  {style}
</style>
</head>
<body>
{inner}
</body>
</html>
"""



def _would_cycle(conn: sqlite3.Connection, project_id: int, depends_on: list[int]) -> bool:
    children: dict[int, list[int]] = defaultdict(list)
    for pid, dep in dependency_pairs(conn):
        if pid == project_id:
            continue
        children[dep].append(pid)
    for dep in depends_on:
        children[dep].append(project_id)

    seen: set[int] = set()
    stack: set[int] = set()

    def dfs(node: int) -> bool:
        if node in stack:
            return True
        if node in seen:
            return False
        stack.add(node)
        for nxt in children.get(node, []):
            if dfs(nxt):
                return True
        stack.remove(node)
        seen.add(node)
        return False

    return any(dfs(n) for n in list(children.keys()) + [project_id])


def _norm_id_list(raw) -> list[int]:
    out: list[int] = []
    for x in raw or []:
        i = int(x)
        if i and i not in out:
            out.append(i)
    return out


def _dep_graph(conn: sqlite3.Connection, project_id: int, depends_on: list[int]):
    children: dict[int, list[int]] = defaultdict(list)
    parents: dict[int, list[int]] = defaultdict(list)
    for pid, dep in dependency_pairs(conn):
        if pid == project_id:
            continue
        children[dep].append(pid)
        parents[pid].append(dep)
    for dep in depends_on:
        children[dep].append(project_id)
        parents[project_id].append(dep)
    return children, parents


def _walk_related(start: int, adj: dict[int, list[int]]) -> set[int]:
    out: set[int] = set()
    queue = deque(adj.get(start, []))
    while queue:
        node = queue.popleft()
        if node in out:
            continue
        out.add(node)
        queue.extend(adj.get(node, []))
    return out


def _dep_related_ids(conn: sqlite3.Connection, project_id: int, depends_on: list[int]) -> set[int]:
    children, parents = _dep_graph(conn, project_id, depends_on)
    return _walk_related(project_id, parents) | _walk_related(project_id, children)


def _proposed_excl_map(
    conn: sqlite3.Connection, project_id: int, excludes: list[int]
) -> dict[int, set[int]]:
    mapping: dict[int, set[int]] = defaultdict(set)
    for pid, other in exclusion_pairs(conn):
        if pid == project_id or other == project_id:
            continue
        mapping[pid].add(other)
    for other in excludes:
        mapping[project_id].add(other)
        mapping[other].add(project_id)
    return mapping


def _closures_have_exclusive(
    conn: sqlite3.Connection,
    project_id: int,
    depends_on: list[int],
    excludes: list[int],
) -> bool:
    _children, parents = _dep_graph(conn, project_id, depends_on)
    excl = _proposed_excl_map(conn, project_id, excludes)
    ids = {int(r["id"]) for r in list_projects(conn)} | {project_id}
    ancestor_cache: dict[int, set[int]] = {}

    def ancestors_of(node: int) -> set[int]:
        cached = ancestor_cache.get(node)
        if cached is not None:
            return cached
        found = _walk_related(node, parents)
        ancestor_cache[node] = found
        return found

    for pid in ids:
        closure = ancestors_of(pid) | {pid}
        for a in closure:
            if excl[a] & closure:
                return True
    return False


def _assert_exclusions_ok(
    conn: sqlite3.Connection,
    project_id: int,
    excludes: list[int],
    depends_on: list[int],
) -> list[int]:
    excludes = _norm_id_list(excludes)
    if project_id in excludes:
        raise ServiceError("A project cannot exclude itself.")
    existing = {int(r["id"]) for r in list_projects(conn)}
    if project_id:
        existing.add(project_id)
    for eid in excludes:
        if eid not in existing:
            raise ServiceError("Exclusion must be an existing project.")
    if set(excludes) & set(depends_on):
        raise ServiceError("A project cannot exclude something it depends on.")
    related = _dep_related_ids(conn, project_id, depends_on)
    if set(excludes) & related:
        raise ServiceError(
            "A project cannot exclude something it depends on, or that depends on it."
        )
    if _closures_have_exclusive(conn, project_id, depends_on, excludes):
        if excludes:
            raise ServiceError(
                "That exclusion would put mutually exclusive projects in the same dependency chain."
            )
        raise ServiceError("Dependencies include mutually exclusive projects.")
    return excludes


def _exclusion_partners(conn: sqlite3.Connection, project_id: int) -> set[int]:
    rows = conn.execute(
        """
        SELECT excludes_id AS other FROM project_exclusions WHERE project_id = ?
        UNION
        SELECT project_id AS other FROM project_exclusions WHERE excludes_id = ?
        """,
        (project_id, project_id),
    )
    return {int(r[0]) for r in rows}


def _drop_exclusion_pair(conn: sqlite3.Connection, left: int, right: int) -> None:
    conn.execute(
        """
        DELETE FROM project_exclusions
        WHERE (project_id = ? AND excludes_id = ?)
           OR (project_id = ? AND excludes_id = ?)
        """,
        (left, right, right, left),
    )


def _replace_exclusions(conn: sqlite3.Connection, project_id: int, excludes: list[int]) -> None:
    wanted = set(_norm_id_list(excludes))
    wanted.discard(project_id)
    old = _exclusion_partners(conn, project_id)
    for other in old - wanted:
        _drop_exclusion_pair(conn, project_id, other)
    for other in wanted:
        conn.execute(
            "INSERT OR IGNORE INTO project_exclusions (project_id, excludes_id) VALUES (?, ?)",
            (project_id, other),
        )
        conn.execute(
            "INSERT OR IGNORE INTO project_exclusions (project_id, excludes_id) VALUES (?, ?)",
            (other, project_id),
        )


def _eject_report(conn: sqlite3.Connection, exclusive_ids: list[int], budget_ids: list[int]) -> dict:
    names = names_by_id(conn)
    return {
        "exclusive_ids": list(exclusive_ids),
        "exclusive_names": [names.get(i, str(i)) for i in exclusive_ids],
        "budget_ids": list(budget_ids),
        "budget_names": [names.get(i, str(i)) for i in budget_ids],
    }


def _eject_exclusives_from_pool(
    conn: sqlite3.Connection, keep_id: int, excludes: list[int]
) -> list[int]:
    """Drop pooled alternatives of keep_id (and their unpinned dependents)."""
    current = pool_rows(conn)
    current_ids = {int(r["id"]) for r in current}
    if keep_id not in current_ids:
        return []
    pinned = {int(r["id"]) for r in current if int(r["pinned"])}
    depmap = dependents_map(conn)
    names = names_by_id(conn)
    drop: list[int] = []
    for other in excludes:
        if other not in current_ids or other in drop:
            continue
        cascade = {other} | {
            d for d in _transitive_dependents(other, depmap) if d in current_ids
        }
        blocked = cascade & pinned
        if blocked:
            label = ", ".join(names.get(i, str(i)) for i in sorted(blocked))
            raise ServiceError(
                f"Cannot exclude {names.get(other, other)} while it "
                f"(or a dependent) is pinned in the pool: {label}.",
                409,
            )
        for i in cascade:
            if i not in drop:
                drop.append(i)
    if not drop:
        return []
    remaining = [r for r in current if int(r["id"]) not in set(drop)]
    conn.execute("DELETE FROM pool_items")
    for idx, row in enumerate(remaining):
        conn.execute(
            "INSERT INTO pool_items (project_id, position, pinned) VALUES (?, ?, ?)",
            (int(row["id"]), idx, int(row["pinned"])),
        )
    return drop


def _validate_project(name: str, cost: float, outcome: float) -> str:
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ServiceError("Name must be 1–80 characters.")
    if cost <= 0:
        raise ServiceError("Cost must be a positive number.")
    if outcome <= 0:
        raise ServiceError("Outcome must be a positive number.")
    return name


def _norm_cost_currency(cost_currency: str) -> str:
    cost_currency = (cost_currency or "SGD").upper()
    if cost_currency not in CURRENCIES:
        raise ServiceError("Currency must be SGD, USD, or MYR.")
    return cost_currency


def refresh_project_costs(conn: sqlite3.Connection, settings=None) -> None:
    """Recompute each project's cost_sgd from its entered amount and currency."""
    settings = settings or get_settings(conn)
    usd, myr = float(settings["usd_per_sgd"]), float(settings["myr_per_sgd"])
    for row in conn.execute(
        "SELECT id, cost_amount, cost_currency FROM projects"
    ):
        amount = float(row["cost_amount"])
        ccy = _norm_cost_currency(row["cost_currency"])
        conn.execute(
            "UPDATE projects SET cost_sgd = ? WHERE id = ?",
            (to_sgd(amount, ccy, usd, myr), int(row["id"])),
        )


def create_project(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    notes: str = "",
    cost: float,
    cost_currency: str,
    outcome: float,
    depends_on: list[int],
    excludes: list[int] | None = None,
) -> int:
    settings = get_settings(conn)
    name = _validate_project(name, cost, outcome)
    notes = (notes or "").strip()[:500]
    cost_currency = _norm_cost_currency(cost_currency)
    cost_sgd = to_sgd(cost, cost_currency, settings["usd_per_sgd"], settings["myr_per_sgd"])
    depends_on = [int(x) for x in depends_on if int(x)]
    if any(d <= 0 for d in depends_on):
        raise ServiceError("Invalid dependency.")
    existing = {int(r["id"]) for r in list_projects(conn)}
    for dep in depends_on:
        if dep not in existing:
            raise ServiceError("Dependency must be an existing project.")
    excludes = _norm_id_list(excludes)
    if conn.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone():
        raise ServiceError("A project with that name already exists.")
    now = utcnow()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """
            INSERT INTO projects (
                name, description, notes, cost_sgd, cost_amount, cost_currency,
                outcome, elo_rating,
                matches_played, wins, losses, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1500, 0, 0, 0, ?, ?)
            """,
            (
                name,
                (description or "").strip(),
                notes,
                cost_sgd,
                cost,
                cost_currency,
                outcome,
                now,
                now,
            ),
        )
        pid = int(cur.lastrowid)
        if _would_cycle(conn, pid, depends_on):
            raise ServiceError("That dependency set would create a cycle.")
        for dep in depends_on:
            if dep == pid:
                raise ServiceError("A project cannot depend on itself.")
            conn.execute(
                "INSERT INTO project_dependencies (project_id, depends_on_id) VALUES (?, ?)",
                (pid, dep),
            )
        excludes = _assert_exclusions_ok(conn, pid, excludes, depends_on)
        _replace_exclusions(conn, pid, excludes)
        conn.execute("UPDATE settings SET last_cost_currency = ? WHERE id = 1", (cost_currency,))
        conn.execute("COMMIT")
        return pid
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not create project (duplicate name or bad dependency).") from exc


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    name: str,
    description: str,
    notes: str = "",
    cost: float,
    cost_currency: str,
    outcome: float,
    depends_on: list[int],
    excludes: list[int] | None = None,
) -> dict:
    if get_project(conn, project_id) is None:
        raise ServiceError("Project not found.", 404)
    settings = get_settings(conn)
    name = _validate_project(name, cost, outcome)
    notes = (notes or "").strip()[:500]
    cost_currency = _norm_cost_currency(cost_currency)
    cost_sgd = to_sgd(cost, cost_currency, settings["usd_per_sgd"], settings["myr_per_sgd"])
    depends_on = [int(x) for x in depends_on if int(x)]
    if project_id in depends_on:
        raise ServiceError("A project cannot depend on itself.")
    existing = {int(r["id"]) for r in list_projects(conn)}
    for dep in depends_on:
        if dep not in existing:
            raise ServiceError("Dependency must be an existing project.")
    other = conn.execute(
        "SELECT 1 FROM projects WHERE name = ? AND id != ?", (name, project_id)
    ).fetchone()
    if other:
        raise ServiceError("A project with that name already exists.")
    if _would_cycle(conn, project_id, depends_on):
        raise ServiceError("That dependency set would create a cycle.")
    write_excludes = excludes is not None
    if write_excludes:
        excludes = _assert_exclusions_ok(conn, project_id, excludes, depends_on)
    now = utcnow()
    ejected: list[int] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, notes = ?,
                cost_sgd = ?, cost_amount = ?, cost_currency = ?,
                outcome = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                (description or "").strip(),
                notes,
                cost_sgd,
                cost,
                cost_currency,
                outcome,
                now,
                project_id,
            ),
        )
        conn.execute("DELETE FROM project_dependencies WHERE project_id = ?", (project_id,))
        for dep in depends_on:
            conn.execute(
                "INSERT INTO project_dependencies (project_id, depends_on_id) VALUES (?, ?)",
                (project_id, dep),
            )
        if write_excludes:
            _replace_exclusions(conn, project_id, excludes)
            ejected = _eject_exclusives_from_pool(conn, project_id, excludes)
        conn.execute("UPDATE settings SET last_cost_currency = ? WHERE id = 1", (cost_currency,))
        conn.execute("COMMIT")
        return _eject_report(conn, ejected, [])
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not update project.") from exc


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    if get_project(conn, project_id) is None:
        raise ServiceError("Project not found.", 404)
    settings = get_settings(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if settings["contest_left_id"] == project_id or settings["contest_right_id"] == project_id:
            conn.execute(
                """
                UPDATE settings SET contest_active = 0, contest_left_id = NULL,
                    contest_right_id = NULL WHERE id = 1
                """
            )
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise


def update_project_name(conn: sqlite3.Connection, name: str) -> None:
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ServiceError("Project name must be 1–80 characters.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE settings SET project_name = ? WHERE id = 1", (name,))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not rename project.") from exc


def update_budget(conn: sqlite3.Connection, amount: float, currency: str) -> dict:
    if amount <= 0:
        raise ServiceError("Budget must be a positive number.")
    currency = (currency or "SGD").upper()
    settings = get_settings(conn)
    budget_sgd = to_sgd(amount, currency, settings["usd_per_sgd"], settings["myr_per_sgd"])
    if budget_sgd <= 0:
        raise ServiceError("Budget must be a positive number.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE settings SET budget_sgd = ?, budget_currency = ? WHERE id = 1",
            (budget_sgd, currency),
        )
        ejected = rebalance_pool(conn, budget_sgd)
        conn.execute("COMMIT")
        return {
            "ejected_ids": ejected,
            "ejected_names": [names_by_id(conn).get(i, str(i)) for i in ejected],
            "over_budget": sum(float(r["cost_sgd"]) for r in pool_rows(conn)) > budget_sgd + EPS,
            "pool_cost_sgd": sum(float(r["cost_sgd"]) for r in pool_rows(conn)),
            "budget_sgd": budget_sgd,
        }
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not update budget.") from exc


def update_rates(conn: sqlite3.Connection, usd_per_sgd: float, myr_per_sgd: float) -> dict:
    if usd_per_sgd <= 0 or myr_per_sgd <= 0:
        raise ServiceError("Conversion rates must be positive.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE settings SET usd_per_sgd = ?, myr_per_sgd = ? WHERE id = 1",
            (usd_per_sgd, myr_per_sgd),
        )
        settings = get_settings(conn)
        refresh_project_costs(conn, settings)
        ejected = rebalance_pool(conn, float(settings["budget_sgd"]))
        conn.execute("COMMIT")
        return {
            "ejected_ids": ejected,
            "ejected_names": [names_by_id(conn).get(i, str(i)) for i in ejected],
        }
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not update rates.") from exc


def set_optimize_metric(conn: sqlite3.Connection, metric: str) -> None:
    if metric not in {"outcome", "elo", "blend"}:
        raise ServiceError("Unknown optimize metric.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE settings SET optimize_metric = ? WHERE id = 1", (metric,))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not set optimize metric.") from exc


def set_pool_metric(conn: sqlite3.Connection, metric: str) -> None:
    if metric not in {"outcome", "elo", "blend"}:
        raise ServiceError("Unknown pool metric.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE settings SET pool_eject_metric = ? WHERE id = 1", (metric,))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not set pool metric.") from exc


def set_theme(conn: sqlite3.Connection, theme: str) -> None:
    theme = (theme or "system").strip().lower()
    if theme not in {"system", "light", "dark"}:
        raise ServiceError("Theme must be system, light, or dark.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE settings SET theme = ? WHERE id = 1", (theme,))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not set theme.") from exc


def pool_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
             """
            SELECT p.*, i.position, i.pinned
            FROM pool_items i
            JOIN projects p ON p.id = i.project_id
            ORDER BY i.position ASC, p.id ASC
             """
         )
     )


def rebalance_pool(conn, budget, *, protect_ids=None) -> list[int]:
    protect_ids = set(protect_ids or ())
    settings = get_settings(conn)
    metric = settings["pool_eject_metric"]
    members = []
    for row in pool_rows(conn):
        members.append({
            "id": int(row["id"]),
            "cost": float(row["cost_sgd"]),
            "pinned": int(row["pinned"]),
            "position": int(row["position"]),
            "value": metric_value(metric, float(row["outcome"]), float(row["elo_rating"])),
        })
    ejected = []
    depmap = dependents_map(conn)
    by_id = {m["id"]: m for m in members}

    def required_by_pinned(mid):
        for did in _transitive_dependents(mid, depmap):
            other = by_id.get(did)
            if other and other["pinned"]:
                return True
        return False

    while sum(m["cost"] for m in members) > budget + EPS:
        by_id = {m["id"]: m for m in members}
        cands = [
            m for m in members
            if not m["pinned"] and m["id"] not in protect_ids and not required_by_pinned(m["id"])
        ]
        if not cands:
            cands = [
                m for m in members
                if not m["pinned"] and not required_by_pinned(m["id"])
            ]
        if not cands:
            break
        victim = min(cands, key=lambda m: (m["value"], -m["position"], -m["id"]))
        drop = {victim["id"]} | {
            did for did in _transitive_dependents(victim["id"], depmap)
            if did in by_id and not by_id[did]["pinned"]
        }
        members = [m for m in members if m["id"] not in drop]
        ejected.extend(i for i in drop if i not in ejected)
    conn.execute("DELETE FROM pool_items")
    for idx, m in enumerate(members):
        conn.execute(
            "INSERT INTO pool_items (project_id, position, pinned) VALUES (?, ?, ?)",
            (m["id"], idx, m["pinned"]),
        )
    return ejected


def _transitive_deps(start: int, deps: dict[int, list[int]]) -> set[int]:
    out: set[int] = set()
    queue = deque(deps.get(start, []))
    while queue:
        node = queue.popleft()
        if node in out:
            continue
        out.add(node)
        queue.extend(deps.get(node, []))
    return out


def _transitive_dependents(start: int, dependents: dict[int, list[int]]) -> set[int]:
    return _transitive_deps(start, dependents)


def add_to_pool(conn: sqlite3.Connection, project_id: int) -> dict:
    project = get_project(conn, project_id)
    if project is None:
        raise ServiceError("Project not found.", 404)
    settings = get_settings(conn)
    deps = dependencies_map(conn)
    current = pool_rows(conn)
    current_ids = [int(r["id"]) for r in current]
    if project_id in current_ids:
        return _eject_report(conn, [], [])
    exclusive_ids: list[int] = []
    budget_ids: list[int] = []
    missing = [d for d in _transitive_deps(project_id, deps) if d not in current_ids]
    if missing:
        for dep_id in list(missing):
            sub = add_to_pool(conn, dep_id)
            for i in sub.get("exclusive_ids", []):
                if i not in exclusive_ids:
                    exclusive_ids.append(i)
            for i in sub.get("budget_ids", []):
                if i not in budget_ids:
                    budget_ids.append(i)
        # Re-read pool after recursion
        current = pool_rows(conn)
        current_ids = [int(r["id"]) for r in current]
        # Check if the requested project is now already in pool
        if project_id in current_ids:
            return _eject_report(conn, exclusive_ids, budget_ids)

    metric = settings["pool_eject_metric"]
    budget = float(settings["budget_sgd"])

    members: list[dict] = []
    for row in current:
        members.append(
            {
                "id": int(row["id"]),
                "cost": float(row["cost_sgd"]),
                "pinned": int(row["pinned"]),
                "position": int(row["position"]),
                "value": metric_value(metric, float(row["outcome"]), float(row["elo_rating"])),
            }
        )
    incoming = {
        "id": project_id,
        "cost": float(project["cost_sgd"]),
        "pinned": 0,
        "position": len(members),
        "value": metric_value(metric, float(project["outcome"]), float(project["elo_rating"])),
    }
    members.append(incoming)

    def total(items: list[dict]) -> float:
        return sum(i["cost"] for i in items)

    excl = set(exclusions_map(conn).get(project_id, []))
    depmap = dependents_map(conn)
    names = names_by_id(conn)
    by_id = {m["id"]: m for m in members}
    for other in list(excl):
        if other not in by_id:
            continue
        cascade = {other} | {
            did for did in _transitive_dependents(other, depmap) if did in by_id
        }
        if any(by_id[i]["pinned"] for i in cascade if i in by_id):
            raise ServiceError(
                f"Cannot add {project['name']}: it cannot coexist with pinned "
                f"{names.get(other, other)}.",
                409,
            )
        members = [m for m in members if m["id"] not in cascade]
        for i in cascade:
            if i not in exclusive_ids:
                exclusive_ids.append(i)
        by_id = {m["id"]: m for m in members}

    while total(members) > budget + EPS:
        candidates = [m for m in members if m["id"] != project_id and not m["pinned"]]
        if not candidates:
            raise ServiceError(
                "Does not fit even after ejecting unpinned projects.",
                409,
            )
        victim = min(candidates, key=lambda m: (m["value"], -m["position"], -m["id"]))
        members = [m for m in members if m["id"] != victim["id"]]
        if victim["id"] not in budget_ids:
            budget_ids.append(victim["id"])

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM pool_items")
        for idx, member in enumerate(members):
            pinned = 1 if member["id"] != project_id and member["pinned"] else 0
            conn.execute(
                "INSERT INTO pool_items (project_id, position, pinned) VALUES (?, ?, ?)",
                (member["id"], idx, pinned),
            )
        conn.execute("COMMIT")
        exclusive_set = set(exclusive_ids)
        budget_ids = [i for i in budget_ids if i not in exclusive_set]
        return _eject_report(conn, exclusive_ids, budget_ids)
    except ServiceError:
        conn.execute("ROLLBACK")
        raise


def remove_from_pool(conn: sqlite3.Connection, project_id: int) -> None:
    current = pool_rows(conn)
    current_ids = {int(r["id"]) for r in current}
    if project_id not in current_ids:
        return
    dependents = dependents_map(conn)
    blockers = [d for d in _transitive_dependents(project_id, dependents) if d in current_ids]
    if blockers:
        names = names_by_id(conn)
        label = ", ".join(names[i] for i in blockers)
        raise ServiceError(f"Still required by pooled projects: {label}.", 409)
    remaining = [r for r in current if int(r["id"]) != project_id]
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DELETE FROM pool_items")
    for idx, row in enumerate(remaining):
        conn.execute(
            "INSERT INTO pool_items (project_id, position, pinned) VALUES (?, ?, ?)",
            (int(row["id"]), idx, int(row["pinned"])),
        )
    conn.execute("COMMIT")


def reorder_pool(conn: sqlite3.Connection, ids: list[int]) -> None:
    current = {int(r["id"]): int(r["pinned"]) for r in pool_rows(conn)}
    if set(ids) != set(current):
        raise ServiceError("Reorder must include exactly the current pool.", 409)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DELETE FROM pool_items")
    for idx, pid in enumerate(ids):
        conn.execute(
            "INSERT INTO pool_items (project_id, position, pinned) VALUES (?, ?, ?)",
            (pid, idx, current[pid]),
        )
    conn.execute("COMMIT")


def toggle_pin(conn: sqlite3.Connection, project_id: int) -> None:
    row = conn.execute("SELECT pinned FROM pool_items WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        raise ServiceError("Project is not in the pool.", 409)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE pool_items SET pinned = ? WHERE project_id = ?",
            (0 if row["pinned"] else 1, project_id),
        )
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not toggle pin.") from exc


def apply_optimize_to_pool(conn: sqlite3.Connection, selected_ids: list[int]) -> None:
    projects = list_projects(conn)
    by_id = {int(p["id"]): p for p in projects}
    chosen = {int(i) for i in selected_ids}
    excl = exclusions_map(conn)
    for pid in chosen:
        for other in excl.get(pid, []):
            if other in chosen:
                raise ServiceError(
                    "Selection includes mutually exclusive projects.",
                    409,
                )
    settings = get_settings(conn)
    metric = settings["optimize_metric"]
    ranked = sorted(
        selected_ids,
        key=lambda i: (
            -metric_value(metric, float(by_id[i]["outcome"]), float(by_id[i]["elo_rating"])),
            i,
        ),
    )
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DELETE FROM pool_items")
    for idx, pid in enumerate(ranked):
        conn.execute(
            "INSERT INTO pool_items (project_id, position, pinned) VALUES (?, ?, 0)",
            (pid, idx),
        )
    conn.execute("COMMIT")


def optimize_now(conn: sqlite3.Connection, metric: str | None = None) -> dict:
    if metric:
        set_optimize_metric(conn, metric)
    settings = get_settings(conn)
    projects = [dict(p) for p in list_projects(conn)]
    return run_optimize(
        projects,
        dependency_pairs(conn),
        float(settings["budget_sgd"]),
        settings["optimize_metric"],
        exclusion_pairs(conn),
    )


def save_last_optimize(conn: sqlite3.Connection, payload: dict) -> None:
    """Persist a compact last-optimize snapshot in settings.last_optimize_json."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE settings SET last_optimize_json = ? WHERE id = 1", (json.dumps(payload),))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise


def load_last_optimize(conn: sqlite3.Connection) -> dict | None:
    """Load the compact last-optimize snapshot, or None if absent/corrupt."""
    row = conn.execute("SELECT last_optimize_json FROM settings WHERE id = 1").fetchone()
    raw = row[0] if row is not None else None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _end_contest_sql(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE settings SET contest_active = 0, contest_left_id = NULL,
            contest_right_id = NULL WHERE id = 1
        """
    )


def start_contest(conn: sqlite3.Connection) -> None:
    projects = [dict(p) for p in list_projects(conn)]
    if len(projects) < 2:
        raise ServiceError("Need at least two projects to start a contest.")
    rows = list(conn.execute("SELECT left_id, right_id FROM contest_matches ORDER BY id"))
    shown, recent = shown_set_from_rows(rows)
    pair = choose_pair(projects, shown, recent)
    if pair is None:
        raise ServiceError("Need at least two projects to start a contest.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE settings SET contest_active = 1, contest_left_id = ?, contest_right_id = ?
            WHERE id = 1
            """,
            pair,
        )
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not start contest.") from exc


def stop_contest(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        _end_contest_sql(conn)
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not stop contest.") from exc


def _advance_pair(conn: sqlite3.Connection) -> None:
    projects = [dict(p) for p in list_projects(conn)]
    if len(projects) < 2:
        _end_contest_sql(conn)
        return
    rows = list(conn.execute("SELECT left_id, right_id FROM contest_matches ORDER BY id"))
    shown, recent = shown_set_from_rows(rows)
    pair = choose_pair(projects, shown, recent)
    if pair is None:
        _end_contest_sql(conn)
        return
    conn.execute(
        "UPDATE settings SET contest_left_id = ?, contest_right_id = ? WHERE id = 1",
        pair,
    )


def contest_choose(conn: sqlite3.Connection, winner_id: int) -> None:
    settings = get_settings(conn)
    if not settings["contest_active"]:
        raise ServiceError("No contest is running.")
    left_id, right_id = int(settings["contest_left_id"]), int(settings["contest_right_id"])
    if winner_id not in {left_id, right_id}:
        raise ServiceError("Winner must be one of the current pair.")
    left = get_project(conn, left_id)
    right = get_project(conn, right_id)
    score_left = 1.0 if winner_id == left_id else 0.0
    new_left, new_right = update_ratings(float(left["elo_rating"]), float(right["elo_rating"]), score_left)
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        INSERT INTO contest_matches (
            left_id, right_id, winner_id, k_factor,
            left_elo_before, right_elo_before, left_elo_after, right_elo_after, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            left_id,
            right_id,
            winner_id,
            K_FACTOR,
            float(left["elo_rating"]),
            float(right["elo_rating"]),
            new_left,
            new_right,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE projects SET elo_rating = ?, matches_played = matches_played + 1,
            wins = wins + ?, losses = losses + ?, updated_at = ? WHERE id = ?
        """,
        (new_left, 1 if winner_id == left_id else 0, 0 if winner_id == left_id else 1, now, left_id),
    )
    conn.execute(
        """
        UPDATE projects SET elo_rating = ?, matches_played = matches_played + 1,
            wins = wins + ?, losses = losses + ?, updated_at = ? WHERE id = ?
        """,
        (new_right, 1 if winner_id == right_id else 0, 0 if winner_id == right_id else 1, now, right_id),
    )
    conn.execute(
        """
        UPDATE settings SET contest_shown = contest_shown + 1, contest_decided = contest_decided + 1
        WHERE id = 1
        """
    )
    conn.execute("COMMIT")
    _advance_pair(conn)


def contest_skip(conn: sqlite3.Connection) -> None:
    settings = get_settings(conn)
    if not settings["contest_active"]:
        raise ServiceError("No contest is running.")
    left_id, right_id = int(settings["contest_left_id"]), int(settings["contest_right_id"])
    left = get_project(conn, left_id)
    right = get_project(conn, right_id)
    now = utcnow()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO contest_matches (
                left_id, right_id, winner_id, k_factor,
                left_elo_before, right_elo_before, left_elo_after, right_elo_after, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, ?)
            """,
            (left_id, right_id, K_FACTOR, float(left["elo_rating"]), float(right["elo_rating"]), now),
        )
        conn.execute("UPDATE settings SET contest_shown = contest_shown + 1 WHERE id = 1")
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not skip contest.") from exc
    _advance_pair(conn)


def contest_undo(conn: sqlite3.Connection) -> None:
    match = conn.execute(
        "SELECT * FROM contest_matches ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if match is None:
        raise ServiceError("Nothing to undo.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        winner_id = match["winner_id"]
        if winner_id is not None:
            now = utcnow()
            left_won = int(winner_id) == int(match["left_id"])
            conn.execute(
                """
                UPDATE projects SET elo_rating = ?,
                    matches_played = MAX(0, matches_played - 1),
                    wins = MAX(0, wins - ?), losses = MAX(0, losses - ?),
                    updated_at = ? WHERE id = ?
                """,
                (
                    float(match["left_elo_before"]),
                    1 if left_won else 0,
                    0 if left_won else 1,
                    now,
                    int(match["left_id"]),
                ),
            )
            conn.execute(
                """
                UPDATE projects SET elo_rating = ?,
                    matches_played = MAX(0, matches_played - 1),
                    wins = MAX(0, wins - ?), losses = MAX(0, losses - ?),
                    updated_at = ? WHERE id = ?
                """,
                (
                    float(match["right_elo_before"]),
                    0 if left_won else 1,
                    1 if left_won else 0,
                    now,
                    int(match["right_id"]),
                ),
            )
            conn.execute(
                "UPDATE settings SET contest_decided = MAX(0, contest_decided - 1) WHERE id = 1"
            )
        conn.execute(
            """
            UPDATE settings SET contest_shown = MAX(0, contest_shown - 1),
                contest_left_id = ?, contest_right_id = ?, contest_active = 1
            WHERE id = 1
            """,
            (int(match["left_id"]), int(match["right_id"])),
        )
        conn.execute("DELETE FROM contest_matches WHERE id = ?", (int(match["id"]),))
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not undo contest.") from exc


def contest_last_match(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
         "SELECT * FROM contest_matches ORDER BY id DESC LIMIT 1"
     ).fetchone()
    if row is None:
        return None
    names = names_by_id(conn)
    left_id = int(row["left_id"])
    right_id = int(row["right_id"])
    winner_id = row["winner_id"]
    recap = {
         "left_name": names.get(left_id, "?"),
         "right_name": names.get(right_id, "?"),
         "skipped": winner_id is None,
         "winner_name": names.get(int(winner_id), "?") if winner_id is not None else None,
         "left_delta": None,
         "right_delta": None,
    }
    if winner_id is not None and row["left_elo_after"] is not None:
        recap["left_delta"] = round(
            float(row["left_elo_after"]) - float(row["left_elo_before"]), 1
        )
        recap["right_delta"] = round(
            float(row["right_elo_after"]) - float(row["right_elo_before"]), 1
        )
    return recap


def reset_elo(conn: sqlite3.Connection, confirm: str) -> None:
    if confirm != "yes":
        raise ServiceError("Reset requires confirmation.")
    now = utcnow()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DELETE FROM contest_matches")
    conn.execute(
        """
        UPDATE projects SET elo_rating = ?, matches_played = 0, wins = 0, losses = 0, updated_at = ?
        """,
        (DEFAULT_ELO, now),
    )
    conn.execute(
        """
        UPDATE settings SET contest_active = 0, contest_left_id = NULL, contest_right_id = NULL,
            contest_shown = 0, contest_decided = 0 WHERE id = 1
        """
    )
    conn.execute("COMMIT")


def contest_progress(conn: sqlite3.Connection) -> dict:
    n = conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"]
    total = unique_pair_count(n)
    decided = conn.execute(
        "SELECT COUNT(*) AS n FROM contest_matches WHERE winner_id IS NOT NULL"
    ).fetchone()["n"]
    return {
        "decided": decided,
        "total_pairs": total,
        "percent": 0 if total == 0 else round(100 * decided / total),
    }
