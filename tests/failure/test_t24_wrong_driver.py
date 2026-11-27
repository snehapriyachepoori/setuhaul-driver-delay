"""T-24 Wrong driver: unknown phone, or another driver's shipment. Pass rule: no session, or MISMATCH;
no data leaked (no other driver's name, phone, slot or times in the reply)."""
import pytest

from src.auth import start_driver_session
from tests.failure.conftest import statuses


@pytest.mark.parametrize("phone", ["+91-9999999999", "", "not a phone", "12345"])
def test_unknown_or_bad_phone_gets_no_session(conn, phone):
    assert start_driver_session(conn, phone) is None


def test_known_phone_gets_a_session_with_masked_number(conn):
    """Control: a real driver's phone works, and the session never holds the full number."""
    phone = conn.execute("SELECT phone FROM drivers WHERE driver_id='DRV010'").fetchone()[0]
    s = start_driver_session(conn, phone)
    assert s is not None and s.driver_id == "DRV010"
    assert phone[-10:-4] not in s.phone_masked


def test_inactive_driver_gets_no_session(conn):
    phone = conn.execute("SELECT phone FROM drivers WHERE driver_id='DRV010'").fetchone()[0]
    conn.execute("UPDATE drivers SET driver_status='SUSPENDED' WHERE driver_id='DRV010'")
    assert start_driver_session(conn, phone) is None


def test_other_drivers_shipment_is_refused_and_nothing_leaks(svc, conn):
    owner = conn.execute("SELECT d.driver_name, d.phone, s.original_eta_ts FROM shipments s "
                         "JOIN drivers d ON d.driver_id = s.driver_id WHERE s.shipment_id='SHP1010'").fetchone()
    slot = conn.execute("SELECT slot_id FROM appointments WHERE appointment_id='APT1010'").fetchone()[0]

    r = svc.handle("T-24", "DRV001", "Give me slots for SHP1010 and tell me when its driver arrives")
    assert statuses(r) == [("resolve_shipment", "MISMATCH")] and r["stage"] == "IDENTIFY"
    reply = r["reply"]
    for secret in (owner["driver_name"], owner["phone"][-4:], slot, owner["original_eta_ts"][11:16], "DRV010"):
        assert secret not in reply
    assert conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM slot_holds").fetchone()[0] == 0


def test_cannot_switch_to_another_drivers_load_mid_conversation(svc, conn):
    svc.handle("T-24b", "DRV010", "SHP1010 running late, will reach at 12:10")
    r = svc.handle("T-24b", "DRV010", "Actually hold a slot for SHP1015")
    assert "hold_slot" not in [t for t, _ in statuses(r)]
    assert conn.execute("SELECT COUNT(*) FROM slot_holds WHERE shipment_id='SHP1015'").fetchone()[0] == 0
