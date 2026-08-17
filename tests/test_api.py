"""API / HTML smoke tests for stackrank.main (docs/05-testing.md, API section)."""

from __future__ import annotations

import re


def _row_stat(conn, pid):
    row = conn.execute(
        "SELECT elo_rating, matches_played FROM projects WHERE id=?",
        (pid,),
    ).fetchone()
    return int(row["elo_rating"]), int(row["matches_played"])


def test_projects_page_returns_ok_and_shows_seed_name(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    # Jinja escapes "&" in "Identity & SSO" as &amp; in HTML.
    assert "Identity" in resp.text and "SSO" in resp.text, f"seed missing: {resp.text[:500]!r}"


def test_create_project_persists_and_duplicate_is_rejected(client):
    payload = {
        "name": "API-Smoke-Proj",
        "description": "created by pytest",
        "cost": "5000",
        "cost_currency": "SGD",
        "outcome": "42",
    }
    first = client.post("/projects", data=payload, follow_redirects=False)
    assert first.status_code == 303

    second = client.post("/projects", data=payload, follow_redirects=False)
    assert second.status_code == 422


def test_optimize_run_emits_selected_and_excluded_markup(client):
    resp = client.post(
        "/optimize/run", data={"metric": "outcome"}, follow_redirects=False
    )
    assert resp.status_code == 200
    assert 'id="opt-selected"' in resp.text, "selected-items markup missing"
    assert 'id="opt-excluded"' in resp.text, "excluded-items markup missing"


def test_contest_start_then_choose_changes_elo(client, conn):
    start = client.post("/contest/start", follow_redirects=False)
    assert start.status_code == 200

    match = re.search(r'name="winner_id"\s+value="(\d+)"', start.text)
    assert match is not None, f"no winner button in {start.text[:600]!r}"
    winner_id = int(match.group(1))

    base_elo = _row_stat(conn, winner_id)
    assert base_elo[1] == 0, "winner should have zero matches before the contest"

    choose = client.post(
        "/contest/choose",
        data={"winner_id": str(winner_id)},
        follow_redirects=False,
    )
    assert choose.status_code == 200

    after_elo, matches_played = _row_stat(conn, winner_id)
    assert matches_played == 1, "one match should be recorded"
    assert after_elo > base_elo[0], f"Elo did not rise: {base_elo} -> {after_elo}"

    rendered = f"{after_elo:.1f}"
    assert rendered in choose.text, (
        f"Winner Elo {rendered} not in leaderboard HTML: {choose.text[:700]!r}"
    )


def test_pool_add_returns_both_columns(client, conn):
    identity = conn.execute(
        "SELECT id FROM projects WHERE name='Identity & SSO'"
    ).fetchone()
    assert identity is not None, "seed should create 'Identity & SSO'"
    identity_id = int(identity[0])

    add_resp = client.post(
        f"/pool/add/{identity_id}", follow_redirects=False
    )
    assert add_resp.status_code == 200
    assert 'id="available-list"' in add_resp.text
    assert 'id="pool-list"' in add_resp.text
    assert "Identity" in add_resp.text and "SSO" in add_resp.text


def _create_project(client, name):
    """POST a project via its create form; asserts the 303 redirect."""
    payload = {
        "name": name,
        "description": "test project",
        "cost": "1000",
        "cost_currency": "SGD",
        "outcome": "9",
    }
    resp = client.post("/projects", data=payload, follow_redirects=False)
    assert resp.status_code == 303, f"create failed for {name}: {resp.status_code}"


def test_projects_page_ok_when_pool_nonempty(client, conn):
    """GET /projects must not 503 when the pool already has a project in it."""
    identity = conn.execute(
        "SELECT id FROM projects WHERE name='Identity & SSO'"
    ).fetchone()
    assert identity is not None, "seed should create 'Identity & SSO'"

    add_resp = client.post(f"/pool/add/{int(identity[0])}", follow_redirects=False)
    assert add_resp.status_code == 200

    resp = client.get("/projects")
    assert resp.status_code == 200, f"GET /projects failed: {resp.status_code}"
    # "Identity & SSO": Jinja escapes '&', so check the words separately.
    assert "Identity" in resp.text and "SSO" in resp.text
    assert "In pool" in resp.text, "pooled project should show an 'In pool' badge"


def test_htmx_delete_returns_list_fragment(client, conn):
    """An HTMX delete returns the 200 list fragment, not a 303 redirect."""
    name = "HTMX-Delete-Smoke-ZX7Q"
    _create_project(client, name)
    created = conn.execute(
        "SELECT id FROM projects WHERE name=?", (name,)
    ).fetchone()
    assert created is not None, "created project not found"

    resp = client.post(
        f"/projects/{int(created[0])}/delete",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    # HTMX delete swaps back the whole list fragment.
    assert resp.status_code == 200, f"expected 200 fragment, got {resp.status_code}"
    assert 'id="project-list"' in resp.text, "list fragment marker missing"
    # A bare fragment is not a full HTML document.
    assert "<html" not in resp.text.lower(), "response looks like a full page, not a fragment"


def test_budget_post_includes_header_oob(client):
    resp = client.post(
        "/settings/budget",
        data={"amount": "200000", "currency": "SGD"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert 'id="header-budget"' in resp.text
    assert "hx-swap-oob" in resp.text
    assert "200,000" in resp.text or "200000" in resp.text


def test_rates_post_includes_header_oob(client):
    resp = client.post(
        "/settings/rates",
        data={"usd_per_sgd": "1.35", "myr_per_sgd": "3.45"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert 'id="header-budget"' in resp.text
    assert "hx-swap-oob" in resp.text


def test_pool_remaining_shows_three_currencies(client):
    resp = client.get("/pool")
    assert resp.status_code == 200
    assert "Remaining" in resp.text
    assert "S$" in resp.text and "US$" in resp.text and "RM" in resp.text
