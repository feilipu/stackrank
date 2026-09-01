def test_bad_budget_sql(client, conn):
    r = client.post("/settings/budget", data={"amount": "1; DROP TABLE projects;--", "currency": "SGD"}, follow_redirects=False)
    assert r.status_code != 500
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects'").fetchone() is not None