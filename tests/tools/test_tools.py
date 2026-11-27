"""Step 5 check-it: typed errors, MISMATCH for other drivers, safe repeats, stage gate, auth (T-18)."""
import pytest

from src.auth import coordinator_pin_ok, start_driver_session
from src.capacity.handoff import missing_fields, open_handoffs
from src.stages import Stage
from src.tools.core import ConversationState, ToolContext, dispatch, tool_schemas


def ctx_for(conn, now, driver="DRV010", thread="T-TEST", stage=Stage.IDENTIFY):
    return ToolContext(conn, driver, thread, ConversationState(stage=stage), now)


# --- auth (T-18) ---
def test_known_phone_gets_session_unknown_does_not(conn):
    s = start_driver_session(conn, "+91 90000 10010")
    assert s.driver_id == "DRV010" and s.phone_masked.endswith("0010") and "9000" not in s.phone_masked
    assert start_driver_session(conn, "+91-9999999999") is None
    assert start_driver_session(conn, "hello") is None


def test_coordinator_pin(monkeypatch):
    monkeypatch.delenv("COORDINATOR_PIN", raising=False)
    assert not coordinator_pin_ok("")            # no PIN configured: nobody gets in
    monkeypatch.setenv("COORDINATOR_PIN", "4321")
    assert coordinator_pin_ok("4321") and not coordinator_pin_ok("1234")


# --- identity and ownership ---
def test_resolve_unique_shipment_moves_to_clarify(conn, now):
    c = ctx_for(conn, now)
    r = dispatch("resolve_shipment", {}, c)
    assert r["status"] == "UNIQUE" and r["shipment_id"] == "SHP1010" and c.state.stage == Stage.CLARIFY


def test_two_live_shipments_is_ambiguous(conn, now):
    r = dispatch("resolve_shipment", {}, ctx_for(conn, now, driver="DRV007"))   # SHP1007 and SHP1016
    assert r["status"] == "AMBIGUOUS" and {x["shipment_id"] for x in r["candidates"]} == {"SHP1007", "SHP1016"}


def test_other_drivers_shipment_is_mismatch_and_reveals_nothing(conn, now):
    c = ctx_for(conn, now, driver="DRV001")
    r = dispatch("resolve_shipment", {"hint": "SHP1010"}, c)
    assert r["status"] == "MISMATCH" and "DRV010" not in str(r) and c.state.shipment_id is None
    c.state.stage = Stage.CLARIFY
    r = dispatch("get_shipment_context", {"shipment_id": "SHP1010"}, c)
    assert r["ok"] is False and r["error"] == "MISMATCH"


def test_cancelled_shipment_not_rebookable(conn, now):
    r = dispatch("resolve_shipment", {"hint": "SHP1019"}, ctx_for(conn, now, driver="DRV008"))
    assert r["status"] == "NOT_ACTIVE"


# --- typed errors ---
def test_bad_arguments_return_typed_errors(conn, now):
    c = ctx_for(conn, now, stage=Stage.CLARIFY)
    c.state.shipment_id = "SHP1010"
    assert dispatch("get_shipment_context", {"shipment_id": "DROP TABLE"}, c)["error"] == "INVALID_ARGUMENTS"
    assert dispatch("get_shipment_context", {"shipment_id": "SHP1010", "driver_id": "DRV001"}, c)["error"] == "INVALID_ARGUMENTS"
    assert dispatch("get_shipment_context", {"shipment_id": "SHP9999"}, c)["error"] == "NOT_FOUND"
    assert dispatch("no_such_tool", {}, c)["error"] == "UNKNOWN_TOOL"


def test_stage_gate_blocks_confirm_early(conn, now):
    r = dispatch("confirm_booking", {"hold_id": "HOLD-0123456789"}, ctx_for(conn, now))
    assert r["error"] == "TOOL_NOT_ALLOWED_AT_STAGE"
    names = {t["function"]["name"] for t in tool_schemas(Stage.IDENTIFY)}
    assert names == {"resolve_shipment", "escalate_to_coordinator"}


# --- the happy path through the tools ---
def _to_offer(conn, now, driver="DRV010", thread="T-TEST"):
    c = ctx_for(conn, now, driver=driver, thread=thread)
    dispatch("resolve_shipment", {}, c)
    dispatch("record_eta_declaration", {"shipment_id": c.state.shipment_id, "kind": "NO_CHANGE"}, c)
    return c


def test_full_rebooking_and_safe_repeats(conn, now):
    c = _to_offer(conn, now)
    offers = dispatch("get_feasible_slots", {"shipment_id": "SHP1010"}, c)
    assert offers["status"] == "OPTIONS" and len(offers["options"]) == 3 and offers["nothing_reserved"]
    first = offers["options"][0]
    h1 = dispatch("hold_slot", {"offer_id": first["offer_id"]}, c)
    assert h1["status"] == "HELD" and c.state.stage == Stage.HOLD
    c.state.last_user_text = "maybe later"
    assert dispatch("confirm_booking", {"hold_id": h1["hold_id"]}, c)["error"] == "NEEDS_EXPLICIT_YES"
    c.state.last_user_text = "haan ji"
    r1 = dispatch("confirm_booking", {"hold_id": h1["hold_id"]}, c)
    assert r1["status"] == "CONFIRMED" and c.state.stage == Stage.DONE
    # same turn, same call again (a model retry): same answer, one booking
    c.state.stage = Stage.HOLD
    r2 = dispatch("confirm_booking", {"hold_id": h1["hold_id"]}, c)
    assert r2["appointment_id"] == r1["appointment_id"]
    n = conn.execute("SELECT COUNT(*) FROM appointments WHERE shipment_id='SHP1010' AND appointment_status='CONFIRMED'").fetchone()[0]
    assert n == 1


def test_offer_from_another_thread_cannot_be_held(conn, now):
    a = _to_offer(conn, now, thread="T-A")
    oid = dispatch("get_feasible_slots", {"shipment_id": "SHP1010"}, a)["options"][0]["offer_id"]
    b = _to_offer(conn, now, thread="T-B")
    dispatch("get_feasible_slots", {"shipment_id": "SHP1010"}, b)
    assert dispatch("hold_slot", {"offer_id": oid}, b)["error"] == "UNKNOWN_OFFER"


def test_shp1015_no_slot_escalates_automatically_with_complete_record(conn, now):
    c = _to_offer(conn, now, driver="DRV015")
    r = dispatch("get_feasible_slots", {"shipment_id": "SHP1015"}, c)
    assert r["status"] == "NO_FEASIBLE_SLOT" and c.state.stage == Stage.ESCALATE
    rows = open_handoffs(conn)
    assert len(rows) == 1 and rows[0]["reason_code"] == "NO_FEASIBLE_SLOT" and missing_fields(rows[0]) == []
    assert rows[0]["owner"].startswith("CON001")
    assert dispatch("hold_slot", {"offer_id": "OFF-0123456789"}, c)["error"] == "TOOL_NOT_ALLOWED_AT_STAGE"


def test_repair_time_needs_a_clock_time(conn, now):
    c = ctx_for(conn, now)
    dispatch("resolve_shipment", {}, c)
    r = dispatch("record_eta_declaration", {"shipment_id": "SHP1010", "kind": "REPAIR_TIME", "delay_minutes": 90}, c)
    assert r["error"] == "NEED_CLOCK_TIME" and c.state.stage == Stage.CLARIFY


def test_declared_clock_time_drives_options(conn, now):
    c = ctx_for(conn, now, driver="DRV013")
    dispatch("resolve_shipment", {}, c)
    dispatch("record_eta_declaration", {"shipment_id": "SHP1013", "kind": "CLOCK_TIME", "clock_time": "13:10"}, c)
    r = dispatch("get_feasible_slots", {"shipment_id": "SHP1013"}, c)
    assert r["eta"] == "13:10" and all(o["start"] >= "14:00" for o in r["options"])   # +30 min MEDIUM margin
