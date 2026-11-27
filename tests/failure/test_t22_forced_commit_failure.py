"""T-22 Force the commit to fail. Pass rule: the driver is never told "confirmed"."""
import sqlite3
from contextlib import contextmanager

import src.capacity.commit as commit
from tests.failure.conftest import chat_bookings, says_confirmed, statuses


@contextmanager
def failing_txn(conn):
    """Does all the work, then the disk refuses the COMMIT."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    finally:
        conn.execute("ROLLBACK")
    raise sqlite3.OperationalError("disk I/O error")


def test_commit_fails_driver_not_told_confirmed(svc, conn, monkeypatch):
    svc.handle("T-22", "DRV010", "SHP1010 running late, will reach at 12:10")
    svc.handle("T-22", "DRV010", "1")
    monkeypatch.setattr(commit, "write_txn", failing_txn)

    r = svc.handle("T-22", "DRV010", "yes")
    assert statuses(r) == [("confirm_booking", "DATABASE_BUSY")]
    assert not says_confirmed(r["reply"])
    assert chat_bookings(conn) == 0
    assert conn.execute("SELECT appointment_status FROM appointments WHERE appointment_id='APT1010'").fetchone()[0] == "CONFIRMED"
    assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_a_model_that_lies_after_a_failed_commit_is_overruled(conn, tmp_path, monkeypatch):
    """Even if the model ignores the error and writes 'confirmed', the output guard replaces it."""
    from src.agent.graph import DelayService
    from src.agent.llm import ModelReply
    from src.agent.rules_model import RulesModel
    from tests.conftest import ts

    class LiesAfterFailure(RulesModel):
        def chat(self, messages, tools):
            if messages[-1]["role"] == "tool" and "DATABASE_BUSY" in messages[-1]["content"]:
                return ModelReply("All done, your slot is confirmed!", [], "liar")
            return super().chat(messages, tools)

    s = DelayService(conn, LiesAfterFailure(), tmp_path / "ck2.db", clock=lambda: ts("10:00"))
    try:
        s.handle("T-22b", "DRV010", "SHP1010 running late, will reach at 12:10")
        s.handle("T-22b", "DRV010", "1")
        monkeypatch.setattr(commit, "write_txn", failing_txn)
        r = s.handle("T-22b", "DRV010", "yes")
    finally:
        s.close()
    assert not says_confirmed(r["reply"])
    assert any(x.get("code") == "OUTPUT_GUARD_REPLACED" for x in r["log"])
    assert chat_bookings(conn) == 0
