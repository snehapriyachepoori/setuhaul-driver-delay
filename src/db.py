"""One way to open the database, so every connection has the same safety settings.

- foreign_keys=ON  : SQLite switches this OFF on every new connection (audit I-16).
- WAL journal      : readers do not block the single writer.
- busy_timeout     : wait for the write lock instead of failing at once.
- isolation_level=None : we write BEGIN IMMEDIATE ourselves, so we control transactions.

We never write to data/setuhaul_original.db. `make_work_copy` copies it first.
"""
from __future__ import annotations

import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.config import ORIGINAL_DB, ROOT

BUSY_TIMEOUT_MS = 10_000


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path).resolve()
    if p == ORIGINAL_DB.resolve():
        raise PermissionError("Refusing to open the original database for writing; use make_work_copy().")
    conn = sqlite3.connect(str(p), isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


def make_work_copy(dest: str | Path | None = None, source: str | Path = ORIGINAL_DB) -> Path:
    """Copy the original database to a fresh work file and add the new tables."""
    from src.migrate import migrate

    if dest is None:
        dest = ROOT / "data" / f"work_{uuid.uuid4().hex[:8]}.db"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(dest) + suffix).unlink(missing_ok=True)
    shutil.copyfile(source, dest)
    conn = connect(dest)
    try:
        migrate(conn)
    finally:
        conn.close()
    return dest


@contextmanager
def write_txn(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE takes the write lock BEFORE we read, so our re-check is not stale."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
