"""check_slot(): is this slot available to THIS shipment at THIS moment? (architecture 9.5)

"Available" is not a property of a slot. It is a property of a slot for one shipment at one
moment. The same function runs when options are shown, when a hold is placed and again inside
the confirm transaction. It returns reason codes, never a guess.

Checks (reason code when it fails):
  1  shipment active, this driver's, not docked  NOT_ACTIVE, NOT_YOURS, ALREADY_DOCKED
  2  slot open, not booked, not held by another  SLOT_BLOCKED, CURRENT_BOOKING, TAKEN, HELD_BY_OTHER
  3  dock active, no dock event overlapping      DOCK_DOWN      (dock events override slot status)
  4  dock type and weight fit the load           DOCK_TYPE, WEIGHT
  5  inside facility hours                       OUTSIDE_HOURS
  6  start at/after ETA + margin and after now   TOO_EARLY
  7  finish at/before driver's latest finish     TOO_LATE_FOR_YOU
  8  no overlap with another booking/hold        OVERLAP
  9  priority policy P-3 allows it               PROTECTED      (set level: find_feasible_slots)
  10 approval needed (shown, but a person must confirm)  flags: SHIFT_OVER_LIMIT, OTHER_DAY, AFTER_LAST_START
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from src.capacity.eta import Declaration, ResolvedEta, resolve_eta
from src.config import policy
from src.timeutil import at_clock, ist_date, to_epoch


@dataclass
class SlotCheck:
    slot_id: str
    dock_id: str
    dock_code: str
    dock_type: str
    start: int
    end: int
    reasons: list[str] = field(default_factory=list)
    approval_reasons: list[str] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return not self.reasons

    @property
    def needs_approval(self) -> bool:
        return bool(self.approval_reasons)


class Context:
    """Everything one feasibility run reads, loaded once from the database."""

    def __init__(self, conn: sqlite3.Connection, shipment_id: str):
        self.p = policy()
        self.ship = conn.execute("SELECT * FROM shipments WHERE shipment_id=?", (shipment_id,)).fetchone()
        if self.ship is None:
            raise KeyError(f"unknown shipment {shipment_id}")
        fac_id = self.ship["destination_facility_id"]
        self.facility = conn.execute("SELECT * FROM facilities WHERE facility_id=?", (fac_id,)).fetchone()
        self.docks = {r["dock_id"]: r for r in conn.execute("SELECT * FROM docks WHERE facility_id=?", (fac_id,))}
        self.slots = conn.execute(
            "SELECT s.slot_id, s.dock_id, s.slot_status, t.start_epoch, t.end_epoch "
            "FROM appointment_slots s JOIN slot_times t USING(slot_id) WHERE s.facility_id=? "
            "ORDER BY t.start_epoch, s.dock_id", (fac_id,)).fetchall()
        self.slot_by_id = {r["slot_id"]: r for r in self.slots}
        self.events = [
            (r["dock_id"], to_epoch(r["event_start_ts"]),
             to_epoch(r["event_end_ts"]) if r["event_end_ts"] else 2**62, r["event_type"])
            for r in conn.execute("SELECT * FROM dock_status_events")
            if r["event_type"] in self.p["feasibility"]["blocking_dock_events"]
        ]
        self.rules = {r["rule_type"]: r["rule_value"] for r in conn.execute(
            "SELECT rule_type, rule_value FROM facility_rules WHERE facility_id=? AND active_flag=1", (fac_id,))}
        active = self.p["feasibility"]["active_appointment_statuses"]
        ph = ",".join("?" * len(active))
        self.active_appts = conn.execute(
            f"SELECT a.appointment_id, a.shipment_id, a.slot_id, s.dock_id, t.start_epoch, t.end_epoch "
            f"FROM appointments a JOIN appointment_slots s USING(slot_id) JOIN slot_times t USING(slot_id) "
            f"WHERE a.appointment_status IN ({ph})", active).fetchall()
        self.current_appt = next((a for a in self.active_appts if a["shipment_id"] == shipment_id), None)
        self.holds = conn.execute(
            "SELECT h.hold_id, h.slot_id, h.thread_id, h.shipment_id, h.state, h.expires_at, s.dock_id, "
            "t.start_epoch, t.end_epoch FROM slot_holds h JOIN appointment_slots s USING(slot_id) "
            "JOIN slot_times t USING(slot_id) WHERE h.state IN ('ACTIVE','PENDING_APPROVAL')").fetchall()
        self.checkin = conn.execute(
            "SELECT * FROM facility_checkins WHERE shipment_id=?", (shipment_id,)).fetchone()

    # --- helpers -------------------------------------------------------------
    def live_holds(self, now: int):
        """Expiry is checked on every read; a hold past expires_at is not trusted."""
        return [h for h in self.holds if h["state"] == "PENDING_APPROVAL" or h["expires_at"] > now]

    def needs_reefer(self) -> bool:
        return bool(self.ship["temperature_control_required"]) or self.ship["required_dock_type"] == "REEFER"

    def needs_heavy(self) -> bool:
        limit = int(self.rules.get("HEAVY_DOCK_REQUIRED_KG", 10**9))
        return self.ship["required_dock_type"] == "HEAVY" or self.ship["load_weight_kg"] > limit

    def dock_type_ok(self, dock) -> bool:
        if self.needs_reefer():
            return bool(dock["supports_refrigerated"])
        if self.needs_heavy():
            return dock["dock_type"] == "HEAVY"
        return dock["dock_type"] == "STANDARD"   # keep standard loads off scarce docks

    def plan_reference(self) -> int:
        if self.current_appt is not None:
            return self.current_appt["start_epoch"]
        return to_epoch(self.ship["original_eta_ts"])


def _evaluate(ctx: Context, slot, *, driver_id: str | None, eta: ResolvedEta, now: int,
              latest_finish: int | None, thread_id: str | None) -> SlotCheck:
    p = ctx.p
    dock = ctx.docks[slot["dock_id"]]
    start, end = slot["start_epoch"], slot["end_epoch"]
    c = SlotCheck(slot["slot_id"], dock["dock_id"], dock["dock_code"], dock["dock_type"], start, end)
    r = c.reasons
    ship = ctx.ship
    unload_s = int(ship["expected_unload_min"]) * 60
    busy_end = max(end, start + unload_s) if p["feasibility"]["overrun_blocks_next_slot"] else end

    # 1 shipment
    if ship["current_status"] in ("IN_DOCK", "COMPLETED") or (ctx.checkin is not None and ctx.checkin["dock_in_ts"]):
        r.append("ALREADY_DOCKED")
    elif ship["current_status"] not in p["feasibility"]["rebookable_shipment_statuses"]:
        r.append("NOT_ACTIVE")
    if driver_id is not None and ship["driver_id"] != driver_id:
        r.append("NOT_YOURS")

    # 2 slot open, not booked, not held by another thread
    if slot["slot_status"] != "OPEN":
        r.append("SLOT_BLOCKED")
    appt = next((a for a in ctx.active_appts if a["slot_id"] == slot["slot_id"]), None)
    if appt is not None:
        r.append("CURRENT_BOOKING" if appt["shipment_id"] == ship["shipment_id"] else "TAKEN")
    for h in ctx.live_holds(now):
        if h["slot_id"] == slot["slot_id"] and h["thread_id"] != thread_id:
            r.append("HELD_BY_OTHER")
            break

    # 3 dock active and no dock event overlapping (overrides an OPEN slot status)
    if dock["dock_status"] != "ACTIVE" or any(
            d == dock["dock_id"] and s < busy_end and e > start for d, s, e, _ in ctx.events):
        r.append("DOCK_DOWN")

    # 4 dock type and weight
    if not ctx.dock_type_ok(dock):
        r.append("DOCK_TYPE")
    if ship["load_weight_kg"] > dock["max_vehicle_weight_kg"]:
        r.append("WEIGHT")

    # 5 facility hours
    f = ctx.facility
    if start < at_clock(start, f["open_time"]) or busy_end > at_clock(start, f["close_time"]):
        r.append("OUTSIDE_HOURS")

    # 6 not before the truck can be there (ETA + margin), not in the past
    if start < eta.planning_epoch or start < now:
        r.append("TOO_EARLY")

    # 7 driver's latest finish
    if latest_finish is not None and busy_end > latest_finish:
        r.append("TOO_LATE_FOR_YOU")

    # 8 overlap with other bookings or live holds on the same dock (own current booking excluded)
    buf = int(p["feasibility"]["buffer_min"]) * 60
    others = [(a["slot_id"], a["start_epoch"], a["end_epoch"]) for a in ctx.active_appts
              if a["dock_id"] == dock["dock_id"] and a["shipment_id"] != ship["shipment_id"]]
    others += [(h["slot_id"], h["start_epoch"], h["end_epoch"]) for h in ctx.live_holds(now)
               if h["dock_id"] == dock["dock_id"] and h["thread_id"] != thread_id]
    if any(sid != slot["slot_id"] and s < busy_end + buf and e + buf > start for sid, s, e in others):
        r.append("OVERLAP")

    # 10 approval routing (not a failure: shown, but a person confirms)
    a = c.approval_reasons
    ref = ctx.plan_reference()
    if start - ref > int(p["approval"]["max_shift_min"]) * 60:
        a.append("SHIFT_OVER_LIMIT")
    if p["approval"]["other_day_needs_approval"] and ist_date(start) != ist_date(ref):
        a.append("OTHER_DAY")
    last = ctx.rules.get("LAST_NEW_START_TIME")
    if last and start > at_clock(start, last):
        a.append("AFTER_LAST_START")
    return c


def check_slot(conn: sqlite3.Connection, shipment_id: str, slot_id: str, *, now: int,
               driver_id: str | None = None, eta: ResolvedEta | None = None,
               confirmed: Declaration | None = None, latest_finish: int | None = None,
               thread_id: str | None = None) -> SlotCheck:
    """Checks 1 to 8 and 10 for one slot. Used for the re-check inside hold and confirm."""
    ctx = Context(conn, shipment_id)
    eta = eta or resolve_eta(conn, shipment_id, confirmed)
    slot = ctx.slot_by_id.get(slot_id)
    if slot is None:
        raise KeyError(f"slot {slot_id} not at this shipment's facility")
    c = _evaluate(ctx, slot, driver_id=driver_id, eta=eta, now=now,
                  latest_finish=latest_finish, thread_id=thread_id)
    if c.feasible and _protected(ctx, [c] + _feasible_others(ctx, c, driver_id, eta, now, latest_finish, thread_id),
                                 now).get(c.slot_id):
        c.reasons.append("PROTECTED")
    return c


def _feasible_others(ctx, c, driver_id, eta, now, latest_finish, thread_id):
    out = []
    for s in ctx.slots:
        if s["slot_id"] == c.slot_id:
            continue
        x = _evaluate(ctx, s, driver_id=driver_id, eta=eta, now=now, latest_finish=latest_finish, thread_id=thread_id)
        if x.feasible:
            out.append(x)
    return out


def _protected(ctx: Context, feasible: list[SlotCheck], now: int) -> dict[str, bool]:
    """P-3: if the shipment's dock type has <= N compatible slots in the window,
    the LAST one is kept for loads at or above the protected priority."""
    pr = ctx.p["priority"]
    order = pr["order"]
    if order.index(ctx.ship["priority_code"]) <= order.index(pr["protected_min_priority"]):
        return {}
    window_end = now + int(pr["protected_window_min"]) * 60
    in_window = sorted((c for c in feasible if c.start < window_end), key=lambda c: c.start)
    if 0 < len(in_window) <= int(pr["protected_slot_threshold"]):
        return {in_window[-1].slot_id: True}
    return {}


def find_feasible_slots(conn: sqlite3.Connection, shipment_id: str, *, now: int,
                        driver_id: str | None = None, eta: ResolvedEta | None = None,
                        confirmed: Declaration | None = None, latest_finish: int | None = None,
                        thread_id: str | None = None) -> tuple[list[SlotCheck], list[SlotCheck]]:
    """Run every check on every slot at the shipment's facility.
    Returns (feasible, all_checks). all_checks keeps the reason codes for the hand-off record."""
    ctx = Context(conn, shipment_id)
    eta = eta or resolve_eta(conn, shipment_id, confirmed)
    checks = [_evaluate(ctx, s, driver_id=driver_id, eta=eta, now=now,
                        latest_finish=latest_finish, thread_id=thread_id) for s in ctx.slots]
    feasible = [c for c in checks if c.feasible]
    for sid in _protected(ctx, feasible, now):
        next(c for c in checks if c.slot_id == sid).reasons.append("PROTECTED")
    return [c for c in checks if c.feasible], checks


def reason_summary(checks: list[SlotCheck]) -> dict[str, int]:
    """How many slots failed for each reason (for the hand-off and the readout)."""
    out: dict[str, int] = {}
    for c in checks:
        for code in c.reasons:
            out[code] = out.get(code, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
