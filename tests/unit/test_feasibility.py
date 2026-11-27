"""T-06, T-12: feasibility checks and reason codes on the REAL snapshot."""
from src.capacity.feasibility import check_slot, find_feasible_slots, reason_summary
from src.timeutil import hhmm
from tests.conftest import ts

REEFER_SHIPMENTS = ["SHP1010", "SHP1015"]


def test_reefer_never_gets_a_standard_dock(conn, now):
    for s in REEFER_SHIPMENTS:
        feasible, checks = find_feasible_slots(conn, s, now=now)
        assert all(c.dock_type == "REEFER" for c in feasible)
        assert all("DOCK_TYPE" in c.reasons for c in checks if c.dock_type != "REEFER")


def test_standard_load_stays_off_reefer_and_heavy_docks(conn, now):
    feasible, _ = find_feasible_slots(conn, "SHP1013", now=now)
    assert feasible and all(c.dock_type == "STANDARD" for c in feasible)


def test_shp1015_has_zero_feasible_slots_with_reason_codes(conn, now):
    feasible, checks = find_feasible_slots(conn, "SHP1015", now=now)
    assert feasible == []
    summary = reason_summary(checks)
    assert {"DOCK_TYPE", "DOCK_DOWN", "TOO_EARLY"} <= set(summary)
    # Every D5 slot after the 18:30 ETA is under the maintenance event, even if its status says OPEN.
    d5_late = [c for c in checks if c.dock_code == "D5" and c.start >= ts("18:00")]
    assert d5_late and all("DOCK_DOWN" in c.reasons for c in d5_late)
    # Every D5 slot before then is too early for the truck.
    d5_early = [c for c in checks if c.dock_code == "D5" and c.start < ts("18:00")]
    assert all({"TOO_EARLY"} & set(c.reasons) or "CURRENT_BOOKING" in c.reasons for c in d5_early)


def test_shp1010_gets_the_d5_midday_slots(conn, now):
    feasible, _ = find_feasible_slots(conn, "SHP1010", now=now)
    assert [(c.dock_code, hhmm(c.start)) for c in feasible] == \
        [("D5", "12:00"), ("D5", "13:00"), ("D5", "14:00"), ("D5", "15:00"), ("D5", "16:00")]


def test_shp1014_is_refused_on_d1_for_weight(conn, now):
    feasible, checks = find_feasible_slots(conn, "SHP1014", now=now)
    d1 = [c for c in checks if c.dock_code == "D1"]
    assert d1 and all("WEIGHT" in c.reasons for c in d1)
    assert all(c.dock_code in ("D2", "D4") for c in feasible)   # the 25,000 kg standard docks


def test_dock_event_overrides_open_slot_status(conn, now):
    # D3 breakdown 09:15-13:00: the 09:00 slot is OPEN in appointment_slots but the dock is down.
    c = check_slot(conn, "SHP1013", "SLOT-JAI-030", now=ts("08:00"))
    assert "DOCK_DOWN" in c.reasons


def test_someone_elses_shipment_is_not_yours(conn, now):
    c = check_slot(conn, "SHP1013", "SLOT-JAI-020", now=now, driver_id="DRV001")
    assert "NOT_YOURS" in c.reasons


def test_cancelled_shipment_gets_nothing(conn, now):
    feasible, checks = find_feasible_slots(conn, "SHP1019", now=now)
    assert feasible == [] and all("NOT_ACTIVE" in c.reasons for c in checks)


def test_live_hold_by_another_thread_blocks_and_expired_hold_does_not(conn, now):
    slot = "SLOT-JAI-061"   # D5 12:00
    conn.execute("INSERT INTO slot_holds VALUES ('H1',?,'SHP1015','OTHER',NULL,'ACTIVE',?,?,?,'k1')",
                 (slot, now + 300, now, now))
    assert "HELD_BY_OTHER" in check_slot(conn, "SHP1010", slot, now=now, thread_id="ME").reasons
    assert check_slot(conn, "SHP1010", slot, now=now, thread_id="OTHER").feasible      # own hold
    assert check_slot(conn, "SHP1010", slot, now=now + 301, thread_id="ME").feasible   # expired: not trusted


def test_far_move_is_shown_but_needs_approval(conn, now):
    # SHP1010 was booked at 11:00; 15:00 is more than 3 hours later (check 10, T-12).
    c = check_slot(conn, "SHP1010", "SLOT-JAI-064", now=now)
    assert c.feasible and "SHIFT_OVER_LIMIT" in c.approval_reasons


def test_latest_finish_is_respected(conn, now):
    feasible, _ = find_feasible_slots(conn, "SHP1006", now=now, latest_finish=ts("13:00"))
    assert feasible and all(c.end <= ts("13:00") for c in feasible)


def test_p3_protected_last_slot_kept_for_high_priority(conn, now):
    # Driver must finish by 13:00: only two standard slots fit. The last one is kept for HIGH+.
    normal, checks = find_feasible_slots(conn, "SHP1013", now=now, latest_finish=ts("13:00"))  # NORMAL
    critical, _ = find_feasible_slots(conn, "SHP1014", now=now, latest_finish=ts("13:15"))     # CRITICAL
    assert len(normal) == 1 and any("PROTECTED" in c.reasons for c in checks)
    assert len(critical) == 2
