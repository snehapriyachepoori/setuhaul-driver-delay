"""T-14: connection safety settings, and the new tables enforce their rules."""
import hashlib
import sqlite3

import pytest

from src.config import ORIGINAL_DB
from src.db import connect
from src.migrate import migrate


def test_every_connection_has_foreign_keys_wal_and_busy_timeout(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_orphan_insert_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO slot_holds VALUES ('H1','NO-SUCH-SLOT','SHP1010','T1',NULL,'ACTIVE',1,1,1,'k1')")


def test_original_database_is_never_opened_for_writing():
    with pytest.raises(PermissionError):
        connect(ORIGINAL_DB)


def test_work_copy_leaves_original_unchanged(tmp_path):
    from src.db import make_work_copy

    before = hashlib.sha256(ORIGINAL_DB.read_bytes()).hexdigest()
    make_work_copy(tmp_path / "x.db")
    assert hashlib.sha256(ORIGINAL_DB.read_bytes()).hexdigest() == before


def test_migration_adds_only_new_tables_and_is_repeatable(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["slot_holds", "offers", "idempotency_log", "inbound_messages", "handoffs",
              "audit_events", "priority_policy", "slot_times", "outbox"]:
        assert t in names
    migrate(conn)  # second run must not fail or duplicate
    assert conn.execute("SELECT COUNT(*) FROM slot_times").fetchone()[0] == \
        conn.execute("SELECT COUNT(*) FROM appointment_slots").fetchone()[0]


def test_slot_times_are_epoch_numbers(conn):
    row = conn.execute("SELECT start_epoch, end_epoch FROM slot_times LIMIT 1").fetchone()
    assert isinstance(row[0], int) and row[1] - row[0] > 0


def test_partial_unique_index_allows_only_one_live_hold_per_slot(conn):
    conn.execute("INSERT INTO slot_holds VALUES ('H1','SLOT-JAI-061','SHP1010','T1',NULL,'ACTIVE',9e9,1,1,'k1')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO slot_holds VALUES ('H2','SLOT-JAI-061','SHP1015','T2',NULL,'ACTIVE',9e9,1,1,'k2')")
    # a released hold does not count, so a new live hold is fine afterwards
    conn.execute("UPDATE slot_holds SET state='RELEASED' WHERE hold_id='H1'")
    conn.execute("INSERT INTO slot_holds VALUES ('H2','SLOT-JAI-061','SHP1015','T2',NULL,'ACTIVE',9e9,1,1,'k2')")


def test_audit_events_are_append_only(conn):
    conn.execute("INSERT INTO audit_events(ts, actor, action) VALUES (1,'test','X')")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_events SET action='Y'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit_events")
