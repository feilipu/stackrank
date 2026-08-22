"""Service-layer tests for pool management + project CRUD (docs/05-testing.md)."""

from __future__ import annotations

import pytest

from stackrank.services import (
    ServiceError,
    add_to_pool,
    create_project,
    delete_project,
    exclusions_map,
    get_project,
    pool_rows,
    reorder_pool,
    remove_from_pool,
    set_pool_metric,
    toggle_pin,
    update_budget,
    update_project,
    update_rates,
)


def assert_service_error(exc_info, status=None):
    exc = exc_info.value
    assert isinstance(exc, ServiceError), f"expected ServiceError, got {exc!r}"
    if status is not None:
        got = getattr(exc, "status_code", None)
        assert got == status, f"ServiceError status={got}; expected {status}"


def new_project(conn, name, cost=100, outcome=30.0, depends_on=None, excludes=None):
    return create_project(
        conn,
        name=name,
        description="",
        cost=cost,
        cost_currency="SGD",
        outcome=outcome,
        depends_on=list(depends_on or []),
        excludes=list(excludes or []),
    )


def test_add_expensive_project_ejects_lowest_unpinned_by_pool_metric(conn):
    set_pool_metric(conn, "outcome")

    p_low = new_project(conn, "Low", cost=100, outcome=10.0)
    p_high = new_project(conn, "High", cost=100, outcome=90.0)
    add_to_pool(conn, p_low)
    add_to_pool(conn, p_high)

       # tighten so incoming + two bases (201 SGD) overflows but one survives
    update_budget(conn, 150, "SGD")
    p_incoming = new_project(conn, "Incoming", cost=1, outcome=50.0)

    add_to_pool(conn, p_incoming)

    ids_after = {int(r["id"]) for r in pool_rows(conn)}
    assert p_low not in ids_after, "lowest-metric unpinned project should be ejected"
    assert p_high in ids_after
    assert p_incoming in ids_after


def test_pinned_project_not_ejected_and_add_rejects_when_nothing_else_can_go(conn):
    set_pool_metric(conn, "outcome")

       # P fits under a roomy budget and is then pinned
    update_budget(conn, 1000, "SGD")
    p = new_project(conn, "Pinned", cost=3, outcome=60.0)
    add_to_pool(conn, p)
    toggle_pin(conn, p)

       # drop budget below (p + incoming); the only occupant is pinned
    update_budget(conn, 5, "SGD")
    incoming = new_project(conn, "Another", cost=9, outcome=70.0)

       # no unpinned victim -> add rejected with 409, pool untouched
    with pytest.raises(ServiceError) as exc_info:
        add_to_pool(conn, incoming)

    assert_service_error(exc_info, status=409)
    ids_after = {int(r["id"]) for r in pool_rows(conn)}
    assert p in ids_after, "the pinned project must survive"
    assert incoming not in ids_after


def test_missing_dependency_blocks_add_to_pool(conn):
       # A depends on B; adding A while B is outside the pool is a 409
    b_pid = new_project(conn, "B", cost=100, outcome=30.0)
    p_a = new_project(conn, "A", cost=100, outcome=40.0, depends_on=[b_pid])

    with pytest.raises(ServiceError) as exc_info:
        add_to_pool(conn, int(p_a))

    assert_service_error(exc_info, status=409)


def test_cannot_remove_dependency_while_dependent_pooled(conn):
       # B pooled first, then A (depends on B); removing B while A is pooled -> 409
    b_pid = new_project(conn, "B", cost=100, outcome=30.0)
    p_a = new_project(conn, "A", cost=100, outcome=40.0, depends_on=[b_pid])

    add_to_pool(conn, int(b_pid))
    add_to_pool(conn, int(p_a))

       # removing a pooled dependency still needed by a pooled dependent is blocked
    with pytest.raises(ServiceError) as exc_info:
        remove_from_pool(conn, int(b_pid))

    assert_service_error(exc_info, status=409)
       # blocking happens before any mutation; both remain pooled
    ids_after = {int(r["id"]) for r in pool_rows(conn)}
    assert int(b_pid) in ids_after and int(p_a) in ids_after


def test_reorder_pool_persists_positions(conn):
       # three projects fit comfortably under the default 250000 SGD budget
    p1 = new_project(conn, "P1", cost=100, outcome=30.0)
    p2 = new_project(conn, "P2", cost=100, outcome=40.0)
    p3 = new_project(conn, "P3", cost=100, outcome=50.0)

    add_to_pool(conn, int(p1))
    add_to_pool(conn, int(p2))
    add_to_pool(conn, int(p3))

       # reverse their stored positions
    reorder_pool(conn, [int(p3), int(p2), int(p1)])

    rows = pool_rows(conn)
    ordered_ids = [int(r["id"]) for r in rows]
    assert set(ordered_ids) == {p1, p2, p3}
    expected_order = [int(p3), int(p2), int(p1)]
    for i in range(len(expected_order)):
        assert int(rows[i]["id"]) == expected_order[i]
        assert int(rows[i]["position"]) == i


def test_circular_dependency_rejected(conn):
       # linear chain P1 <- P2 <- P3; making P1 depend on P3 closes the loop
    p1 = new_project(conn, "P1", cost=100, outcome=40.0)
    p2 = new_project(conn, "P2", cost=100, outcome=50.0, depends_on=[p1])
    p3 = new_project(conn, "P3", cost=100, outcome=60.0, depends_on=[p2])

       # closing the loop is a cycle -> rejected by update_project
    with pytest.raises(ServiceError) as exc_info:
        update_project(
            conn,
            int(p1),
            name="P1",
            description="",
            cost=100,
            cost_currency="SGD",
            outcome=40.0,
            depends_on=[int(p3)],
        )

    assert_service_error(exc_info)


def test_self_dependency_rejected(conn):
       # self-reference must be refused on update before any write happens
    p = new_project(conn, "Solo", cost=100, outcome=30.0)

    with pytest.raises(ServiceError) as exc_info:
        update_project(
            conn,
            int(p),
            name="Solo",
            description="",
            cost=100,
            cost_currency="SGD",
            outcome=30.0,
            depends_on=[int(p)],
        )

    assert_service_error(exc_info)

       # no self edge should have reached the dependency table
    self_edges = conn.execute(
        "SELECT COUNT(*) AS n FROM project_dependencies WHERE project_id=? AND depends_on_id=?",
        (int(p), int(p)),
    ).fetchone()["n"]
    assert self_edges == 0


def test_cost_and_outcome_must_be_positive(conn):
       # negative cost is refused by the validator
    with pytest.raises(ServiceError) as exc_info:
        create_project(
            conn,
            name="Bad",
            description="",
            cost=-5,
            cost_currency="SGD",
            outcome=10.0,
            depends_on=[],
        )

    assert_service_error(exc_info)


def test_delete_project_removes_from_pool(conn):
       # put a project in the pool then confirm delete_project removes it entirely
    p = new_project(conn, "ToDelete", cost=100, outcome=30.0)
    add_to_pool(conn, int(p))

       # before cleanup: it is pooled
    pre_ids = {int(r["id"]) for r in pool_rows(conn)}
    assert p in pre_ids

       # delete and confirm gone from both the project table and the pool
    delete_project(conn, int(p))
    row = conn.execute("SELECT * FROM projects WHERE id=?", (p,)).fetchone()
    assert row is None
    post_ids = {int(r["id"]) for r in pool_rows(conn)}
    assert p not in post_ids


def test_budget_shrink_ejects_lowest_unpinned_outcome(conn):
    set_pool_metric(conn, "outcome")
    low = new_project(conn, "Low", cost=100, outcome=10.0)
    high = new_project(conn, "High", cost=100, outcome=90.0)
    add_to_pool(conn, low)
    add_to_pool(conn, high)
    result = update_budget(conn, 150, "SGD")
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert high in ids and low not in ids
    assert result["over_budget"] is False
    assert low in result["ejected_ids"]


def test_budget_shrink_pinned_still_fits(conn):
    set_pool_metric(conn, "outcome")
    update_budget(conn, 1000, "SGD")
    p = new_project(conn, "PinnedFit", cost=3, outcome=60.0)
    add_to_pool(conn, p)
    toggle_pin(conn, p)
    result = update_budget(conn, 5, "SGD")
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert p in ids
    assert result["over_budget"] is False


def test_budget_shrink_pinned_exceeds_budget(conn):
    set_pool_metric(conn, "outcome")
    update_budget(conn, 1000, "SGD")
    p = new_project(conn, "PinnedOver", cost=100, outcome=60.0)
    add_to_pool(conn, p)
    toggle_pin(conn, p)
    result = update_budget(conn, 40, "SGD")
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert p in ids
    assert result["over_budget"] is True
    assert result["budget_sgd"] == 40


def test_budget_shrink_ejects_dependency_and_dependent(conn):
    set_pool_metric(conn, "outcome")
    update_budget(conn, 1000, "SGD")
    b = new_project(conn, "DepB", cost=100, outcome=10.0)
    a = new_project(conn, "DepA", cost=100, outcome=90.0, depends_on=[b])
    add_to_pool(conn, b)
    add_to_pool(conn, a)
    result = update_budget(conn, 150, "SGD")
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert a not in ids and b not in ids
    assert result["over_budget"] is False


def test_budget_shrink_cannot_eject_dep_of_pinned(conn):
    set_pool_metric(conn, "outcome")
    update_budget(conn, 1000, "SGD")
    b = new_project(conn, "KeepB", cost=100, outcome=10.0)
    a = new_project(conn, "PinA", cost=100, outcome=90.0, depends_on=[b])
    add_to_pool(conn, b)
    add_to_pool(conn, a)
    toggle_pin(conn, a)
    result = update_budget(conn, 50, "SGD")
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert a in ids and b in ids
    assert result["over_budget"] is True


def test_create_persists_entered_cost_and_currency(conn):
    pid = create_project(
        conn,
        name="Usd Quote",
        description="",
        cost=74,
        cost_currency="USD",
        outcome=10,
        depends_on=[],
    )
    row = get_project(conn, pid)
    assert float(row["cost_amount"]) == 74
    assert row["cost_currency"] == "USD"
    assert abs(float(row["cost_sgd"]) - 100) < 1e-6


def test_update_unchanged_cost_keeps_entered_amount(conn):
    pid = create_project(
        conn,
        name="Keep Usd",
        description="",
        cost=74,
        cost_currency="USD",
        outcome=10,
        depends_on=[],
    )
    update_project(
        conn,
        pid,
        name="Keep Usd",
        description="",
        cost=74,
        cost_currency="USD",
        outcome=10,
        depends_on=[],
    )
    row = get_project(conn, pid)
    assert float(row["cost_amount"]) == 74
    assert row["cost_currency"] == "USD"


def test_rate_change_recomputes_cost_sgd_from_entered(conn):
    pid = create_project(
        conn,
        name="Fx Job",
        description="",
        cost=74,
        cost_currency="USD",
        outcome=10,
        depends_on=[],
    )
    assert abs(float(get_project(conn, pid)["cost_sgd"]) - 100) < 1e-6
    update_rates(conn, 1.0, 3.45)
    row = get_project(conn, pid)
    assert float(row["cost_amount"]) == 74
    assert row["cost_currency"] == "USD"
    assert abs(float(row["cost_sgd"]) - 74) < 1e-6


def test_create_stores_symmetric_exclusions(conn):
    a = new_project(conn, "Option A")
    b = new_project(conn, "Option B", excludes=[a])
    mapping = exclusions_map(conn)
    assert a in mapping[b] and b in mapping[a]


def test_update_exclude_mirrors_onto_peer(conn):
    a = new_project(conn, "PeerA")
    b = new_project(conn, "PeerB")
    update_project(
        conn,
        int(a),
        name="PeerA",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[int(b)],
    )
    mapping = exclusions_map(conn)
    assert b in mapping[a] and a in mapping[b]
    pairs = {
        (int(r["project_id"]), int(r["excludes_id"]))
        for r in conn.execute("SELECT project_id, excludes_id FROM project_exclusions")
    }
    assert (a, b) in pairs and (b, a) in pairs


def _exclusion_pairs(conn):
    return {
        (int(r["project_id"]), int(r["excludes_id"]))
        for r in conn.execute("SELECT project_id, excludes_id FROM project_exclusions")
    }


def test_clearing_exclude_drops_both_sides(conn):
    a = new_project(conn, "ClearA")
    b = new_project(conn, "ClearB")
    update_project(
        conn,
        int(a),
        name="ClearA",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[int(b)],
    )
    update_project(
        conn,
        int(a),
        name="ClearA",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[],
    )
    mapping = exclusions_map(conn)
    assert mapping.get(a, []) == []
    assert mapping.get(b, []) == []
    assert _exclusion_pairs(conn) == set()


def test_removing_one_exclude_keeps_the_other_pair(conn):
    a = new_project(conn, "KeepA")
    b = new_project(conn, "DropB")
    c = new_project(conn, "KeepC")
    update_project(
        conn,
        int(a),
        name="KeepA",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[int(b), int(c)],
    )
    update_project(
        conn,
        int(a),
        name="KeepA",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[int(c)],
    )
    mapping = exclusions_map(conn)
    assert set(mapping.get(a, [])) == {c}
    assert set(mapping.get(c, [])) == {a}
    assert mapping.get(b, []) == []
    pairs = _exclusion_pairs(conn)
    assert (a, c) in pairs and (c, a) in pairs
    assert (a, b) not in pairs and (b, a) not in pairs


def test_clearing_exclude_from_peer_form_clears_both(conn):
    a = new_project(conn, "FormA")
    b = new_project(conn, "FormB")
    update_project(
        conn,
        int(a),
        name="FormA",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[int(b)],
    )
    update_project(
        conn,
        int(b),
        name="FormB",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=30.0,
        depends_on=[],
        excludes=[],
    )
    mapping = exclusions_map(conn)
    assert mapping.get(a, []) == []
    assert mapping.get(b, []) == []


def test_one_way_exclusion_row_still_maps_both_sides(conn):
    a = new_project(conn, "OneWayA")
    b = new_project(conn, "OneWayB")
    conn.execute("DELETE FROM project_exclusions")
    conn.execute(
        "INSERT INTO project_exclusions (project_id, excludes_id) VALUES (?, ?)",
        (a, b),
    )
    mapping = exclusions_map(conn)
    assert b in mapping[a] and a in mapping[b]


def test_apply_schema_persists_missing_reverse_exclusion(conn):
    from stackrank.db import apply_schema

    a = new_project(conn, "MirrorA")
    b = new_project(conn, "MirrorB")
    conn.execute("DELETE FROM project_exclusions")
    conn.execute(
        "INSERT INTO project_exclusions (project_id, excludes_id) VALUES (?, ?)",
        (a, b),
    )
    apply_schema(conn)
    pairs = {
        (int(r["project_id"]), int(r["excludes_id"]))
        for r in conn.execute("SELECT project_id, excludes_id FROM project_exclusions")
    }
    assert (a, b) in pairs and (b, a) in pairs


def test_cannot_exclude_self(conn):
    a = new_project(conn, "SoloEx")
    with pytest.raises(ServiceError) as exc_info:
        update_project(
            conn,
            int(a),
            name="SoloEx",
            description="",
            cost=100,
            cost_currency="SGD",
            outcome=30.0,
            depends_on=[],
            excludes=[int(a)],
        )
    assert_service_error(exc_info)
    assert exclusions_map(conn).get(int(a), []) == []


def test_cannot_exclude_a_dependency(conn):
    base = new_project(conn, "Base")
    with pytest.raises(ServiceError) as exc_info:
        new_project(conn, "Child", depends_on=[base], excludes=[base])
    assert_service_error(exc_info)


def test_cannot_exclude_a_dependent(conn):
    base = new_project(conn, "KeepBase")
    child = new_project(conn, "ChildOfBase", depends_on=[base])
    with pytest.raises(ServiceError) as exc_info:
        update_project(
            conn,
            int(base),
            name="KeepBase",
            description="",
            cost=100,
            cost_currency="SGD",
            outcome=30.0,
            depends_on=[],
            excludes=[int(child)],
        )
    assert_service_error(exc_info)


def test_cannot_depend_on_exclusive_pair(conn):
    a = new_project(conn, "AltA")
    b = new_project(conn, "AltB", excludes=[a])
    with pytest.raises(ServiceError) as exc_info:
        new_project(conn, "NeedsBoth", depends_on=[a, b])
    assert_service_error(exc_info)


def test_add_exclusive_pushes_the_other_out(conn):
    update_budget(conn, 1000, "SGD")
    a = new_project(conn, "Tile A", cost=100, outcome=40.0)
    b = new_project(conn, "Tile B", cost=100, outcome=50.0, excludes=[a])
    add_to_pool(conn, a)
    result = add_to_pool(conn, b)
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert b in ids and a not in ids
    assert a in result["exclusive_ids"]
    assert "Tile A" in result["exclusive_names"]
    assert result["budget_ids"] == []


def test_add_exclusive_blocked_when_other_is_pinned(conn):
    update_budget(conn, 1000, "SGD")
    a = new_project(conn, "Pinned Alt", cost=100, outcome=40.0)
    b = new_project(conn, "New Alt", cost=100, outcome=50.0, excludes=[a])
    add_to_pool(conn, a)
    toggle_pin(conn, a)
    with pytest.raises(ServiceError) as exc_info:
        add_to_pool(conn, b)
    assert_service_error(exc_info, status=409)
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert a in ids and b not in ids


def test_add_exclusive_also_ejects_dependents(conn):
    update_budget(conn, 1000, "SGD")
    a = new_project(conn, "AltBase", cost=100, outcome=40.0)
    child = new_project(conn, "AltChild", cost=100, outcome=60.0, depends_on=[a])
    b = new_project(conn, "OtherAlt", cost=100, outcome=50.0, excludes=[a])
    add_to_pool(conn, a)
    add_to_pool(conn, child)
    result = add_to_pool(conn, b)
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert b in ids
    assert a not in ids and child not in ids
    assert a in result["exclusive_ids"] and child in result["exclusive_ids"]


def test_add_to_pool_reports_budget_ejections(conn):
    set_pool_metric(conn, "outcome")
    update_budget(conn, 150, "SGD")
    low = new_project(conn, "BudgetLow", cost=100, outcome=10.0)
    high = new_project(conn, "BudgetHigh", cost=100, outcome=90.0)
    add_to_pool(conn, low)
    result = add_to_pool(conn, high)
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert high in ids and low not in ids
    assert low in result["budget_ids"]
    assert "BudgetLow" in result["budget_names"]
    assert result["exclusive_ids"] == []


def test_update_exclude_ejects_pooled_alternative(conn):
    update_budget(conn, 1000, "SGD")
    a = new_project(conn, "PooledA", cost=100, outcome=40.0)
    b = new_project(conn, "PooledB", cost=100, outcome=50.0)
    add_to_pool(conn, a)
    add_to_pool(conn, b)
    result = update_project(
        conn,
        int(b),
        name="PooledB",
        description="",
        cost=100,
        cost_currency="SGD",
        outcome=50.0,
        depends_on=[],
        excludes=[int(a)],
    )
    ids = {int(r["id"]) for r in pool_rows(conn)}
    assert b in ids and a not in ids
    assert "PooledA" in result["exclusive_names"]
