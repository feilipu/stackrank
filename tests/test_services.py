"""Service-layer tests for pool management + project CRUD (docs/05-testing.md)."""

from __future__ import annotations

import pytest

from stackrank.services import (
    ServiceError,
    add_to_pool,
    create_project,
    delete_project,
    pool_rows,
    reorder_pool,
    remove_from_pool,
    set_pool_metric,
    toggle_pin,
    update_budget,
    update_project,
)


def assert_service_error(exc_info, status=None):
    exc = exc_info.value
    assert isinstance(exc, ServiceError), f"expected ServiceError, got {exc!r}"
    if status is not None:
        got = getattr(exc, "status_code", None)
        assert got == status, f"ServiceError status={got}; expected {status}"


def new_project(conn, name, cost=100, outcome=30.0, depends_on=None):
    return create_project(
        conn,
        name=name,
        description="",
        cost=cost,
        cost_currency="SGD",
        outcome=outcome,
        depends_on=list(depends_on or []),
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
