"""Exact 0/1 knapsack over ancestor-closed subsets."""

from __future__ import annotations

from collections import defaultdict, deque

from stackrank.currency import metric_value


class OptimizerError(ValueError):
    pass


def _build_graph(projects: list[dict], dependencies: list[tuple[int, int]]) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Return (children, parents) where edge dep -> project."""
    ids = {int(p["id"]) for p in projects}
    children: dict[int, list[int]] = defaultdict(list)
    parents: dict[int, list[int]] = defaultdict(list)
    for project_id, depends_on_id in dependencies:
        if project_id not in ids or depends_on_id not in ids:
            continue
        children[depends_on_id].append(project_id)
        parents[project_id].append(depends_on_id)
    return children, parents


def topological_order(projects: list[dict], dependencies: list[tuple[int, int]]) -> list[int]:
    children, parents = _build_graph(projects, dependencies)
    ids = [int(p["id"]) for p in projects]
    indeg = {i: len(parents[i]) for i in ids}
    queue = deque(sorted(i for i in ids if indeg[i] == 0))
    order: list[int] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(children[node]):
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    if len(order) != len(ids):
        raise OptimizerError("dependency graph contains a cycle")
    return order


def ancestor_masks(projects: list[dict], dependencies: list[tuple[int, int]]) -> dict[int, set[int]]:
    children, parents = _build_graph(projects, dependencies)
    ids = [int(p["id"]) for p in projects]
    ancestors: dict[int, set[int]] = {i: set() for i in ids}

    def dfs(node: int, stack: set[int]) -> None:
        if node in stack:
            raise OptimizerError("dependency graph contains a cycle")
        if ancestors[node] and node not in stack:
            # still walk to detect cycles through this node
            pass
        stack.add(node)
        for parent in parents[node]:
            ancestors[node].add(parent)
            dfs(parent, stack)
            ancestors[node].update(ancestors[parent])
        stack.remove(node)

    seen: set[int] = set()

    def fill(node: int) -> None:
        if node in seen:
            return
        seen.add(node)
        for parent in parents[node]:
            fill(parent)
            ancestors[node].add(parent)
            ancestors[node].update(ancestors[parent])

    for i in ids:
        fill(i)

    # cycle check via topo
    topological_order(projects, dependencies)
    return ancestors


def optimize(
    projects: list[dict],
    dependencies: list[tuple[int, int]],
    budget_sgd: float,
    metric: str = "outcome",
) -> dict:
    if not projects:
        return {
            "selected": [],
            "excluded": [],
            "total_cost_sgd": 0.0,
            "total_outcome": 0.0,
            "total_elo": 0.0,
            "total_value": 0.0,
            "remaining_sgd": float(budget_sgd),
            "metric": metric,
        }

    by_id = {int(p["id"]): p for p in projects}
    ids = list(by_id)
    if len(ids) > 24:
        raise OptimizerError("more than 24 projects; exact search is not supported")

    order = topological_order(projects, dependencies)
    ancestors = ancestor_masks(projects, dependencies)
    budget_units = int(budget_sgd)  # whole SGD as specified

    cost = {i: int(round(float(by_id[i]["cost_sgd"]))) for i in ids}
    outcome = {i: float(by_id[i]["outcome"]) for i in ids}
    elo = {i: float(by_id[i]["elo_rating"]) for i in ids}
    value = {i: metric_value(metric, outcome[i], elo[i]) for i in ids}

    best = {
        "mask": 0,
        "value": -1.0,
        "cost": 0,
        "elo_sum": 0.0,
    }
    index = {pid: bit for bit, pid in enumerate(ids)}
    reverse = {bit: pid for pid, bit in index.items()}

    def bit_of(pid: int) -> int:
        return 1 << index[pid]

    def rec(pos: int, chosen: int, chosen_cost: int, chosen_value: float, chosen_elo: float) -> None:
        if chosen_cost > budget_units:
            return
        if pos == len(order):
            better = False
            if chosen_value > best["value"] + 1e-12:
                better = True
            elif abs(chosen_value - best["value"]) <= 1e-12:
                if chosen_cost < best["cost"]:
                    better = True
                elif chosen_cost == best["cost"]:
                    if chosen_elo > best["elo_sum"] + 1e-12:
                        better = True
                    elif abs(chosen_elo - best["elo_sum"]) <= 1e-12 and chosen < best["mask"]:
                        better = True
            if better:
                best["mask"] = chosen
                best["value"] = chosen_value
                best["cost"] = chosen_cost
                best["elo_sum"] = chosen_elo
            return

        pid = order[pos]
        # skip
        rec(pos + 1, chosen, chosen_cost, chosen_value, chosen_elo)
        # take if all ancestors selected
        anc_ok = True
        for anc in ancestors[pid]:
            if chosen & bit_of(anc) == 0:
                anc_ok = False
                break
        if anc_ok:
            rec(
                pos + 1,
                chosen | bit_of(pid),
                chosen_cost + cost[pid],
                chosen_value + value[pid],
                chosen_elo + elo[pid],
            )

    rec(0, 0, 0, 0.0, 0.0)

    selected = [reverse[bit] for bit in range(len(ids)) if best["mask"] & (1 << bit)]
    selected.sort()
    excluded = [i for i in ids if i not in selected]
    total_cost = sum(float(by_id[i]["cost_sgd"]) for i in selected)
    total_outcome = sum(outcome[i] for i in selected)
    total_elo = sum(elo[i] for i in selected)
    total_value = sum(value[i] for i in selected)
    return {
        "selected": selected,
        "excluded": excluded,
        "total_cost_sgd": total_cost,
        "total_outcome": total_outcome,
        "total_elo": total_elo,
        "total_value": total_value,
        "remaining_sgd": float(budget_sgd) - total_cost,
        "metric": metric,
    }
