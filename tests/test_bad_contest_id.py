import pytest


def test_bad_contest_id(client, conn):
    response = client.post("/contest/choose", data={"winner_id": "1; DROP TABLE projects;--"})
    assert response.status_code != 500

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects';")
    result = cursor.fetchone()
    assert result is not None