"""Commit layer behaviour: idempotency, holds, expiry, stale options, all-or-nothing rebooking."""
import pytest

import src.capacity.commit as commit
from src.capacity.commit import (IdempotencyConflict, confirm_booking, hold_slot, live_claims_per_slot,
                                 release_hold)

SLOT_D5_12 = "SLOT-JAI-061"     # D5 12:00, feasible for SHP1010 (reefer)
SLOT_D4_13 = "SLOT-JAI-048"


def _hold(conn, now, sid="SHP1010", drv="DRV010", slot=SLOT_D5_12, thread="T1", key="k-hold"):
    return hold_slot(conn, shipment_id=sid, slot_id=slot, thread_id=thread, driver_id=drv,
                     idempotency_key=key, now=now)


def test_hold_then_confirm_rebooks_in_one_go(conn, now):
    h = _hold(conn, now)
    assert h["status"] == "ACTIVE" and h["expires_at"] == now + 300
    r = confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010",
                        idempotency_key="k-conf", now=now + 10)
    assert r["status"] == "CONFIRMED" and r["replaced_appointment_id"] == "APT1010"
    old = conn.execute("SELECT appointment_status, is_current FROM appointments WHERE appointment_id='APT1010'").fetchone()
    assert tuple(old) == ("CANCELLED", 0)
    assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
    actions = [a for (a,) in conn.execute("SELECT action FROM audit_events ORDER BY event_id")]
    assert actions == ["HOLD_PLACED", "CONFIRMED"]
    assert live_claims_per_slot(conn) == []


def test_same_key_twice_returns_same_answer_and_books_once(conn, now):
    h = _hold(conn, now)
    r1 = confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010", idempotency_key="k", now=now)
    r2 = confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010", idempotency_key="k", now=now)
    assert r2["appointment_id"] == r1["appointment_id"] and r2["replayed"] is True
    assert conn.execute("SELECT COUNT(*) FROM appointments WHERE shipment_id='SHP1010' AND appointment_status='CONFIRMED'").fetchone()[0] == 1
    assert _hold(conn, now) == {**h, "replayed": True}


def test_key_reused_for_a_different_request_is_rejected(conn, now):
    _hold(conn, now, key="dup")
    with pytest.raises(IdempotencyConflict):
        _hold(conn, now, slot="SLOT-JAI-062", key="dup")


def test_held_slot_is_refused_to_a_second_thread(conn, now):
    assert _hold(conn, now, thread="T1", key="a")["status"] == "ACTIVE"
    r = _hold(conn, now, sid="SHP1015", drv="DRV015", thread="T2", key="b")
    assert r["status"] == "REFUSED"


def test_expired_hold_is_not_trusted(conn, now):
    h = _hold(conn, now)
    r = confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010",
                        idempotency_key="late", now=now + 301)
    assert r["status"] == "REFUSED" and r["reason_codes"] == ["HOLD_EXPIRED"]
    # and another thread may now hold it
    assert _hold(conn, now + 302, sid="SHP1010", thread="T9", key="t9")["status"] == "ACTIVE"


def test_stale_option_refused_at_confirm(conn, now):
    """T-03: the slot is blocked between hold and confirm; the re-check inside confirm catches it."""
    h = _hold(conn, now)
    conn.execute("INSERT INTO dock_status_events VALUES ('T-EV','DOCK-JAI-D5','BREAKDOWN',"
                 "'2026-08-04T11:30:00+05:30','2026-08-04T14:00:00+05:30','test','2026-08-04T10:00:00+05:30')")
    r = confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010", idempotency_key="c", now=now)
    assert r["status"] == "REFUSED" and "DOCK_DOWN" in r["reason_codes"]
    assert conn.execute("SELECT appointment_status FROM appointments WHERE appointment_id='APT1010'").fetchone()[0] == "CONFIRMED"


def test_far_move_goes_to_approval_not_commit(conn, now):
    h = _hold(conn, now, slot="SLOT-JAI-064")   # D5 15:00, more than 3 h after the 11:00 booking
    assert h["needs_approval"] is True
    r = confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010", idempotency_key="c", now=now)
    assert r["status"] == "NEEDS_APPROVAL"
    assert conn.execute("SELECT state FROM slot_holds WHERE hold_id=?", (h["hold_id"],)).fetchone()[0] == "PENDING_APPROVAL"


def test_failure_mid_commit_leaves_no_half_state(conn, now, monkeypatch):
    """T-05: crash after the old booking is cancelled but before the commit -> nothing changes."""
    h = _hold(conn, now)

    def boom(*a, **k):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(commit, "_audit", boom)
    with pytest.raises(RuntimeError):
        confirm_booking(conn, hold_id=h["hold_id"], thread_id="T1", driver_id="DRV010", idempotency_key="c", now=now)
    assert conn.execute("SELECT appointment_status, is_current FROM appointments WHERE appointment_id='APT1010'").fetchone()[:] == ("CONFIRMED", 1)
    assert conn.execute("SELECT COUNT(*) FROM appointments WHERE appointment_id LIKE 'APT-%'").fetchone()[0] == 0
    assert conn.execute("SELECT state FROM slot_holds WHERE hold_id=?", (h["hold_id"],)).fetchone()[0] == "ACTIVE"
    assert conn.execute("SELECT COUNT(*) FROM idempotency_log WHERE key='c'").fetchone()[0] == 0


def test_release_hold_is_idempotent_and_frees_the_slot(conn, now):
    h = _hold(conn, now)
    assert release_hold(conn, hold_id=h["hold_id"], thread_id="T1", idempotency_key="r", now=now)["status"] == "RELEASED"
    assert release_hold(conn, hold_id=h["hold_id"], thread_id="T1", idempotency_key="r", now=now)["replayed"]
    assert _hold(conn, now, sid="SHP1010", thread="T2", key="x")["status"] == "ACTIVE"


def test_cannot_confirm_someone_elses_hold(conn, now):
    h = _hold(conn, now)
    r = confirm_booking(conn, hold_id=h["hold_id"], thread_id="INTRUDER", driver_id="DRV001",
                        idempotency_key="i", now=now)
    assert r["status"] == "REFUSED" and r["reason_codes"] == ["NO_SUCH_HOLD"]
