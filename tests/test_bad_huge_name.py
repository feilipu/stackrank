def test_create_project_with_huge_name(client):
    """POST /projects with a 10k-char name must not return 500."""
    payload = {
        "name": "A" * 10000,
        "description": "huge name test",
        "cost": "1000",
        "cost_currency": "SGD",
        "outcome": "50",
    }
    resp = client.post("/projects", data=payload, follow_redirects=False)
    assert resp.status_code != 500, (
        f"Expected no 500 error, but got {resp.status_code}. Response: {resp.text[:500]}"
    )
