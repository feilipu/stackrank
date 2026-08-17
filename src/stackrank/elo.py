"""Elo updates (K=32) and pairwise contest pairing."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from itertools import combinations

K_FACTOR = 32.0
DEFAULT_ELO = 1500.0


def expected(a: float, b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def update_ratings(a: float, b: float, score_a: float, k: float = K_FACTOR) -> tuple[float, float]:
    score_b = 1.0 - score_a
    new_a = a + k * (score_a - expected(a, b))
    new_b = b + k * (score_b - expected(b, a))
    return new_a, new_b


def choose_pair(
    projects: list[dict],
    shown_pairs: set[tuple[int, int]],
    recent_order: list[tuple[int, int]],
    rng: random.Random | None = None,
) -> tuple[int, int] | None:
    """Return (left_id, right_id) or None if fewer than 2 projects.

    Prefer unseen unordered pairs with the closest Elo. If every pair has been
    shown, pick the closest-Elo pair that appeared least recently.
    """
    rng = rng or random.Random()
    ids = [int(p["id"]) for p in projects]
    if len(ids) < 2:
        return None
    elo = {int(p["id"]): float(p["elo_rating"]) for p in projects}

    def unordered(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    all_pairs = [unordered(a, b) for a, b in combinations(ids, 2)]
    unseen = [p for p in all_pairs if p not in shown_pairs]
    candidates = unseen if unseen else all_pairs

    def closeness(pair: tuple[int, int]) -> float:
        return abs(elo[pair[0]] - elo[pair[1]])

    last_seen = {pair: idx for idx, pair in enumerate(recent_order)}
    if unseen:
        best_close = min(closeness(p) for p in candidates)
        closest = [p for p in candidates if math.isclose(closeness(p), best_close)]
        pair = rng.choice(closest)
    else:
        # least recently shown, then closest elo
        def recency_key(pair: tuple[int, int]) -> tuple[int, float]:
            return (last_seen.get(pair, -1), closeness(pair))

        pair = min(candidates, key=recency_key)

    left, right = pair
    if rng.random() < 0.5:
        left, right = right, left
    return left, right


def unique_pair_count(n: int) -> int:
    if n < 2:
        return 0
    return n * (n - 1) // 2


def shown_set_from_rows(rows: list) -> tuple[set[tuple[int, int]], list[tuple[int, int]]]:
    shown: set[tuple[int, int]] = set()
    recent: list[tuple[int, int]] = []
    for row in rows:
        a, b = int(row["left_id"]), int(row["right_id"])
        pair = (a, b) if a < b else (b, a)
        shown.add(pair)
        recent.append(pair)
    return shown, recent


def group_shown_counts(recent: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for pair in recent:
        counts[pair] += 1
    return counts
