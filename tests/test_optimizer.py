"""Unit tests for the dependency-aware knapsack optimizer (docs/05-testing.md)."""

from __future__ import annotations

import pytest

from stackrank.optimizer import OptimizerError, optimize


def _proj(pid, cost_sgd, outcome=50.0, elo_rating=1500.0):
    return {
        "id": pid,
        "name": f"P{pid}",
        "cost_sgd": cost_sgd,
        "outcome": outcome,
        "elo_rating": elo_rating,
    }


def test_empty_projects_budget_selects_nothing():
    result = optimize([], [], budget_sgd=1000)
    assert result["selected"] == []
    assert result["excluded"] == []


def test_single_cheap_project_is_selected():
    result = optimize([_proj(1, 400)], dependencies=[], budget_sgd=1000)
    assert set(result["selected"]) == {1}


def test_single_expensive_project_excluded():
    result = optimize([_proj(1, 5000)], dependencies=[], budget_sgd=1000)
    assert set(result["selected"]) == set()
    assert 1 in result["excluded"]


def test_dependency_pair_both_fit_both_selected():
    projs = [_proj(1, 600), _proj(2, 300)]

    result = optimize(projs, dependencies=[(1, 2)], budget_sgd=1000)

    assert set(result["selected"]) == {1, 2}
    assert not (1 in result["selected"] and 2 not in result["selected"])


def test_diamond_dependency_does_not_double_count_sgd():
    projs = [_proj(1, 500), _proj(2, 400), _proj(3, 400)]

    result = optimize(projs, dependencies=[(2, 1), (3, 1)], budget_sgd=1900)

    assert set(result["selected"]) == {1, 2, 3}
    assert int(round(result["total_cost_sgd"])) <= 1300


def test_cycle_raises_optimizer_error():
    projs = [_proj(1, 100), _proj(2, 100)]

    with pytest.raises(OptimizerError):
        optimize(projs, dependencies=[(1, 2), (2, 1)], budget_sgd=1000)


def test_elo_vs_outcome_can_change_winner():
    projs = [
        _proj(1, 500, outcome=90.0, elo_rating=1300.0),
        _proj(2, 500, outcome=40.0, elo_rating=2000.0),
    ]

    by_metric = {
        m: set(optimize(projs, dependencies=[], budget_sgd=500, metric=m)["selected"])
        for m in ("outcome", "elo")
    }
    assert by_metric["outcome"] != by_metric["elo"], "metrics should disagree on the winner here"


def test_result_ancestor_closed_and_within_budget():
    projs = [_proj(1, 500), _proj(2, 500), _proj(3, 500)]
    deps = [(1, 2), (2, 3)]

    selected = set(optimize(projs, dependencies=deps, budget_sgd=1500)["selected"])

    for pid, dep in deps:
        if pid in selected:
            assert dep in selected
    total = sum(p["cost_sgd"] for p in projs if int(p["id"]) in selected)
    assert total <= 1500
