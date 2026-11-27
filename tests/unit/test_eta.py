"""T-07: resolved ETA rule (architecture 9.4)."""
import pytest

from src.capacity.eta import (DelayKind, Declaration, NeedClockTime, declaration_from_driver,
                              resolve_eta)
from src.timeutil import hhmm, to_epoch
from tests.conftest import ts


def test_utc_z_time_is_converted_to_india_time():
    # The brief's example: 06:15:00Z is 11:45 in India, not 06:15.
    assert hhmm(to_epoch("2026-08-04T06:15:00Z")) == "11:45"
    assert to_epoch("2026-08-04T06:15:00Z") == to_epoch("2026-08-04T11:45:00+05:30")


def test_shp1013_low_confidence_eta_gets_60_minute_margin(conn):
    e = resolve_eta(conn, "SHP1013")
    assert (e.source, e.confidence, e.margin_min) == ("DRIVER_DECLARED", "LOW", 60)
    assert e.planning_epoch == ts("11:00") + 60 * 60


def test_margins_come_from_config_not_code(conn):
    assert resolve_eta(conn, "SHP1015").margin_min == 15     # HIGH
    assert resolve_eta(conn, "SHP1010").margin_min == 30     # no ETA rows -> plan, MEDIUM


def test_newest_driver_update_used_for_shp1006(conn):
    e = resolve_eta(conn, "SHP1006")   # 10:50 MEDIUM then 11:20 HIGH
    assert hhmm(e.eta_epoch) == "11:20" and e.confidence == "HIGH"


def test_later_of_driver_and_warehouse_wins(conn):
    conn.execute("INSERT INTO eta_updates(eta_update_id, shipment_id, source_type, declared_eta_ts, "
                 "confidence_code, created_at) VALUES ('T-W1','SHP1006','WAREHOUSE_ESTIMATE',"
                 "'2026-08-04T11:50:00+05:30','LOW','2026-08-04T09:40:00+05:30')")
    e = resolve_eta(conn, "SHP1006")
    assert e.source == "WAREHOUSE_ESTIMATE" and hhmm(e.eta_epoch) == "11:50" and e.margin_min == 60


def test_confirmed_driver_statement_beats_database_estimates(conn):
    e = resolve_eta(conn, "SHP1013", Declaration(ts("11:30"), "MEDIUM"))
    assert e.source == "DRIVER_CONFIRMED_IN_CHAT" and e.planning_epoch == ts("12:00")


def test_operations_override_wins_outright(conn):
    conn.execute("INSERT INTO eta_updates(eta_update_id, shipment_id, source_type, declared_eta_ts, "
                 "confidence_code, created_at) VALUES ('T-O1','SHP1013','OPERATIONS_OVERRIDE',"
                 "'2026-08-04T10:40:00+05:30','HIGH','2026-08-04T09:00:00+05:30')")
    e = resolve_eta(conn, "SHP1013", Declaration(ts("11:30")))
    assert e.source == "OPERATIONS_OVERRIDE" and hhmm(e.eta_epoch) == "10:40"


def test_repair_time_is_not_an_arrival_time():
    with pytest.raises(NeedClockTime):
        declaration_from_driver(DelayKind.REPAIR_TIME, delay_minutes=90)


def test_arrival_delay_adds_to_current_eta():
    d = declaration_from_driver(DelayKind.ARRIVAL_DELAY, base_eta_epoch=ts("17:00"), delay_minutes=90)
    assert hhmm(d.eta_epoch) == "18:30"
