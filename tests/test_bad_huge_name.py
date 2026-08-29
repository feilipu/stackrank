from tests.conftest import client

def test_create_project_with_huge_name(client):
    """
    POST /projects with a name consisting of 10,000 'A's.
    Expect not to return a 500 error.
    """
    huge_name = "A" * 10000
    payload = {
        "name": huge_name,
        "description": "huge name test",
        "cost": "1000",
        "cost_currency": "SGD",
        "outcome": "50",
    }
    
    resp = client.post("/projects", data=payload, follow_redirects=False)
    
    # If it's rejected (4xx), that's fine. If it's accepted (303), that's fine.
    # The only failure is a 500.
    assert resp.status_code != 500, f"Expected no 500 error, but got {resp.status_code}. Response: {resp.text[:500]}"
