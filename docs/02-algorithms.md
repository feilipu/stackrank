# Algorithms

## Currency

Base unit is SGD. Rates stored as “foreign per 1 SGD”.

```
to_usd(sgd) = sgd * usd_per_sgd
to_myr(sgd) = sgd * myr_per_sgd
from_usd(usd) = usd / usd_per_sgd
from_myr(myr) = myr / myr_per_sgd
```

Every money UI shows all three: `S$…  ·  US$…  ·  RM…`.

Budget form: amount + currency select. Persist both the typed currency and the converted SGD amount.

Blend value used by optimizer and pool ejection:

```
blend(p) = 0.6 * p.outcome + 0.4 * (p.elo_rating / 15.0)
```

Dividing Elo by 15 maps a typical 1500 rating onto the same order of magnitude as outcome scores (~100). Keep the constants in `stackrank/currency.py` as named constants.

## Elo (`K = 32`)

Standard expected-score update.

```
expected(a, b) = 1 / (1 + 10 ** ((b - a) / 400))
a' = a + K * (score_a - expected(a, b))
b' = b + K * (score_b - expected(b, a))
```

- A wins: `score_a = 1`, `score_b = 0`
- B wins: opposite
- Skip: no Elo change, no matches/wins/losses increment; still recorded in `contest_matches` and `contest_shown`

After a decisive match:

- increment both `matches_played`
- increment winner `wins`, loser `losses`
- write new ratings

Reset Elo: set every project to 1500 / 0 / 0 / 0 and delete `contest_matches`. End any active contest.

### Pairing

When a contest is started (or after a decision):

1. Eligible projects: all projects (need ≥ 2 or the contest cannot start).
2. Prefer pairs that have never been compared (unordered pair `{i,j}` not in history as a decisive or skipped match).
3. Among remaining unseen pairs, pick the two closest Elo ratings (smallest `|elo_i - elo_j|`).
4. If every unordered pair has been shown, wrap and pick the closest-Elo pair that was shown least recently.
5. Randomize left/right so the same project is not always card A.

Progress: `contest_decided / C(n,2)` displayed as percent, plus “N of M unique pairs decided”. User can stop at any time (`contest_active = 0`, clear current pair).

## Optimizer — 0/1 knapsack with precedence

Exact algorithm for `n ≤ 30`. If `n > 30`, still run the same DP but document that runtime is `O(n * B_units)`; discretize money to whole SGD (round costs to nearest integer SGD) so the DP is tractable.

### Step 1 — graph

Directed edge `dep → project` (“dep must come before project”). Reject if not a DAG.

### Step 2 — topological order

Kahn or DFS. Process projects in topo order so a project is only considered after all ancestors.

### Step 3 — DP

Let `cost[i]` be integer SGD, `value[i]` be the chosen metric (`outcome`, `elo`, or `blend`), `B` = floor(budget_sgd).

Because of precedence, a project may only be taken if all of its transitive dependencies are also taken. **Implementation choice (required):** expand each project into a *closure*:

```
closure_cost(i)  = cost(i) + cost of all ancestors not already implied
```

Do **not** use naive “must-include-ancestors at take time” without sharing, or the DP double-counts shared dependencies.

Required approach: **bitmask DP** when `n ≤ 24`, otherwise **topo DP over feasible ancestor-closed sets**.

Preferred implementation (`n ≤ 24`, seed is 12):

- Index projects `0..n-1`.
- `anc_mask[i]` = bitset of strict ancestors of i (not including i).
- `feasible(mask)` iff for every bit i in mask, `anc_mask[i] ⊆ mask`.
- Enumerate only ancestor-closed subsets via recursion in topo order: at project i, either skip, or take if `anc_mask[i] ⊆ chosen_so_far`.
- Prune when `cost > B`.
- Track best `value`, breaking ties by **lower cost**, then **higher Elo sum**, then **smaller mask** (stable).

This is exact and simple for n=12–24. If n>24, fall back to PuLP ILP (optional extra) or the same recursion with aggressive cost pruning; still must return a feasible ancestor-closed set.

Return:

```
{
  selected: [project ids],
  excluded: [project ids],
  total_cost_sgd,
  total_outcome,
  total_elo,
  total_value,          # according to metric
  remaining_sgd,
  metric
}
```

Do not persist the optimize result unless the user clicks “Apply to pool”. Apply replaces `pool_items` with the selected set, positions by descending value, unpinned.

## Pool ejection

Inputs: current pool (ordered), incoming project P, budget, eject metric, pins.

Algorithm when adding P (from Available → Pool):

1. If P is already in the pool, ignore.
2. If any direct-or-transitive dependency of P is not in the pool, **block** the add and return an HTMX error fragment listing missing dependency names. Do not auto-add dependencies (user must pull them in).
3. Tentatively append P at the lowest priority (end of list).
4. While `sum(costs) > budget`:
   - Candidates = unpinned items **except P** (never eject the item just added if something else can go). If still over, P itself may be rejected with “does not fit even after ejecting unpinned projects”.
   - Eject the candidate with the **lowest** metric (`elo` / `outcome` / `blend`). Tie-break: lowest position (already low priority), then highest id.
5. Persist the new pool and return both columns + totals.

Removing P from the pool:

- If any remaining item depends on P (directly or transitively), **block** and name the dependents. User must remove dependents first.

Reordering inside the pool updates `position` only. Reorder must not break budget (budget already held).

Pin toggle: pinned items are skipped by auto-eject. Pinning never changes membership.

Live totals always shown: total cost (3 currencies), remaining budget, total outcome, total Elo, count.
