"""POST /projects with a negative cost must not 500."""

from __future__ import annotations


def test_create_project_with_negative_cost_does_not_500(client):
    payload = {
        "name": "Bad-Cost-Proj",
        "description": "created by pytest",
        "cost": "-1",
        "cost_currency": "SGD",
        "outcome": "42",
    }
    resp = client.post("/projects", data=payload, follow_redirects=False)
    assert resp.status_code != 500
