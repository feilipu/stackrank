"""Unit tests for Elo scoring (docs/05-testing.md: Unit - Elo)."""

from __future__ import annotations

from stackrank.elo import K_FACTOR, expected, update_ratings


def test_equal_rating_winner_gives_expected_delta():
    new_a, new_b = update_ratings(1500, 1500, 1.0)
    assert round(new_a - 1500) == 16
    assert round(new_b - 1500) == -16
    assert K_FACTOR == 32


def test_expected_elo_matches_closed_form():
    a = expected(1500, 1700)
    closed = 1 / (1 + 10 ** (200 / 400))
    assert abs(a - closed) < 1e-9


def test_skip_does_not_change_ratings_or_records(conn):
    from stackrank.services import contest_skip, create_project, start_contest

    p_a = _mk(conn, "Alpha", cost=500, outcome=60.0)
    p_b = _mk(conn, "Beta", cost=500, outcome=40.0)
    before = {pid: _row_stat(conn, pid) for pid in (p_a, p_b)}

    start_contest(conn)
    contest_skip(conn)

    for pid, snapshot in before.items():
        assert _row_stat(conn, pid) == snapshot


def test_reset_elo_restores_baseline(conn):
    from stackrank.services import contest_choose, create_project, reset_elo, start_contest

    p_a = _mk(conn, "Alpha", cost=500, outcome=60.0)
    p_b = _mk(conn, "Beta", cost=500, outcome=40.0)

    start_contest(conn)
    contest_choose(conn, p_a)

    moved = (
        conn.execute("SELECT COUNT(*) AS n FROM projects WHERE elo_rating <> 1500").fetchone()["n"]
        + conn.execute("SELECT COUNT(*) AS n FROM projects WHERE wins > 0 OR losses > 0").fetchone()["n"]
    )
    assert moved > 0, "a decided match should move at least one rating or W-L"

    reset_elo(conn, "yes")
    for row in conn.execute("SELECT elo_rating, matches_played, wins, losses FROM projects"):
        assert int(row["elo_rating"]) == 1500
        assert int(row["matches_played"]) == 0
        assert int(row["wins"]) == 0
        assert int(row["losses"]) == 0


def _mk(conn, name, *, cost, outcome):
    from stackrank.services import create_project

    return create_project(
        conn,
        name=name,
        description="",
        cost=cost,
        cost_currency="SGD",
        outcome=outcome,
        depends_on=[],
    )


def _row_stat(conn, pid):
    row = conn.execute("SELECT elo_rating, wins, losses FROM projects WHERE id = ?", (pid,)).fetchone()
    return (int(row["elo_rating"]), int(row["wins"]), int(row["losses"]))
