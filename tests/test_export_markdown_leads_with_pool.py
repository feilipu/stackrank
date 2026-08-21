def test_export_markdown_leads_with_pool(client, conn):
    identity = conn.execute("SELECT id FROM projects WHERE name='Identity & SSO'").fetchone()
    client.post(f"/pool/add/{int(identity[0])}")
    resp = client.get("/export.md")
    assert resp.status_code == 200
    assert "## In-Budget Success Pool" in resp.text
    assert "## Excluded" in resp.text
    assert "## All sub-projects" not in resp.text
    assert "Colour key" in resp.text
    assert "#ecfdf5" in resp.text
    assert "#fff7ed" in resp.text
    pool_at = resp.text.index("## In-Budget Success Pool")
    excluded_at = resp.text.index("## Excluded")
    assert pool_at < excluded_at
    pool_section = resp.text[pool_at:excluded_at]
    excluded_section = resp.text[excluded_at:]
    assert "| Identity & SSO | S$" in pool_section
    assert "| Identity & SSO | S$" not in excluded_section
    assert "| Partner API | S$" in excluded_section
    assert "| Partner API | S$" not in pool_section
    assert "Excluded" in excluded_section
    assert "| Project |" in pool_section
    assert "| Project |" in excluded_section


def test_export_html_colours_pool_vs_excluded(client, conn):
    identity = conn.execute("SELECT id FROM projects WHERE name='Identity & SSO'").fetchone()
    client.post(f"/pool/add/{int(identity[0])}")
    resp = client.get("/export.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Colour key" in resp.text
    assert "#ecfdf5" in resp.text
    assert "#fff7ed" in resp.text
    pool_at = resp.text.index("In-Budget Success Pool")
    excluded_at = resp.text.index("<h2>Excluded</h2>")
    assert pool_at < excluded_at
    pool_section = resp.text[pool_at:excluded_at]
    excluded_section = resp.text[excluded_at:]
    assert "Identity &amp; SSO" in pool_section or "Identity & SSO" in pool_section
    assert "Partner API" in excluded_section
    assert 'class="row pool"' in pool_section
    assert 'class="row excl"' in excluded_section
    assert 'class="site-top' in resp.text
    assert 'href="/projects"' in resp.text
    assert 'href="/pool"' in resp.text
    assert 'nav-active' in resp.text
    assert "Contractor list" in resp.text
    assert 'class="sheet"' in resp.text


def test_contractor_export_lists_only_accepted(client, conn):
    identity = conn.execute(
        "SELECT id FROM projects WHERE name='Identity & SSO'"
    ).fetchone()
    client.post(f"/pool/add/{int(identity[0])}")
    html = client.get("/export/contractor.html")
    assert html.status_code == 200
    assert "accepted projects" in html.text
    assert "Identity &amp; SSO" in html.text or "Identity & SSO" in html.text
    assert "Partner API" not in html.text
    assert "<h2>Excluded</h2>" not in html.text
    assert "Elo" not in html.text.split("accepted projects")[-1]
    assert 'class="sheet"' in html.text
    md = client.get("/export/contractor.md")
    assert md.status_code == 200
    assert md.text.startswith("# ")
    assert "accepted projects" in md.text
    assert "Identity & SSO" in md.text
    assert "Partner API" not in md.text
    assert "## Excluded" not in md.text
    assert "| Project |" in md.text
    assert "| Description |" in md.text
    assert "Budget:" not in md.text
    assert "Total:" in md.text
    assert "S$18,000" in md.text
    report = html.text.split('class="export-report"')[-1]
    assert "Budget:" not in report
    assert "Total:" in report
    assert "S$18,000" in report


def test_export_ccy_usd_converts_costs(client, conn):
    identity = conn.execute(
        "SELECT id FROM projects WHERE name='Identity & SSO'"
    ).fetchone()
    client.post(f"/pool/add/{int(identity[0])}")
    html = client.get("/export.html", params={"ccy": "USD"})
    assert html.status_code == 200
    assert 'name="ccy"' in html.text
    assert 'value="USD" selected' in html.text
    assert "US$13,320" in html.text
    assert "S$18,000" not in html.text
    con = client.get("/export/contractor.html", params={"ccy": "USD"})
    assert con.status_code == 200
    report = con.text.split('class="export-report"')[-1]
    assert "Budget:" not in report
    assert "Total: US$13,320" in report
    md = client.get("/export/contractor.md", params={"ccy": "USD"})
    assert "Budget:" not in md.text
    assert "Total: US$13,320" in md.text
    assert "US$13,320" in md.text
