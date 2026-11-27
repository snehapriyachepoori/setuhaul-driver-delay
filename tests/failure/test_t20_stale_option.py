"""T-20 Stale option: the driver is shown slot X, a coordinator blocks X, then the driver says "take it".
Pass rule: refused with a reason and fresh options; no booking."""
from tests.failure.conftest import chat_bookings, current_booking, statuses


def _offer_slots(conn, thread):
    return {o: s for o, s in conn.execute("SELECT offer_id, slot_id FROM offers WHERE thread_id=?", (thread,))}


def test_blocked_after_shown_is_refused_and_new_options_given(svc, conn):
    before_booking = current_booking(conn, "SHP1010")
    svc.handle("T-20", "DRV010", "SHP1010 running late, will reach at 12:10")
    shown = _offer_slots(conn, "T-20")
    x = conn.execute("SELECT slot_id FROM offers WHERE thread_id='T-20' AND shown_rank=1").fetchone()[0]

    # A coordinator blocks slot X while the driver is reading the options.
    conn.execute("UPDATE appointment_slots SET slot_status='BLOCKED' WHERE slot_id=?", (x,))

    r = svc.handle("T-20", "DRV010", "1")                     # "take the first one"
    assert statuses(r)[:2] == [("hold_slot", "REFUSED"), ("get_feasible_slots", "OPTIONS")]
    assert r["stage"] == "OFFER"
    reasons = [d for (d,) in conn.execute(
        "SELECT detail_json FROM audit_events WHERE action='HOLD_REFUSED' AND thread_id='T-20'")]
    assert len(reasons) == 1 and "SLOT_BLOCKED" in reasons[0]          # the reason is recorded
    fresh = [s for o, s in _offer_slots(conn, "T-20").items() if o not in shown]
    assert fresh and x not in fresh                                  # new options, without slot X
    assert conn.execute("SELECT COUNT(*) FROM slot_holds").fetchone()[0] == 0
    assert chat_bookings(conn) == 0 and current_booking(conn, "SHP1010") == before_booking
