from __future__ import annotations

import pytest


def test_create_project_with_empty_name_is_not_500(client):
    """POST /projects with name="" should not return 500."""
    payload = {
        "name": "",
        "description": "test empty name",
        "cost": "1000",
        "cost_currency": "SGD",
        "outcome": "10",
    }
    resp = client.post("/projects", data=payload, follow_redirects=False)
    
    # The requirement says: "If the empty name is rejected as invalid, that is a pass as long as status is not 500."
    assert resp.status_code != 500, f"Expected status not 500, but got {resp.status_code}. Response: {resp.text}"
