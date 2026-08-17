# Project Stack Ranker

Single-user local app for ranking sub-projects under a budget. Three complementary modes:

1. **Automatic optimize** — exact 0/1 knapsack over ancestor-closed sets (outcome, Elo, or a blend).
2. **In-budget success pool** — drag or click projects into a pool that never exceeds the budget. Lowest-metric unpinned items are ejected; pinned items stay.
3. **Elo beauty contest** — pairwise A/B comparisons (K = 32) with a live leaderboard.

Money is stored in **SGD**. USD and MYR are shown using configurable “foreign per 1 SGD” rates. You can type the budget (or a project cost) in any of the three currencies.

## Setup and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn stackrank.main:app --reload --app-dir src
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The first launch seeds 12 example projects and a S$250,000 budget.

Tabs: **Projects**, **Optimize**, **Pool**, **Contest**.

## Tests

```bash
source .venv/bin/activate
pytest
```

Tests use a temporary SQLite file and never touch `data/stackrank.db`.
