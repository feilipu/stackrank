"""SQLite connection, schema, and seed hook."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Repo-local default so a zip + ./run.sh just works. A later Mac .app should
# store this under ~/Library/Application Support/StackRanker/ instead.
DEFAULT_DB = ROOT / "data" / "stackrank.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    project_name TEXT NOT NULL DEFAULT 'Untitled project',
    budget_sgd REAL NOT NULL,
    budget_currency TEXT NOT NULL,
    usd_per_sgd REAL NOT NULL,
    myr_per_sgd REAL NOT NULL,
    optimize_metric TEXT NOT NULL,
    pool_eject_metric TEXT NOT NULL,
    contest_active INTEGER NOT NULL,
    contest_left_id INTEGER,
    contest_right_id INTEGER,
    contest_shown INTEGER NOT NULL,
    contest_decided INTEGER NOT NULL,
    last_optimize_json TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    cost_sgd REAL NOT NULL,
    cost_amount REAL NOT NULL,
    cost_currency TEXT NOT NULL DEFAULT 'SGD',
    outcome REAL NOT NULL,
    elo_rating REAL NOT NULL DEFAULT 1500,
    matches_played INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_dependencies (
    project_id INTEGER NOT NULL,
    depends_on_id INTEGER NOT NULL,
    PRIMARY KEY (project_id, depends_on_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_exclusions (
    project_id INTEGER NOT NULL,
    excludes_id INTEGER NOT NULL,
    PRIMARY KEY (project_id, excludes_id),
    CHECK (project_id != excludes_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (excludes_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pool_items (
    project_id INTEGER PRIMARY KEY,
    position INTEGER NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contest_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    left_id INTEGER NOT NULL,
    right_id INTEGER NOT NULL,
    winner_id INTEGER,
    k_factor REAL NOT NULL,
    left_elo_before REAL,
    right_elo_before REAL,
    left_elo_after REAL,
    right_elo_after REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (left_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (right_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""


def resolve_db_path(path: str | os.PathLike | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("STACKRANK_DB")
    if env:
        return Path(env)
    return DEFAULT_DB


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)")}
    if "project_name" not in cols:
        conn.execute(
            "ALTER TABLE settings ADD COLUMN project_name "
            "TEXT NOT NULL DEFAULT 'Untitled project'"
        )
    if "last_optimize_json" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN last_optimize_json TEXT")
    proj_cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "notes" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
    if "cost_currency" not in proj_cols:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN cost_currency "
            "TEXT NOT NULL DEFAULT 'SGD'"
        )
    if "cost_amount" not in proj_cols:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN cost_amount REAL NOT NULL DEFAULT 0"
        )
        conn.execute("UPDATE projects SET cost_amount = cost_sgd")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)")}
    if "last_cost_currency" not in cols:
        conn.execute(
             "ALTER TABLE settings ADD COLUMN last_cost_currency "
             "TEXT NOT NULL DEFAULT 'SGD'"
         )
    if "theme" not in cols:
        conn.execute(
             "ALTER TABLE settings ADD COLUMN theme "
             "TEXT NOT NULL DEFAULT 'system'"
         )
    _mirror_exclusion_pairs(conn)
    row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO settings (
                id, budget_sgd, budget_currency, usd_per_sgd, myr_per_sgd,
                optimize_metric, pool_eject_metric, contest_active,
                contest_left_id, contest_right_id, contest_shown, contest_decided
            ) VALUES (1, 250000, 'SGD', 0.74, 3.45, 'outcome', 'elo', 0, NULL, NULL, 0, 0)
            """
        )


def _mirror_exclusion_pairs(conn: sqlite3.Connection) -> None:
    """If A excludes B, persist B excludes A as well."""
    rows = list(conn.execute("SELECT project_id, excludes_id FROM project_exclusions"))
    have = {(int(r["project_id"]), int(r["excludes_id"])) for r in rows}
    for a, b in list(have):
        if a == b or (b, a) in have:
            continue
        conn.execute(
            "INSERT INTO project_exclusions (project_id, excludes_id) VALUES (?, ?)",
            (b, a),
        )
        have.add((b, a))


def ensure_seeded(conn: sqlite3.Connection) -> None:
    from stackrank.seed import seed_if_empty

    seed_if_empty(conn)


@contextmanager
def get_db(path: str | os.PathLike | None = None):
    conn = connect(path)
    try:
        apply_schema(conn)
        ensure_seeded(conn)
        yield conn
    finally:
        conn.close()
