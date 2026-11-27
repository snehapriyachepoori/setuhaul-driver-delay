"""T-23 Expired hold. Pass rule: a confirm after the 5-minute expiry is refused."""
from tests.failure.conftest import chat_bookings, says_confirmed, statuses


def test_yes_after_expiry_is_refused(svc, conn, clock):
    svc.handle("T-23", "DRV010", "SHP1010 running late, will reach at 12:10")
    svc.handle("T-23", "DRV010", "1")
    hold_id = conn.execute("SELECT hold_id FROM slot_holds WHERE thread_id='T-23'").fetchone()[0]

    clock.now += 6 * 60                       # the driver answers six minutes later
    r = svc.handle("T-23", "DRV010", "yes")
    assert statuses(r)[0] == ("confirm_booking", "REFUSED")
    assert not says_confirmed(r["reply"])
    assert conn.execute("SELECT state FROM slot_holds WHERE hold_id=?", (hold_id,)).fetchone()[0] == "EXPIRED"
    assert chat_bookings(conn) == 0
    assert conn.execute("SELECT appointment_status FROM appointments WHERE appointment_id='APT1010'").fetchone()[0] == "CONFIRMED"


def test_yes_just_before_expiry_still_works(svc, conn, clock):
    """Control: the same flow inside the five minutes books once, so the test above can fail."""
    svc.handle("T-23c", "DRV010", "SHP1010 running late, will reach at 12:10")
    svc.handle("T-23c", "DRV010", "1")
    clock.now += 4 * 60
    r = svc.handle("T-23c", "DRV010", "yes")
    assert statuses(r) == [("confirm_booking", "CONFIRMED")]
    assert chat_bookings(conn) == 1
