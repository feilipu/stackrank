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


def test_rename_overall_project_persists(client):
    r = client.post("/settings/name", data={"name": "Acme Launch"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    page = client.get("/projects")
    assert page.status_code == 200
    assert "Acme Launch" in page.text


def test_rename_overall_project_rejects_empty(client):
    r = client.post("/settings/name", data={"name": "   "}, follow_redirects=False)
    assert r.status_code == 422


def test_export_markdown_lists_seed_projects(client):
    resp = client.get("/export.md")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers.get("content-type", "")
    assert "Identity" in resp.text and "SSO" in resp.text
    assert "Budget:" in resp.text
    assert "| Project |" in resp.text
    assert "attachment" in (resp.headers.get("content-disposition") or "")


def test_export_markdown_uses_renamed_title(client):
    client.post("/settings/name", data={"name": "Acme Launch"}, follow_redirects=False)
    resp = client.get("/export.md")
    assert resp.status_code == 200
    assert resp.text.startswith("# Acme Launch")
    assert "acme-launch.md" in (resp.headers.get("content-disposition") or "")


def test_budget_shrink_flash_and_pool_oob(client, conn):
    for name, cost, outcome in (("EjectMe", "100", "10"), ("KeepMe", "100", "90")):
        client.post(
             "/projects",
            data={
                 "name": name,
                 "description": "",
                 "cost": cost,
                 "cost_currency": "SGD",
                 "outcome": outcome,
             },
            follow_redirects=False,
         )
    ids = {name: _id_for(conn, name) for name in ("EjectMe", "KeepMe")}
    client.post(f"/pool/add/{ids['EjectMe']}")
    client.post(f"/pool/add/{ids['KeepMe']}")
    resp = client.post(
         "/settings/budget",
        data={"amount": "150", "currency": "SGD"},
        follow_redirects=False,
     )
    assert resp.status_code == 200
    assert 'id="header-budget"' in resp.text
    assert "EjectMe" in resp.text
    assert 'id="pool-board"' in resp.text
    assert "hx-swap-oob" in resp.text
    assert "Removed from the success pool to fit the new budget" in resp.text


def test_projects_form_includes_excludes_field(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert 'name="excludes"' in resp.text
    assert "Excludes" in resp.text
    assert 'name="depends_on"' in resp.text
    assert "rel-selects" in resp.text
    form = resp.text.split('id="new-project-form"', 1)[-1].split("</form>", 1)[0]
    assert 'type="checkbox" name="excludes"' in form
    assert 'type="checkbox" name="depends_on"' in form
    assert "rel-select-box" in form


def _id_for(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
    assert row is not None, name
    return int(row[0])


def _article(html: str, pid: int) -> str:
    m = re.search(rf'<article id="project-{pid}"[\s\S]*?</article>', html)
    assert m, f"missing article for {pid}"
    return m.group(0)


def test_exclude_posted_with_hidden_sentinel_still_saves(client, conn):
    """Browser may send excludes=0 (sentinel) plus the selected id."""
    client.post(
        "/projects",
        data={
            "name": "SentinelA",
            "description": "",
            "cost": "100",
            "cost_currency": "SGD",
            "outcome": "40",
        },
        follow_redirects=False,
    )
    client.post(
        "/projects",
        data={
            "name": "SentinelB",
            "description": "",
            "cost": "100",
            "cost_currency": "SGD",
            "outcome": "40",
            "excludes": ["0", str(_id_for(conn, "SentinelA"))],
        },
        follow_redirects=False,
    )
    a_id = _id_for(conn, "SentinelA")
    b_id = _id_for(conn, "SentinelB")
    page = client.get("/projects")
    b_html = _article(page.text, b_id)
    assert "Excludes:" in b_html and "SentinelA" in b_html
    pairs = {
        (int(r["project_id"]), int(r["excludes_id"]))
        for r in conn.execute("SELECT project_id, excludes_id FROM project_exclusions")
    }
    assert (b_id, a_id) in pairs and (a_id, b_id) in pairs


def test_exclude_note_appears_on_peer_card_and_edit(client, conn):
    for name in ("NoteAltA", "NoteAltB"):
        client.post(
            "/projects",
            data={
                "name": name,
                "description": "",
                "cost": "100",
                "cost_currency": "SGD",
                "outcome": "40",
            },
            follow_redirects=False,
        )
    a_id = _id_for(conn, "NoteAltA")
    b_id = _id_for(conn, "NoteAltB")
    upd = client.post(
        f"/projects/{a_id}",
        data={
            "name": "NoteAltA",
            "description": "",
            "cost": "100",
            "cost_currency": "SGD",
            "outcome": "40",
            "excludes": str(b_id),
        },
        follow_redirects=False,
    )
    assert upd.status_code == 200, upd.text[:400]
    a_html = _article(upd.text, a_id)
    b_html = _article(upd.text, b_id)
    assert "Excludes:" in a_html and "NoteAltB" in a_html
    assert "Excludes:" in b_html and "NoteAltA" in b_html
    edit_b = client.get(f"/projects/{b_id}/edit")
    assert edit_b.status_code == 200
    opt = re.search(
        rf'<input type="checkbox" name="excludes" value="{a_id}"([^>]*)>',
        edit_b.text,
    )
    assert opt is not None and "checked" in opt.group(1)


def test_clearing_exclude_removes_note_from_both_cards(client, conn):
    for name in ("GoneAltA", "GoneAltB"):
        client.post(
            "/projects",
            data={
                "name": name,
                "description": "",
                "cost": "100",
                "cost_currency": "SGD",
                "outcome": "40",
            },
            follow_redirects=False,
        )
    a_id = _id_for(conn, "GoneAltA")
    b_id = _id_for(conn, "GoneAltB")
    client.post(
        f"/projects/{a_id}",
        data={
            "name": "GoneAltA",
            "description": "",
            "cost": "100",
            "cost_currency": "SGD",
            "outcome": "40",
            "excludes": str(b_id),
        },
        follow_redirects=False,
    )
    cleared = client.post(
        f"/projects/{a_id}",
        data={
            "name": "GoneAltA",
            "description": "",
            "cost": "100",
            "cost_currency": "SGD",
            "outcome": "40",
            "excludes": "0",
        },
        follow_redirects=False,
    )
    assert cleared.status_code == 200, cleared.text[:400]
    a_html = _article(cleared.text, a_id)
    b_html = _article(cleared.text, b_id)
    assert "Excludes:" not in a_html
    assert "Excludes:" not in b_html
    edit_b = client.get(f"/projects/{b_id}/edit")
    opt = re.search(
        rf'<input type="checkbox" name="excludes" value="{a_id}"([^>]*)>',
        edit_b.text,
    )
    assert opt is None or "checked" not in opt.group(1)


def test_pool_add_exclusive_flashes_pushed_out_name(client, conn):
    for name in ("OptionA", "OptionB"):
        client.post(
            "/projects",
            data={
                "name": name,
                "description": "",
                "cost": "100",
                "cost_currency": "SGD",
                "outcome": "40",
            },
            follow_redirects=False,
        )
    a_id = _id_for(conn, "OptionA")
    b_id = _id_for(conn, "OptionB")
    upd = client.post(
        f"/projects/{b_id}",
        data={
            "name": "OptionB",
            "description": "",
            "cost": "100",
            "cost_currency": "SGD",
            "outcome": "40",
            "excludes": str(a_id),
        },
        follow_redirects=False,
    )
    assert upd.status_code == 200, upd.text[:400]
    client.post(f"/pool/add/{a_id}")
    resp = client.post(f"/pool/add/{b_id}", follow_redirects=False)
    assert resp.status_code == 200
    assert "Cannot coexist in the build" in resp.text
    assert "OptionA" in resp.text
    assert 'id="flash"' in resp.text
    assert "hx-swap-oob" in resp.text


def test_pool_add_budget_eject_flashes_name(client, conn):
    client.post("/settings/budget", data={"amount": "150", "currency": "SGD"})
    for name, outcome in (("StayHigh", "90"), ("GoLow", "10")):
        client.post(
            "/projects",
            data={
                "name": name,
                "description": "",
                "cost": "100",
                "cost_currency": "SGD",
                "outcome": outcome,
            },
            follow_redirects=False,
        )
    high_id = _id_for(conn, "StayHigh")
    low_id = _id_for(conn, "GoLow")
    client.post(f"/pool/add/{low_id}")
    resp = client.post(f"/pool/add/{high_id}", follow_redirects=False)
    assert resp.status_code == 200
    assert "Removed from the success pool to fit the budget" in resp.text
    assert "GoLow" in resp.text
