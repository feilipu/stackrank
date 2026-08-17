# Data model

SQLite file: `data/stackrank.db` (created on first boot). All money is stored in **SGD**. Display conversion is derived.

`PRAGMA foreign_keys = ON` on every connection.

## `settings` (single row, `id = 1`)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Always 1 |
| budget_sgd | REAL NOT NULL | Must be > 0 |
| budget_currency | TEXT NOT NULL | `SGD` / `USD` / `MYR` — the currency the user last typed the goal in |
| usd_per_sgd | REAL NOT NULL | How many USD = 1 SGD. Default `0.74` |
| myr_per_sgd | REAL NOT NULL | How many MYR = 1 SGD. Default `3.45` |
| optimize_metric | TEXT NOT NULL | `outcome` / `elo` / `blend` |
| pool_eject_metric | TEXT NOT NULL | `elo` / `outcome` / `blend` |
| contest_active | INTEGER NOT NULL | 0/1 |
| contest_left_id | INTEGER NULL | Current pair A |
| contest_right_id | INTEGER NULL | Current pair B |
| contest_shown | INTEGER NOT NULL | Pairs presented this contest (including skips) |
| contest_decided | INTEGER NOT NULL | Pairs with a winner this contest |
| project_name | TEXT NOT NULL | Overall project title. Default `Untitled project`. 1–80 chars after trim. |

On first boot insert the singleton with `budget_sgd = 250000`, `budget_currency = 'SGD'`, `project_name = 'Untitled project'`.

Existing databases are migrated in `apply_schema`: if `project_name` is missing, `ALTER TABLE settings ADD COLUMN project_name TEXT NOT NULL DEFAULT 'Untitled project'`.

**Average conversion rate.** The “average” is the configured pair of rates, shown together so the user can see SGD, USD, and MYR at once. Editing either rate updates every displayed conversion immediately. There is no live FX API.

When the user sets the budget in USD or MYR, persist `budget_currency` and convert into `budget_sgd`:

```
budget_sgd = amount_usd / usd_per_sgd
budget_sgd = amount_myr / myr_per_sgd
```

## `projects`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| name | TEXT NOT NULL UNIQUE | trimmed, 1–80 chars |
| description | TEXT | optional, may be empty |
| cost_sgd | REAL NOT NULL | must be > 0 |
| outcome | REAL NOT NULL | must be > 0 |
| elo_rating | REAL NOT NULL | default 1500 |
| matches_played | INTEGER NOT NULL | default 0; increments on win or loss, not skip |
| wins | INTEGER NOT NULL | default 0 |
| losses | INTEGER NOT NULL | default 0 |
| created_at | TEXT NOT NULL | ISO-8601 UTC |
| updated_at | TEXT NOT NULL | ISO-8601 UTC |

## `project_dependencies`

| Column | Type | Notes |
|---|---|---|
| project_id | INTEGER NOT NULL | the dependent |
| depends_on_id | INTEGER NOT NULL | must exist first |
| PRIMARY KEY (project_id, depends_on_id) | | |
| FOREIGN KEY … ON DELETE CASCADE | | |

Invariants (enforced in service layer, tested):

- `project_id != depends_on_id`
- No cycles (DFS / topological failure rejects the write)
- Both IDs exist

## `pool_items`

The current In-Budget Success Pool. Order is explicit.

| Column | Type | Notes |
|---|---|---|
| project_id | INTEGER PK | FK projects ON DELETE CASCADE |
| position | INTEGER NOT NULL | 0 = highest priority (ejected last among unpinned) |
| pinned | INTEGER NOT NULL | 0/1; pinned items are never auto-ejected |

The pool must always satisfy:

- `sum(cost_sgd) <= budget_sgd` (within 1e-6)
- If A is in the pool and A depends on B, B is also in the pool

## `contest_matches`

History of beauty-contest decisions (skips included).

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| left_id | INTEGER NOT NULL | |
| right_id | INTEGER NOT NULL | |
| winner_id | INTEGER NULL | NULL means skip |
| k_factor | REAL NOT NULL | 32 |
| left_elo_before | REAL | |
| right_elo_before | REAL | |
| left_elo_after | REAL | NULL on skip |
| right_elo_after | REAL | NULL on skip |
| created_at | TEXT NOT NULL | ISO-8601 UTC |

## Seed (12 projects)

Seed only when `projects` is empty. All Elo start at 1500. Suggested set (costs in SGD):

| Name | Cost | Outcome | Depends on |
|---|---:|---:|---|
| Identity & SSO | 18000 | 80 | — |
| Billing ledger | 22000 | 70 | Identity & SSO |
| Customer portal | 35000 | 90 | Identity & SSO |
| Analytics warehouse | 40000 | 75 | — |
| Experiment platform | 28000 | 65 | Analytics warehouse |
| Mobile app | 45000 | 85 | Customer portal |
| Payments rails | 38000 | 88 | Billing ledger |
| Fraud rules | 20000 | 60 | Payments rails |
| Support desk | 15000 | 50 | Customer portal |
| Partner API | 26000 | 72 | Identity & SSO |
| Data quality | 16000 | 55 | Analytics warehouse |
| Launch campaign | 12000 | 40 | Customer portal, Payments rails |

Budget 250_000 SGD is tight enough that optimize, pool, and Elo disagree in interesting ways.

## Validation summary

| Rule | Where |
|---|---|
| cost > 0, outcome > 0 | create/update project |
| name unique, non-empty | create/update project |
| no self-dependency | dependency write |
| no cycles | dependency write |
| budget > 0 | settings write |
| rates > 0 | settings write |
| delete project | cascade deps, pool, matches; if contest pair uses it, end contest |
