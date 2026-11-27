"""T-19 Duplicate message. Real data: THR009 repeats THR001's delay report from DRV006 (MSG015, flagged
is_duplicate) and today it created a second exception. Pass rule: one action; the second reply is the
stored first reply."""
from tests.failure.conftest import chat_bookings, current_booking, tools_called

REPORT = "SHP1006: Traffic after Shahpura. Reaching around 11:20. Any slot after 12?"


def test_same_delay_report_twice_acts_once(svc, conn):
    a = svc.handle("THR001", "DRV006", REPORT, msg_key="wa-9001")
    b = svc.handle("THR001", "DRV006", REPORT, msg_key="wa-9001")      # the channel retries the same message
    assert tools_called(a) == ["resolve_shipment", "record_eta_declaration", "get_feasible_slots"]
    assert tools_called(b) == [] and b["reply"] == a["reply"]
    assert conn.execute("SELECT COUNT(*) FROM offers WHERE thread_id='THR001'").fetchone()[0] == 3   # one set, not two
    assert conn.execute("SELECT COUNT(*) FROM audit_events WHERE action='TURN' AND thread_id='THR001'").fetchone()[0] == 1


def test_same_yes_twice_books_once(svc, conn):
    svc.handle("THR001", "DRV006", REPORT, msg_key="wa-9001")
    svc.handle("THR001", "DRV006", "1", msg_key="wa-9002")
    a = svc.handle("THR001", "DRV006", "yes take it", msg_key="wa-9003")
    b = svc.handle("THR001", "DRV006", "yes take it", msg_key="wa-9003")
    assert tools_called(a) == ["confirm_booking"] and tools_called(b) == []
    assert b["reply"] == a["reply"]
    assert chat_bookings(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1        # one message to the driver


def test_repeat_on_a_new_thread_books_nothing_by_itself(svc, conn):
    """The real THR009 repeat came on a NEW thread with a NEW channel id (wa-9009), so the key cannot
    catch it. What protects the driver: a repeat only shows options; nothing is held or booked until the
    driver picks and says yes again. Known gap (see docs/failure_tests.txt): it is not flagged as a repeat."""
    svc.handle("THR001", "DRV006", REPORT, msg_key="wa-9001")
    r = svc.handle("THR009", "DRV006", REPORT, msg_key="wa-9009")
    assert tools_called(r)[-1] == "get_feasible_slots" and r["stage"] == "OFFER"
    assert conn.execute("SELECT COUNT(*) FROM slot_holds").fetchone()[0] == 0
    assert chat_bookings(conn) == 0
    assert current_booking(conn, "SHP1006") == ("APT1006", "SLOT-JAI-045", "CONFIRMED")
