# Project Stack Ranker

**Status (2026-09-18):** shipped on [`main`](https://github.com/feilipu/stackrank). Python 3.11+ / FastAPI / SQLite. Version `1.0.0`. Product spec: [`stackrank_prompt.txt`](stackrank_prompt.txt). Agent notes: [`docs/handoff.md`](docs/handoff.md).

Single-user local app for ranking sub-projects under a budget. Three complementary modes:

1. **Automatic optimize** — exact 0/1 knapsack over ancestor-closed sets (outcome, Elo, or a blend).
2. **In-budget success pool** — drag or click projects into a pool that never exceeds the budget. Lowest-metric unpinned items are ejected; pinned items stay. Sub-projects can **exclude** each other (option A or B, not both).
3. **Elo beauty contest** — pairwise A/B comparisons (K = 32) with a live leaderboard.

Money is stored in **SGD**. USD and MYR are shown using configurable “foreign per 1 SGD” rates. You can type the budget (or a project cost) in any of the three currencies.

## Run on a Mac (technical friend)

You need **Python 3.11 or newer**. Check with `python3 --version`. If that is missing or too old, install from [python.org/downloads](https://www.python.org/downloads/) (the official installer is enough; Xcode is not required). The **first** launch needs internet so `pip` can fetch FastAPI and friends.

Then, in Terminal, from this folder:

```bash
chmod +x run.sh install.sh   # once
./run.sh
```

`./install.sh` does the same thing as `./run.sh`: it creates `.venv`, installs the runtime packages, starts the app at [http://127.0.0.1:8000](http://127.0.0.1:8000), and opens your default browser. Stop with **Ctrl+C**.

The first launch with an empty `data/` folder seeds 12 example projects and a S$250,000 budget. After that, everything lives in `data/stackrank.db` next to `run.sh` (gitignored). Point at another file with `STACKRANK_DB=/path/to/file.db`. Host/port: `STACKRANK_HOST` / `STACKRANK_PORT`.

Tabs: **Projects**, **Optimize**, **Pool**, **Contest**, **Export**. The header title is the overall project name (rename in place). Export is a compact coloured report (green = in the success pool, amber = excluded) plus a contractor list of accepted projects; pick SGD / USD / MYR on that tab. In-pool items are green; out-of-pool items are amber.

Equivalent manual commands (same result as `./run.sh`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn stackrank.main:app --app-dir src --host 127.0.0.1 --port 8000
```

If port 8000 is taken: `STACKRANK_PORT=8001 ./run.sh`. To use a specific database:

```bash
STACKRANK_DB="$PWD/data/stackrank.db" ./run.sh
```

No Node, Docker, or CDN is required. After the first `pip install`, later launches can reuse the venv (HTMX, Tailwind, and SortableJS are vendored in `static/vendor/`).

## Share a copy

From a development checkout:

```bash
./scripts/pack.sh
```

That writes `dist/stackrank-YYYYMMDD.zip` without `.venv`, your live database, logs, or `.git`. Unzip on the other Mac, `cd stackrank`, and run `./run.sh` (or `./install.sh`).

To also hand over your current projects, copy `data/stackrank.db` into their `data/` folder (create `data/` if needed) **before** they start the app, or replace theirs after the first launch.

## Tests (this repo)

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Tests use a temporary SQLite file and never touch `data/stackrank.db`. Playwright is only for the optional `scripts/smoke_tabs.py` check, not for running the app.

As of 2026-09-18 the suite collects **105** tests (**104** pass). One known drift: `tests/test_services.py::test_missing_dependency_blocks_add_to_pool` still expects a 409, but adding to the pool now pulls missing dependencies when they fit.

Developers who want auto-reload:

```bash
source .venv/bin/activate
uvicorn stackrank.main:app --reload --app-dir src --host 127.0.0.1 --port 8000
```

## Docs / GitHub

- Product spec (shipped behaviour): [`stackrank_prompt.txt`](stackrank_prompt.txt)
- Agent handoff: [`docs/handoff.md`](docs/handoff.md)
- Design notes: [`docs/00-overview.md`](docs/00-overview.md) … [`docs/10-export-dark-theme.md`](docs/10-export-dark-theme.md)
- Rebuild slices (only if starting over): [`implementation_plan.md`](implementation_plan.md)
- License: MIT

Remote: https://github.com/feilipu/stackrank. Do not commit `.venv/`, `data/*.db`, or `dist/`.
