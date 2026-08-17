"""Shared pytest fixtures used across the suite."""

from __future__ import annotations

import os


# Point every request at a throwaway on-disk DB *before* importing stackrank.main,
# so nothing ever touches the developer's data/stackrank.db during tests.
os.environ.setdefault("STACKRANK_DB", "tests_placeholder.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import stackrank.main as m  # noqa: E402


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "test_db.db"


@pytest.fixture()
def conn(db_path):
    """A live write-ready connection for direct service-level tests."""
    from stackrank.db import apply_schema, connect

    c = connect(db_path)
    apply_schema(c)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture()
def client(db_path):
    """A FastAPI TestClient whose requests all hit this test's temp DB."""
    m.set_db_path(str(db_path))
    m.LAST_OPTIMIZE = None
    with TestClient(m.app) as tc:
        yield tc

    m.set_db_path(None)
