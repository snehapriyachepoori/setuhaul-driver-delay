"""T-21 Crash between "cancel old booking" and "create new". Pass rule: database unchanged; the old
booking is still active; and after the crash is gone the driver can finish normally."""
import pytest

import src.capacity.commit as commit
from tests.failure.conftest import chat_bookings, current_booking, tools_called


def test_crash_after_cancel_rolls_everything_back(svc, conn, monkeypatch):
    before = current_booking(conn, "SHP1010")
    svc.handle("T-21", "DRV010", "SHP1010 running late, will reach at 12:10")
    svc.handle("T-21", "DRV010", "1")
    hold_id = conn.execute("SELECT hold_id FROM slot_holds WHERE thread_id='T-21'").fetchone()[0]

    real_execute_count = {"n": 0}
    real_audit = commit._audit

    def crash_on_confirm(conn_, now, actor, action, *a, **k):
        # The old booking is already marked CANCELLED and the new one inserted when this runs.
        if action == "CONFIRMED":
            real_execute_count["n"] += 1
            raise RuntimeError("simulated power cut in the middle of the rebooking")
        return real_audit(conn_, now, actor, action, *a, **k)

    monkeypatch.setattr(commit, "_audit", crash_on_confirm)
    with pytest.raises(RuntimeError):
        svc.handle("T-21", "DRV010", "yes")
    assert real_execute_count["n"] == 1                                  # the crash really happened mid-commit

    # Nothing half-done: old booking live, no new booking, hold still ACTIVE, no message queued.
    assert current_booking(conn, "SHP1010") == before
    assert conn.execute("SELECT appointment_status, is_current FROM appointments "
                        "WHERE appointment_id='APT1010'").fetchone()[:] == ("CONFIRMED", 1)
    assert chat_bookings(conn) == 0
    assert conn.execute("SELECT state FROM slot_holds WHERE hold_id=?", (hold_id,)).fetchone()[0] == "ACTIVE"
    assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0

    # The crash is fixed; the driver says yes again and it works once.
    monkeypatch.setattr(commit, "_audit", real_audit)
    r = svc.handle("T-21", "DRV010", "yes")
    assert tools_called(r) == ["confirm_booking"] and r["stage"] == "DONE"
    assert chat_bookings(conn) == 1
