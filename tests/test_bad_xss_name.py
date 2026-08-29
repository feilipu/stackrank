from pytest import fail
from tests.conftest import client, conn

def test_bad_xss_name(client):
    """
    Verify that a project name containing a script tag does not result in a 500 error
    and is properly escaped when retrieved via GET /projects.
    """
    payload = {
        "name": "<script>alert(1)</script>",
        "description": "XSS test project",
        "cost": "5000",
        "cost_currency": "SGD",
        "outcome": "42",
    }
    
    # 1. POST /projects
    # If create is rejected as invalid (422), that is a pass as long as status is not 500.
    # If create succeeds (303), the GET check still applies.
    resp = client.post("/projects", data=payload, follow_redirects=False)
    
    if resp.status_code == 500:
        fail(f"POST /projects returned 500 for XSS payload: {resp.text}")
    
    # 2. GET /projects and assert the response does not contain the raw string "<script>alert(1)</script>"
    # We need to check if the project was actually created or if it was rejected.
    # If it was rejected (e.g. 422), we still want to ensure the GET /projects doesn't crash.
    
    get_resp = client.get("/projects")
    assert get_resp.status_code == 200, f"GET /projects failed after XSS POST: {get_resp.status_code}"
    
    # The raw string should NOT be in the HTML. It should be escaped by Jinja.
    assert "<script>alert(1)</script>" not in get_resp.text, (
        f"XSS vulnerability detected! Raw script tag found in GET /projects response: {get_resp.text[:500]}"
    )
