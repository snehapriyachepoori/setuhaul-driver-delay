"""Shared test fixtures: every test gets its OWN fresh copy of the real database."""
import pytest

from src.config import policy
from src.db import connect, make_work_copy
from src.timeutil import to_epoch


@pytest.fixture
def db_path(tmp_path):
    return make_work_copy(tmp_path / "work.db")


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def now():
    """Scenario clock: 4 Aug 2026 10:00 India time (config/policy.toml [demo])."""
    return to_epoch(policy()["demo"]["now"])


def ts(clock: str) -> int:
    """'18:30' -> epoch on the snapshot day."""
    return to_epoch(f"2026-08-04T{clock}:00+05:30")
