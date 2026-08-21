"""Pool-tab budget fill fraction (docs/07-pool-fill-animation.md)."""

import re

from stackrank.services import budget_fill


def test_budget_fill_half():
    d = budget_fill(50, 100)
    assert d["fill_pct"] == 50
    assert d["fill_ratio"] == 0.5


def test_budget_fill_over_clamps_pct():
    d = budget_fill(150, 100)
    assert d["fill_pct"] == 100
    assert d["fill_ratio_raw"] == 1.5


def test_budget_fill_zero_budget():
    d = budget_fill(10, 0)
    assert d["fill_pct"] == 0


def test_pool_page_renders_fill_graphic(client):
    resp = client.get("/pool")
    assert resp.status_code == 200
    assert 'id="pool-fill"' in resp.text
    assert re.search(r'data-fill="\d+"', resp.text)
    assert re.search(r"--pool-fill:\s*\d+%;", resp.text)
    assert re.search(r"--pool-fill-ratio:\s*[01](\.\d+)?;", resp.text)
    assert "pool-fill-frame" in resp.text
    assert "pool-fill-wave-clip" in resp.text
    assert "pool-fill-wave-c" in resp.text
    assert "pool-fill-wave-d" in resp.text
    assert "pool-fill-wave-clip-front" in resp.text
    assert re.search(r"\d+% full", resp.text, re.I)


def test_pool_page_has_no_control_char_glyphs(client):
    resp = client.get("/pool")
    assert resp.status_code == 200
    assert "\x01" not in resp.text
    assert "\x02" not in resp.text


def test_pool_page_uses_html_water_not_svg_basin(client):
    resp = client.get("/pool")
    assert resp.status_code == 200
    assert 'class="pool-fill-water"' in resp.text
    assert 'class="pool-fill-duck"' in resp.text


def test_pool_page_budget_and_fill_are_split(client):
    resp = client.get("/pool")
    assert resp.status_code == 200
    assert 'id="pool-sticky"' in resp.text
    assert 'id="budget-card"' in resp.text
    assert 'id="pool-fill"' in resp.text
    assert 'name="metric"' in resp.text
    assert "Available Pool" in resp.text


def test_pool_add_returns_fill_oob(client, conn):
    identity = conn.execute(
         "SELECT id FROM projects WHERE name='Identity & SSO'"
     ).fetchone()
    assert identity is not None
    resp = client.post(f"/pool/add/{int(identity[0])}", follow_redirects=False)
    assert resp.status_code == 200
    assert 'id="pool-fill"' in resp.text
    assert "hx-swap-oob" in resp.text
    fill = re.search(r'data-fill="(\d+)"', resp.text)
    assert fill is not None and int(fill.group(1)) > 0
    assert re.search(r"\d+% full", resp.text, re.I)


def test_projects_page_has_no_pool_fill(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert 'id="pool-fill"' not in resp.text
