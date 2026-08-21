"""Seed 12 example sub-projects when the database is empty."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SEED_PROJECTS = [
    {
        "name": "Identity & SSO",
        "description": "Single sign-on, roles, and session management for every product surface.",
        "cost_sgd": 18000,
        "outcome": 80,
        "depends_on": [],
    },
    {
        "name": "Billing ledger",
        "description": "Canonical invoices, credits, and tax-ready journal entries.",
        "cost_sgd": 22000,
        "outcome": 70,
        "depends_on": ["Identity & SSO"],
    },
    {
        "name": "Customer portal",
        "description": "Self-serve account home for plans, usage, and support tickets.",
        "cost_sgd": 35000,
        "outcome": 90,
        "depends_on": ["Identity & SSO"],
    },
    {
        "name": "Analytics warehouse",
        "description": "Central event store and modelled marts for product analytics.",
        "cost_sgd": 40000,
        "outcome": 75,
        "depends_on": [],
    },
    {
        "name": "Experiment platform",
        "description": "Feature flags and A/B assignment wired to the warehouse.",
        "cost_sgd": 28000,
        "outcome": 65,
        "depends_on": ["Analytics warehouse"],
    },
    {
        "name": "Mobile app",
        "description": "iOS and Android client for the customer portal.",
        "cost_sgd": 45000,
        "outcome": 85,
        "depends_on": ["Customer portal"],
    },
    {
        "name": "Payments rails",
        "description": "Card and bank collection, retries, and payouts.",
        "cost_sgd": 38000,
        "outcome": 88,
        "depends_on": ["Billing ledger"],
    },
    {
        "name": "Fraud rules",
        "description": "Velocity and device checks on the payments path.",
        "cost_sgd": 20000,
        "outcome": 60,
        "depends_on": ["Payments rails"],
    },
    {
        "name": "Support desk",
        "description": "Agent console tied to customer identities and tickets.",
        "cost_sgd": 15000,
        "outcome": 50,
        "depends_on": ["Customer portal"],
    },
    {
        "name": "Partner API",
        "description": "OAuth-scoped public API for integration partners.",
        "cost_sgd": 26000,
        "outcome": 72,
        "depends_on": ["Identity & SSO"],
    },
    {
        "name": "Data quality",
        "description": "Freshness monitors and schema contracts on warehouse tables.",
        "cost_sgd": 16000,
        "outcome": 55,
        "depends_on": ["Analytics warehouse"],
    },
    {
        "name": "Launch campaign",
        "description": "Paid and lifecycle launch once checkout actually works.",
        "cost_sgd": 12000,
        "outcome": 40,
        "depends_on": ["Customer portal", "Payments rails"],
    },
]


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"]
    if count:
        return
    now = utcnow()
    names_to_id: dict[str, int] = {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        for item in SEED_PROJECTS:
            cur = conn.execute(
                """
                INSERT INTO projects (
                    name, description, cost_sgd, cost_amount, cost_currency,
                    outcome, elo_rating,
                    matches_played, wins, losses, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'SGD', ?, 1500, 0, 0, 0, ?, ?)
                """,
                (
                    item["name"],
                    item["description"],
                    item["cost_sgd"],
                    item["cost_sgd"],
                    item["outcome"],
                    now,
                    now,
                ),
            )
            names_to_id[item["name"]] = int(cur.lastrowid)
        for item in SEED_PROJECTS:
            pid = names_to_id[item["name"]]
            for dep_name in item["depends_on"]:
                conn.execute(
                    "INSERT INTO project_dependencies (project_id, depends_on_id) VALUES (?, ?)",
                    (pid, names_to_id[dep_name]),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
