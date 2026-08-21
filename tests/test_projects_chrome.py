"""Projects notes, filter, last currency (docs/09-projects-notes-theme.md)."""

import re
from pathlib import Path

from stackrank.services import create_project


def test_create_project_persists_notes(conn):
    pid = create_project(
        conn,
        name="Notes Tile",
        description="desc",
        notes="must tile first",
        cost=100,
        cost_currency="SGD",
        outcome=10,
        depends_on=[],
     )
    row = conn.execute("SELECT notes FROM projects WHERE id=?", (pid,)).fetchone()
    assert row is not None
    assert row["notes"] == "must tile first"


def test_create_project_remembers_last_cost_currency(conn):
    create_project(
        conn,
        name="Usd Job",
        description="",
        notes="",
        cost=10,
        cost_currency="USD",
        outcome=1,
        depends_on=[],
    )
    row = conn.execute("SELECT last_cost_currency FROM settings WHERE id=1").fetchone()
    assert row["last_cost_currency"] == "USD"


def test_projects_q_hides_non_matching_names(client):
    client.post(
        "/projects",
        data={
            "name": "Alpha Filter",
            "description": "",
            "cost": "10",
            "cost_currency": "SGD",
            "outcome": "1",
        },
    )
    client.post(
        "/projects",
        data={
            "name": "Beta Filter",
            "description": "",
            "cost": "10",
            "cost_currency": "SGD",
            "outcome": "1",
        },
    )
    resp = client.get("/projects", params={"q": "Alpha Filter"})
    assert resp.status_code == 200
    assert '<h2 class="text-lg font-semibold">Alpha Filter</h2>' in resp.text
    assert '<h2 class="text-lg font-semibold">Beta Filter</h2>' not in resp.text


def test_projects_pool_in_only_lists_in_pool(client, conn):
    client.post(
         "/projects",
        data={
             "name": "InPool Only",
             "description": "",
             "cost": "10",
             "cost_currency": "SGD",
             "outcome": "1",
         },
     )
    client.post(
         "/projects",
        data={
             "name": "OutPool Only",
             "description": "",
             "cost": "10",
             "cost_currency": "SGD",
             "outcome": "1",
         },
     )
    in_id = int(
        conn.execute(
             "SELECT id FROM projects WHERE name=?", ("InPool Only",)
         ).fetchone()[0]
     )
    client.post(f"/pool/add/{in_id}")
    resp = client.get("/projects", params={"pool": "in"})
    assert resp.status_code == 200
    assert '<h2 class="text-lg font-semibold">InPool Only</h2>' in resp.text
    assert '<h2 class="text-lg font-semibold">OutPool Only</h2>' not in resp.text


def test_edit_form_shows_entered_usd_not_sgd(client, conn):
    client.post(
        "/projects",
        data={
            "name": "Usd Edit Job",
            "description": "",
            "cost": "74",
            "cost_currency": "USD",
            "outcome": "10",
        },
    )
    pid = int(
        conn.execute(
            "SELECT id FROM projects WHERE name=?", ("Usd Edit Job",)
        ).fetchone()[0]
    )
    resp = client.get(f"/projects/{pid}/edit")
    assert resp.status_code == 200
    assert 'name="cost"' in resp.text
    assert 'value="74.00"' in resp.text
    assert 'value="USD" selected' in resp.text
    assert "100.00" not in resp.text
    client.post(
        f"/projects/{pid}",
        data={
            "name": "Usd Edit Job",
            "description": "",
            "cost": "74.00",
            "cost_currency": "USD",
            "outcome": "10",
        },
    )
    row = conn.execute(
        "SELECT cost_amount, cost_currency FROM projects WHERE id=?", (pid,)
    ).fetchone()
    assert float(row["cost_amount"]) == 74
    assert row["cost_currency"] == "USD"


def test_create_usd_then_add_form_selects_usd(client):
    client.post(
        "/projects",
        data={
            "name": "Usd Default Job",
            "description": "",
            "cost": "10",
            "cost_currency": "USD",
            "outcome": "1",
        },
    )
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert 'value="USD" selected' in resp.text


def test_projects_page_includes_outcome_per_sgd(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert "outcome/S$" in resp.text or "outcome/S" in resp.text


def test_projects_page_includes_dep_sketch_svg(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "dep-sketch" in resp.text
    assert "Identity &amp; SSO</text>" in resp.text
    assert "d[:14]" not in resp.text


def test_contest_choose_then_undo_restores_elo(client, conn):
    start = client.post("/contest/start")
    assert start.status_code == 200
    found = re.search(r'name="winner_id"\s+value="(\d+)"', start.text)
    assert found is not None
    winner_id = int(found.group(1))
    before = conn.execute(
         "SELECT elo_rating, matches_played FROM projects WHERE id=?",
         (winner_id,),
     ).fetchone()
    choose = client.post("/contest/choose", data={"winner_id": str(winner_id)})
    assert choose.status_code == 200
    mid = conn.execute(
         "SELECT elo_rating, matches_played FROM projects WHERE id=?",
         (winner_id,),
     ).fetchone()
    assert int(mid["matches_played"]) == int(before["matches_played"]) + 1
    undo = client.post("/contest/undo")
    assert undo.status_code == 200
    after = conn.execute(
         "SELECT elo_rating, matches_played FROM projects WHERE id=?",
         (winner_id,),
     ).fetchone()
    assert int(after["matches_played"]) == int(before["matches_played"])
    assert abs(float(after["elo_rating"]) - float(before["elo_rating"])) < 1e-6


def test_dark_nav_active_matches_theme_button_chip():
    css = (Path(__file__).resolve().parents[1] / "static" / "app.css").read_text()
    assert "html.dark a.nav-active" in css
    block = css.split("html.dark a.nav-active", 1)[1].split("}", 1)[0]
    assert "#4f46e5" in block
    assert "#fff" in block


def test_selected_tab_uses_theme_button_classes(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert "nav-active rounded bg-indigo-600 text-white" in resp.text
    assert "text-brand-dark nav-active" not in resp.text


def test_rates_post_returns_budget_card_not_nested(client):
    resp = client.post(
         "/settings/rates",
        data={"usd_per_sgd": "0.74", "myr_per_sgd": "3.45"},
     )
    assert resp.status_code == 200
    assert resp.text.count('id="budget-card"') == 1
    assert '<section id="budget-card">' in resp.text


def test_projects_page_includes_favicon_and_data_theme(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert "favicon.svg" in resp.text
    assert "data-theme=" in resp.text


def test_theme_post_stays_on_current_tab(client):
    resp = client.post(
        "/settings/theme",
        data={"theme": "dark", "next": "/pool"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pool"
    pool = client.get("/pool")
    assert pool.status_code == 200
    assert 'data-theme="dark"' in pool.text
    assert 'name="next" value="/pool"' in pool.text
