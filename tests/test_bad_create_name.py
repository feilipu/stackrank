"""Regression: a hostile project name must not 500 or drop the projects table."""

from __future__ import annotations


def test_create_project_with_sql_injection_name_does_not_500_or_drop_table(client, conn):
    payload = {
        "name": "'; DROP TABLE projects;--",
        "description": "injection attempt",
        "cost": "5000",
        "cost_currency": "SGD",
        "outcome": "42",
    }
    resp = client.post("/projects", data=payload, follow_redirects=False)
    assert resp.status_code != 500

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
    ).fetchone()
    assert row is not None, "projects table missing after injection attempt"
