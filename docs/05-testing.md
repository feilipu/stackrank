# Testing

`pytest` from the repo root. Tests use a temp SQLite file (never the developer `data/stackrank.db`).

Provide `tests/conftest.py` with:

- `db_path` tmp_path fixture
- `conn` fixture applying schema
- `app` fixture overriding the db path
- `client` = `TestClient(app)`

## Unit — optimizer (`tests/test_optimizer.py`)

1. Empty set + budget → selected `[]`.
2. Single project cheaper than budget → selected.
3. Single project costlier than budget → excluded.
4. A depends on B; selecting A without B is impossible; if both fit, both selected.
5. Diamond dependency (A,B → C) does not double-count C’s cost.
6. Cycle in input raises a clear error (optimizer assumes DAG; service rejects earlier — still guard).
7. Metric `elo` vs `outcome` can change the winner (construct 2–3 projects).
8. Result is ancestor-closed and `total_cost <= budget`.

## Unit — Elo (`tests/test_elo.py`)

1. Equal 1500 vs 1500, A wins → A ≈ 1516, B ≈ 1484 (`K=32`).
2. Skip does not change ratings or W-L.
3. Reset returns everyone to 1500 / 0 / 0 / 0.
4. `expected(1500, 1700)` matches the closed-form.

## Unit — currency (`tests/test_currency.py`)

1. Round-trip USD → SGD → USD within 1e-6.
2. Display helper includes all three codes.

## Service — pool (`tests/test_services.py`)

1. Adding a project whose cost exceeds remaining ejects the lowest unpinned metric project.
2. Pinned project is not ejected; if nothing else can go, add is rejected.
3. Missing dependency blocks add.
4. Budget shrink ejects lowest unpinned; pinned over-budget stays and reports over_budget; ejecting a dependency also ejects its dependent.
5. Removing a dependency while a dependent is still pooled is blocked.
6. Reorder persists positions.

## Service — projects

1. Circular dependency rejected.
2. Self-dependency rejected.
3. Positive cost/outcome enforced.
4. Delete cascades out of pool.

## API / HTML (`tests/test_api.py`)

1. `GET /projects` is 200 and contains a seeded name after startup with empty db (seed runs).
2. `POST /projects` creates a row; second POST with same name is 422.
3. `POST /optimize/run` returns selected/excluded markup.
4. `POST /contest/start` then `choose` changes Elo in the leaderboard HTML.
5. `POST /pool/add/{id}` returns both columns.
6. `POST /settings/name` persists the overall title; empty name is 422.
7. `GET /export.md` is 200 `text/markdown`, contains a seeded name and `Budget:`.
8. `GET /export.html` is 200 `text/html` and uses green (`#ecfdf5`) vs amber (`#fff7ed`).
9. `GET /pool` includes `#pool-fill` with `data-fill` (`tests/test_pool_fill.py`).

## Manual / README smoke

README must include a Mac friend path (`./run.sh`) and the equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn stackrank.main:app --app-dir src --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Seed data visible. All four tabs load.

Runtime install is `requirements.txt`. Tests need `requirements-dev.txt` (pytest, httpx, playwright). No Playwright required to run the app. Optional later.
