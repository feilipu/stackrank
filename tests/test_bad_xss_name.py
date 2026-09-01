def test_bad_xss_name(client):
    """XSS-looking project name must not 500; GET /projects must not echo a live script tag."""
    payload = {
        "name": "<script>alert(1)</script>",
        "description": "XSS test project",
        "cost": "5000",
        "cost_currency": "SGD",
        "outcome": "42",
    }
    resp = client.post("/projects", data=payload, follow_redirects=False)
    assert resp.status_code != 500, f"POST /projects returned 500 for XSS payload: {resp.text}"

    get_resp = client.get("/projects")
    assert get_resp.status_code == 200, f"GET /projects failed after XSS POST: {get_resp.status_code}"
    assert "<script>alert(1)</script>" not in get_resp.text, (
        "Raw script tag found in GET /projects response"
    )
