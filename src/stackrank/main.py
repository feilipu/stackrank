"""FastAPI app for Project Stack Ranker (routes in docs/03).

The only runtime state that is not persisted -- the most recent optimizer run --
lives at module level (`LAST_OPTIMIZE`), per the "module global is fine" note.

User-input validation never produces a 500: `ServiceError` from the service layer
is mapped globally to an HTML fragment that HTMX retargets into `#flash`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from stackrank import currency as cur
from stackrank import services
from stackrank.db import apply_schema, connect, ensure_seeded, resolve_db_path

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stackrank.main")

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

# --- Runtime state (memory only) ------------------------------------------
LAST_OPTIMIZE: dict | None = None          # most recent optimizer run, in app memory
_DB_PATH_OVERRIDE: str | Path | None = None  # tests point requests at a tmp DB


def active_db_path() -> str:
    """DB path per request: test override > STACKRANK_DB env > default file."""
    if _DB_PATH_OVERRIDE is not None:
        return resolve_db_path(_DB_PATH_OVERRIDE)
    return resolve_db_path(None)


def set_db_path(path: "str | Path | None") -> None:
    """Override the DB path used by every request (used by tests)."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path


@contextmanager
def get_conn():
    """Yield a write-ready connection; schema + seed run first so reads are safe."""
    conn = connect(active_db_path())
    try:
        apply_schema(conn)                 # idempotent; also inserts settings singleton
        ensure_seeded(conn)                # 12 example projects when the DB is empty
        yield conn
    finally:
        conn.close()


def _bootstrap(db_path) -> None:
    """Create + seed-on-empty at boot (a per-request get_conn re-seeds too)."""
    try:
        conn = connect(db_path)
        apply_schema(conn)
        ensure_seeded(conn)
        conn.close()
    except Exception:                      # pragma: no cover - startup best-effort
        log.exception("db bootstrap failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _bootstrap(active_db_path())
    yield


app = FastAPI(title="Project Stack Ranker", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    currencies=list(cur.CURRENCIES),
    symbols=dict(cur.SYMBOLS),
    format_money=cur.format_money,
    format_triple=cur.format_triple,
    metric_label=lambda m: {
        "outcome": "Outcome",
        "elo": "Elo",
        "blend": "Blended",
    }.get(m or "outcome", "Blended"),
)




def render_partial(name: str, context: dict) -> str:
    """Render an HTMX fragment to a string (Jinja2Templates has no batch API)."""
    return templates.get_template(name).render(context)


# --- Input coercion --------------------------------------------------------

def to_number(value, *, field: str) -> float:
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError):
        raise services.ServiceError(f"{field} must be a positive number.")
    if num <= 0:
        raise services.ServiceError(f"{field} must be positive.")
    return num


def to_id_list(items) -> list[int]:
    out: list[int] = []
    for raw in items or []:
        try:
            num = int(str(raw).strip())
        except (TypeError, ValueError):
            raise services.ServiceError("Invalid dependency selection.")
        if num > 0 and num not in out:
            out.append(num)
    return out


def project_payload(form_data: dict) -> dict:
    """Build a service kwargs dict from raw form fields (numbers validated here)."""
    cost = form_data.get("cost") or ""
    outcome = form_data.get("outcome") or ""
    depends_on = form_data.get("depends_on") or []
    return {
        "name": str(form_data.get("name") or "").strip(),
        "description": str(form_data.get("description") or "").strip(),
        "cost": to_number(cost, field="Cost"),
        "cost_currency": str(form_data.get("cost_currency") or "SGD").upper(),
        "outcome": to_number(outcome, field="Outcome"),
        "depends_on": to_id_list([str(x) for x in depends_on]),
    }


async def read_body(request: Request) -> dict:
    """Parse a urlencoded/multipart body; repeated keys become lists (absent -> {})."""
    try:
        form = await request.form()
    except Exception:                      # pragma: no cover - empty body tolerated
        return {}
    data: dict = {}
    for key in form.multi_items():
        name, value = key[0], key[1]
        if name in data and isinstance(data[name], list):
            data[name].append(value)
        elif name in data:
            data[name] = [data[name], value]
        else:
            data[name] = value
    return data


# --- Error policy (docs/03) ------------------------------------------------

@app.exception_handler(services.ServiceError)
async def handle_service_error(request: Request, exc: services.ServiceError):
    """Readable fragment; 422/409 land in the #flash region via HX-Retarget."""
    status = getattr(exc, "status_code", 422) or 422
    body = templates.get_template("_partials/errors.html").render({"message": str(exc.message)})
    headers: dict[str, str] = {}
    if status in (409, 422):              # user validation failures retarget the flash
        headers["HX-Retarget"] = "#flash"
    log.info("validation error (%s): %s", status, exc.message)
    return HTMLResponse(body, status_code=status, headers=headers or None)


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    """Never 500 in the UI -- show a friendy fragment; log full detail server-side."""
    log.exception("unexpected error handled by request", exc_info=exc)
    body = templates.get_template("_partials/errors.html").render({"message": "Something went wrong. See the server logs."})
    return HTMLResponse(body, status_code=503, headers={"HX-Retarget": "#flash"})


# --- HTMX detection --------------------------------------------------------

@app.middleware("http")
async def mark_hx(request: Request, call_next):
    request.state.is_hx = request.headers.get("HX-Request", "").lower() == "true"
    return await call_next(request)


# --- Context builders ------------------------------------------------------

def _money(sgd: float, settings) -> dict:
    """Three-currency triple for a stored SGD amount using the configured rates."""
    return cur.format_triple(float(sgd), settings["usd_per_sgd"], settings["myr_per_sgd"])


def _project_name(settings) -> str:
    """Parent title; tolerant of pre-migration rows missing the column."""
    if settings is None:
        return "Untitled project"
    try:
        name = settings["project_name"]
    except (IndexError, KeyError):
        return "Untitled project"
    return name or "Untitled project"


def sgd_display(sgd: float, code: str, usd: float, myr: float) -> float:
    """Re-express a stored SGD amount in the currency it was last typed in."""
    code = (code or "SGD").upper()
    if code == "USD":
        return cur.to_usd(sgd, usd)
    if code == "MYR":
        return cur.to_myr(sgd, myr)
    return sgd


def project_context(conn, *, page: str | None = "projects") -> dict:
    settings = services.get_settings(conn)
    usd, myr = settings["usd_per_sgd"], settings["myr_per_sgd"]
    budget_currency = str(settings["budget_currency"]).upper()
    pool_ids = {int(r["id"]) for r in services.pool_rows(conn)}
    names = services.names_by_id(conn)
    deps_map = services.dependencies_map(conn)

    rows: list[dict] = []
    for row in services.list_projects(conn):
        pid = int(row["id"])
        rows.append(
            {
                "id": pid,
                "name": row["name"],
                "description": row["description"] or "",
                "cost_sgd": float(row["cost_sgd"]),
                "cost": _money(float(row["cost_sgd"]), settings),
                "outcome": float(row["outcome"]),
                "elo_rating": round(float(row["elo_rating"])),
                "matches_played": int(row["matches_played"]),
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "in_pool": pid in pool_ids,
                "dependencies": [names.get(d, "?") for d in deps_map.get(pid, [])],
            }
        )

    return {
        "page": page,
        "settings": settings,
        "project_name": _project_name(settings),
        "rows": rows,
        "project_options": [{"id": int(r["id"]), "name": r["name"]}
                            for r in services.list_projects(conn)],
        "budget_amount": round(
            sgd_display(float(settings["budget_sgd"]), budget_currency, usd, myr)
        ),
        "budget_currency": budget_currency,
        "triple": _money(float(settings["budget_sgd"]), settings),
        "budget_triple": _money(float(settings["budget_sgd"]), settings)["text"],
        "currencies": cur.CURRENCIES,
        "symbols": cur.SYMBOLS,
        "usd_per_sgd": usd,
        "myr_per_sgd": myr,
    }


def pool_context(conn, *, page: str | None = "pool") -> dict:
    settings = services.get_settings(conn)
    all_rows = list(services.list_projects(conn))
    in_pool = list(services.pool_rows(conn))
    pool_ids = {int(r["id"]) for r in in_pool}

    def decorate(row):
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "description": row["description"] or "",
            "cost_sgd": float(row["cost_sgd"]),
            "cost": _money(float(row["cost_sgd"]), settings),
            "outcome": float(row["outcome"]),
            "elo_rating": round(float(row["elo_rating"])),
            "pinned": bool(int(row["pinned"])) if "pinned" in row.keys() else False,
        }

    pool_items = [decorate(dict(r)) for r in in_pool]
    available = [decorate(dict(r)) for r in all_rows if int(r["id"]) not in pool_ids]

    cost_sgd = sum(float(r["cost_sgd"]) for r in in_pool)
    budget_sgd = float(settings["budget_sgd"])
    remaining = budget_sgd - cost_sgd
    totals = {
        "count": len(pool_items),
        "cost": _money(cost_sgd, settings),
        "remaining_sgd": max(remaining, 0.0),
        "remaining": _money(max(remaining, 0.0), settings),
        "over_budget": remaining < -1e-9,
        "outcome": round(sum(float(r["outcome"]) for r in in_pool), 1),
        "elo": round(sum(float(r["elo_rating"]) for r in in_pool), 1),
    }
    return {
        "page": page,
        "settings": settings,
        "project_name": _project_name(settings),
        "available": available,
        "pool_items": pool_items,
        "totals": totals,
        "budget_sgd": budget_sgd,
        "triple": _money(budget_sgd, settings),
        "budget_triple": _money(budget_sgd, settings)["text"],
        "pool_metric": str(settings["pool_eject_metric"]).lower(),
        "currencies": cur.CURRENCIES,
        "symbols": cur.SYMBOLS,
    }


def optimize_context(conn, *, page: str | None = "optimize") -> dict:
    settings = services.get_settings(conn)
    last = dict(LAST_OPTIMIZE or {}) if LAST_OPTIMIZE else {}
    return {
        "page": page,
        "settings": settings,
        "project_name": _project_name(settings),
        "metric": str(settings["optimize_metric"]).lower(),
        "last": last,
        "has_result": LAST_OPTIMIZE is not None,
        "triple": cur.format_triple(
            float(settings["budget_sgd"]), settings["usd_per_sgd"], settings["myr_per_sgd"]
        ),
        "budget_triple": cur.format_money(
            float(settings["budget_sgd"]), settings["usd_per_sgd"], settings["myr_per_sgd"]
        ),
        "currencies": cur.CURRENCIES,
        "symbols": cur.SYMBOLS,
    }


def contest_context(conn, *, page: str | None = "contest") -> dict:
    settings = services.get_settings(conn)
    usd, myr = settings["usd_per_sgd"], settings["myr_per_sgd"]
    by_id = {int(p["id"]): p for p in services.list_projects(conn)}
    active = bool(settings["contest_active"]) and settings["contest_left_id"] is not None

    def card(pid) -> dict | None:
        row = by_id.get(int(pid)) if pid else None
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "description": row["description"] or "",
            "cost_sgd": float(row["cost_sgd"]),
            "cost": _money(float(row["cost_sgd"]), settings),
            "outcome": float(row["outcome"]),
            "elo_rating": round(float(row["elo_rating"]), 1),
            "matches_played": int(row["matches_played"]),
            "wins": int(row["wins"]),
            "losses": int(row["losses"]),
        }

    leaderboard = sorted(
        [
            {
                "id": int(p["id"]),
                "name": p["name"],
                "elo_rating": round(float(p["elo_rating"]), 1),
                "matches_played": int(p["matches_played"]),
                "wins": int(p["wins"]),
                "losses": int(p["losses"]),
            }
            for p in by_id.values()
        ],
        key=lambda d: (-d["elo_rating"], d["name"].lower()),
    )
    return {
        "page": page,
        "settings": settings,
        "project_name": _project_name(settings),
        "active": active,
        "left": card(settings["contest_left_id"]),
        "right": card(settings["contest_right_id"]),
        "leaderboard": leaderboard,
        "progress": services.contest_progress(conn),
        "triple": cur.format_triple(float(settings["budget_sgd"]), usd, myr),
        "budget_triple": cur.format_money(float(settings["budget_sgd"]), usd, myr),
        "currencies": cur.CURRENCIES,
        "symbols": cur.SYMBOLS,
    }


def build_optimize_result(conn, metric: str | None = None) -> dict:
    """Run the optimizer and remember it at module level, with currency triples."""
    global LAST_OPTIMIZE
    raw = services.optimize_now(conn, metric or None)
    settings = services.get_settings(conn)
    by_id = {int(p["id"]): p for p in services.list_projects(conn)}

    def to_item(pid: int) -> dict:
        p = by_id[int(pid)]
        return {
            "id": int(pid),
            "name": p["name"],
            "cost_sgd": float(p["cost_sgd"]),
            "cost": _money(float(p["cost_sgd"]), settings),
            "outcome": float(p["outcome"]),
            "elo_rating": round(float(p["elo_rating"])),
        }

    result = dict(raw)
    result["selected_items"] = [to_item(pid) for pid in raw.get("selected", [])]
    result["excluded_items"] = [to_item(pid) for pid in raw.get("excluded", [])]
    result["total_cost_money"] = _money(float(result["total_cost_sgd"]), settings)
    result["remaining_money"] = _money(float(result["remaining_sgd"]), settings)
    LAST_OPTIMIZE = result
    return result


def project_list_html() -> str:
    """Render the #project-list fragment (swapped after create/update/delete)."""
    with get_conn() as conn:
        ctx = project_context(conn, page=None)
        return render_partial("_partials/project_list.html", dict(ctx))


# --- Routes ----------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Landing page redirects to the projects tab."""
    return RedirectResponse(url="/projects", status_code=307)


@app.get("/export.md")
@app.get("/export")
def export_markdown() -> PlainTextResponse:
    """Download a markdown document of the overall project and every sub-project."""
    with get_conn() as conn:
        body = services.export_markdown(conn)
        filename = services.export_filename(conn)
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---- Projects --------------------------------------------------------------

@app.get("/projects")
def projects_page(request: Request):
    with get_conn() as conn:
        ctx = project_context(conn, page="projects")
    return templates.TemplateResponse(request, "projects.html", dict(ctx, flash=None))


@app.post("/projects")
async def create_project(request: Request):
    data = await read_body(request)
    with get_conn() as conn:
        services.create_project(conn, **project_payload(data))
    if getattr(request.state, "is_hx", False):
        return HTMLResponse(project_list_html(), headers={"HX-Trigger": "list-refreshed"})
    return RedirectResponse(url="/projects", status_code=303)


@app.get("/projects/{project_id}/edit")
def project_edit_form(request: Request, project_id: int):
    with get_conn() as conn:
        row = services.get_project(conn, project_id)
        if row is None:
            raise services.ServiceError("Project not found.", 404)
        ctx = project_context(conn, page=None)
        selected = [int(d) for d in services.dependencies_map(conn).get(project_id, [])]
    return templates.TemplateResponse(
         request,
"_partials/project_edit.html",
          dict(ctx, editing=project_id,
             cost_sgd=round(float(row["cost_sgd"]), 2),
             name=row["name"], description=row["description"] or "",
             outcome=float(row["outcome"]), selected=selected, flash=None)
         )


@app.post("/projects/{project_id}")
async def update_project(request: Request, project_id: int):
    data = await read_body(request)
    with get_conn() as conn:
        services.update_project(conn, project_id, **project_payload(data))
    return HTMLResponse(project_list_html())


@app.post("/projects/{project_id}/delete")
async def delete_project(project_id: int, request: Request):
    with get_conn() as conn:
        services.delete_project(conn, project_id)
    if getattr(request.state, "is_hx", False):
        return HTMLResponse(project_list_html(), headers={"HX-Trigger": "list-refreshed"})
    return RedirectResponse(url="/projects", status_code=303)


# ---- Settings ---------------------------------------------------------------

@app.post("/settings/budget")
async def set_budget(request: Request, amount: str = Form(""), currency: str = Form("SGD")) -> HTMLResponse:
    value = to_number(amount if amount else "0", field="Budget")
    with get_conn() as conn:
        services.update_budget(conn, value, (currency or "SGD").upper())
        ctx = project_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/budget_card.html", dict(ctx, flash=None)))


@app.post("/settings/rates")
async def set_rates(request: Request, usd_per_sgd: str = Form("0"), myr_per_sgd: str = Form("0")) -> HTMLResponse:
    usd = to_number(usd_per_sgd if usd_per_sgd else "0", field="USD per SGD")
    myr = to_number(myr_per_sgd if myr_per_sgd else "0", field="MYR per SGD")
    with get_conn() as conn:
        services.update_rates(conn, usd, myr)
        ctx = project_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/budget_card.html", dict(ctx, flash=None)))


@app.post("/settings/name")
async def set_name(request: Request, name: str = Form("")) -> HTMLResponse:
    with get_conn() as conn:
        services.update_project_name(conn, name)
        ctx = project_context(conn, page=None)
    if getattr(request.state, "is_hx", False):
        return HTMLResponse(render_partial("_partials/header_title.html", dict(ctx, flash=None)))
    return RedirectResponse(url="/projects", status_code=303)


# ---- Optimize --------------------------------------------------------------

@app.get("/optimize")
def optimize_page(request: Request):
    with get_conn() as conn:
        if request.query_params.get("autorun"):
            build_optimize_result(conn, None)
        ctx = optimize_context(conn, page="optimize")
    return templates.TemplateResponse(request, "optimize.html", dict(ctx, flash=None))


@app.post("/optimize/run")
async def optimize_run(metric: str = Form(""), request: Request = None) -> HTMLResponse:
    metric_norm = "outcome" if metric not in ("outcome", "elo", "blend") else metric
    with get_conn() as conn:
        services.set_optimize_metric(conn, metric_norm)
        build_optimize_result(conn, metric_norm)
        ctx = optimize_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/optimize_results.html", dict(ctx, flash=None)))


@app.post("/optimize/apply")
async def optimize_apply(request: Request, selected: list[str] | None = Form(None)) -> HTMLResponse:
    with get_conn() as conn:
        ids = to_id_list([str(x) for x in (selected or [])])
        if not ids and LAST_OPTIMIZE is not None:
            ids = [int(x) for x in LAST_OPTIMIZE.get("selected", [])]
        services.apply_optimize_to_pool(conn, ids)
    note = (
         f'<div id="applied-note" class="alert alert-ok">Selection applied to the '
         f'In-Budget Success Pool ({len(ids)} project{"s" if len(ids) != 1 else ""}).</div>'
     )
    return HTMLResponse(note, headers={"HX-Trigger": "opt-applied"})


# ---- Pool ------------------------------------------------------------------

@app.get("/pool")
def pool_page(request: Request):
    with get_conn() as conn:
        ctx = pool_context(conn, page="pool")
    return templates.TemplateResponse(request, "pool.html", dict(ctx, flash=None))


@app.post("/pool/add/{project_id}")
async def pool_add(project_id: int) -> HTMLResponse:
    with get_conn() as conn:
        services.add_to_pool(conn, project_id)
        ctx = pool_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/pool_board.html", dict(ctx, flash=None)))


@app.post("/pool/remove/{project_id}")
async def pool_remove(project_id: int) -> HTMLResponse:
    with get_conn() as conn:
        services.remove_from_pool(conn, project_id)
        ctx = pool_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/pool_board.html", dict(ctx, flash=None)))


@app.post("/pool/reorder")
async def pool_reorder(ids: list[str] | None = Form(None)) -> HTMLResponse:
    ordered = to_id_list([str(x) for x in (ids or [])])
    with get_conn() as conn:
        services.reorder_pool(conn, ordered)
        ctx = pool_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/pool_board.html", dict(ctx, flash=None)))


@app.post("/pool/pin/{project_id}")
async def pool_pin(project_id: int) -> HTMLResponse:
    with get_conn() as conn:
        services.toggle_pin(conn, project_id)
        ctx = pool_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/pool_board.html", dict(ctx, flash=None)))


@app.post("/settings/pool-metric")
async def set_pool_metric(metric: str = Form("elo")) -> HTMLResponse:
    metric_norm = "elo" if metric not in ("outcome", "elo", "blend") else metric
    with get_conn() as conn:
        services.set_pool_metric(conn, metric_norm)
        ctx = pool_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/pool_board.html", dict(ctx, flash=None)))


# ---- Contest ---------------------------------------------------------------

@app.get("/contest")
def contest_page(request: Request):
    with get_conn() as conn:
        ctx = contest_context(conn, page="contest")
    return templates.TemplateResponse(request, "contest.html", dict(ctx, flash=None))


@app.post("/contest/start")
async def contest_start() -> HTMLResponse:
    with get_conn() as conn:
        services.start_contest(conn)
        ctx = contest_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/contest_board.html", dict(ctx, flash=None)))


@app.post("/contest/choose")
async def contest_choose(winner_id: str = Form("")) -> HTMLResponse:
    try:
        winner = int(str(winner_id).strip())
    except (TypeError, ValueError):
        raise services.ServiceError("Choose project A or B to decide the pair.", 422)
    with get_conn() as conn:
        services.contest_choose(conn, winner)
        ctx = contest_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/contest_board.html", dict(ctx, flash=None)))


@app.post("/contest/skip")
async def contest_skip() -> HTMLResponse:
    with get_conn() as conn:
        settings = services.get_settings(conn)
        if settings["contest_active"] and settings["contest_left_id"] is not None:
            services.contest_skip(conn)     # skip the current pair, advance to next
        ctx = contest_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/contest_board.html", dict(ctx, flash=None)))


@app.post("/contest/stop")
async def contest_stop() -> HTMLResponse:
    with get_conn() as conn:
        services.stop_contest(conn)
        ctx = contest_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/contest_board.html", dict(ctx, flash=None)))


@app.post("/contest/reset")
async def contest_reset(confirm: str = Form("no")) -> HTMLResponse:
    if str(confirm or "no").lower() != "yes":
        raise services.ServiceError("Reset clears all Elo. Confirm to proceed.", 422)
    with get_conn() as conn:
        services.reset_elo(conn, "yes")
        ctx = contest_context(conn, page=None)
    return HTMLResponse(render_partial("_partials/contest_board.html", dict(ctx, flash=None)))

