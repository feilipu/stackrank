"""CRUD, settings, pool, contest, and optimize apply."""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque

from stackrank.currency import metric_value, to_sgd
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


def names_by_id(conn: sqlite3.Connection) -> dict[int, str]:
    return {int(r["id"]): r["name"] for r in conn.execute("SELECT id, name FROM projects")}


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


def _validate_project(name: str, cost: float, outcome: float) -> str:
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ServiceError("Name must be 1–80 characters.")
    if cost <= 0:
        raise ServiceError("Cost must be a positive number.")
    if outcome <= 0:
        raise ServiceError("Outcome must be a positive number.")
    return name


def create_project(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    cost: float,
    cost_currency: str,
    outcome: float,
    depends_on: list[int],
) -> int:
    settings = get_settings(conn)
    name = _validate_project(name, cost, outcome)
    cost_sgd = to_sgd(cost, cost_currency, settings["usd_per_sgd"], settings["myr_per_sgd"])
    depends_on = [int(x) for x in depends_on if int(x)]
    if any(d <= 0 for d in depends_on):
        raise ServiceError("Invalid dependency.")
    existing = {int(r["id"]) for r in list_projects(conn)}
    for dep in depends_on:
        if dep not in existing:
            raise ServiceError("Dependency must be an existing project.")
    if conn.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone():
        raise ServiceError("A project with that name already exists.")
    now = utcnow()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """
            INSERT INTO projects (
                name, description, cost_sgd, outcome, elo_rating,
                matches_played, wins, losses, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1500, 0, 0, 0, ?, ?)
            """,
            (name, (description or "").strip(), cost_sgd, outcome, now, now),
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
    cost: float,
    cost_currency: str,
    outcome: float,
    depends_on: list[int],
) -> None:
    if get_project(conn, project_id) is None:
        raise ServiceError("Project not found.", 404)
    settings = get_settings(conn)
    name = _validate_project(name, cost, outcome)
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
    now = utcnow()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, cost_sgd = ?, outcome = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, (description or "").strip(), cost_sgd, outcome, now, project_id),
        )
        conn.execute("DELETE FROM project_dependencies WHERE project_id = ?", (project_id,))
        for dep in depends_on:
            conn.execute(
                "INSERT INTO project_dependencies (project_id, depends_on_id) VALUES (?, ?)",
                (project_id, dep),
            )
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise


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


def update_budget(conn: sqlite3.Connection, amount: float, currency: str) -> None:
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
        conn.execute("COMMIT")
    except ServiceError:
        conn.execute("ROLLBACK")
        raise
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        raise ServiceError("Could not update budget.") from exc


def update_rates(conn: sqlite3.Connection, usd_per_sgd: float, myr_per_sgd: float) -> None:
    if usd_per_sgd <= 0 or myr_per_sgd <= 0:
        raise ServiceError("Conversion rates must be positive.")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE settings SET usd_per_sgd = ?, myr_per_sgd = ? WHERE id = 1",
            (usd_per_sgd, myr_per_sgd),
        )
        conn.execute("COMMIT")
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


def add_to_pool(conn: sqlite3.Connection, project_id: int) -> None:
    project = get_project(conn, project_id)
    if project is None:
        raise ServiceError("Project not found.", 404)
    settings = get_settings(conn)
    deps = dependencies_map(conn)
    current = pool_rows(conn)
    current_ids = [int(r["id"]) for r in current]
    if project_id in current_ids:
        return
    missing = [d for d in _transitive_deps(project_id, deps) if d not in current_ids]
    if missing:
        names = names_by_id(conn)
        label = ", ".join(names[i] for i in missing)
        raise ServiceError(f"Missing dependencies in the pool: {label}.", 409)

    by_id = {int(r["id"]): r for r in list_projects(conn)}
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

    ejected: list[int] = []
    while total(members) > budget + EPS:
        candidates = [m for m in members if m["id"] != project_id and not m["pinned"]]
        if not candidates:
            raise ServiceError(
                "Does not fit even after ejecting unpinned projects.",
                409,
            )
        victim = min(candidates, key=lambda m: (m["value"], -m["position"], -m["id"]))
        members = [m for m in members if m["id"] != victim["id"]]
        ejected.append(victim["id"])

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
    )


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
