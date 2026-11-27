"""resolve_eta(): one ETA per shipment, with its source and how sure we are (architecture 9.4).

Order of trust:
  1. newest OPERATIONS_OVERRIDE wins outright;
  2. else a driver declaration CONFIRMED in this conversation;
  3. else the LATER of the newest driver and newest warehouse estimate (the safe side);
  4. else the shipment's own latest/original plan time.
Then add a safety margin by confidence (values in config/policy.toml).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum

from src.config import policy
from src.timeutil import to_epoch


class DelayKind(str, Enum):
    ARRIVAL_DELAY = "ARRIVAL_DELAY"   # "I will reach you 90 minutes later than planned"
    CLOCK_TIME = "CLOCK_TIME"         # "I will reach at 19:10"
    REPAIR_TIME = "REPAIR_TIME"       # "repair takes 90 minutes" -> not an arrival time


class NeedClockTime(ValueError):
    """A repair time is not an arrival time. The agent must ask for a clock time."""


@dataclass(frozen=True)
class Declaration:
    """What the driver said AND confirmed when we stated it back."""
    eta_epoch: int
    confidence: str = "MEDIUM"


@dataclass(frozen=True)
class ResolvedEta:
    shipment_id: str
    eta_epoch: int
    source: str
    confidence: str
    margin_min: int
    based_on: tuple[str, ...] = field(default_factory=tuple)

    @property
    def planning_epoch(self) -> int:
        """Earliest moment a slot may start for this truck."""
        return self.eta_epoch + self.margin_min * 60


def margin_for(confidence: str) -> int:
    return int(policy()["eta"]["margin_min"][confidence])


def declaration_from_driver(kind: DelayKind, *, base_eta_epoch: int | None = None,
                            delay_minutes: int | None = None, clock_epoch: int | None = None,
                            confidence: str = "MEDIUM") -> Declaration:
    """Turn what the driver said into an arrival time, keeping the KIND of statement."""
    if kind == DelayKind.REPAIR_TIME:
        raise NeedClockTime("Repair time given; ask: 'What time do you expect to reach the gate?'")
    if kind == DelayKind.CLOCK_TIME:
        if clock_epoch is None:
            raise ValueError("clock_epoch required for CLOCK_TIME")
        return Declaration(clock_epoch, confidence)
    if base_eta_epoch is None or delay_minutes is None:
        raise ValueError("base_eta_epoch and delay_minutes required for ARRIVAL_DELAY")
    return Declaration(base_eta_epoch + delay_minutes * 60, confidence)


def resolve_eta(conn: sqlite3.Connection, shipment_id: str,
                confirmed: Declaration | None = None) -> ResolvedEta:
    ship = conn.execute(
        "SELECT original_eta_ts, latest_eta_ts FROM shipments WHERE shipment_id=?", (shipment_id,)
    ).fetchone()
    if ship is None:
        raise KeyError(shipment_id)

    rows = conn.execute(
        "SELECT eta_update_id, source_type, declared_eta_ts, confidence_code, created_at "
        "FROM eta_updates WHERE shipment_id=?", (shipment_id,)
    ).fetchall()
    # Newest per source, comparing created_at as numbers.
    newest: dict[str, tuple] = {}
    for r in rows:
        key = r[1]
        created = to_epoch(r[4])
        if key not in newest or created > newest[key][0]:
            newest[key] = (created, r[0], to_epoch(r[2]), r[3])

    def build(eta, source, conf, ids):
        return ResolvedEta(shipment_id, eta, source, conf, margin_for(conf), tuple(ids))

    if "OPERATIONS_OVERRIDE" in newest:
        _, uid, eta, conf = newest["OPERATIONS_OVERRIDE"]
        return build(eta, "OPERATIONS_OVERRIDE", conf, [uid])

    if confirmed is not None:
        return build(confirmed.eta_epoch, "DRIVER_CONFIRMED_IN_CHAT", confirmed.confidence, [])

    candidates = [newest[s] for s in ("DRIVER_DECLARED", "WAREHOUSE_ESTIMATE") if s in newest]
    if candidates:
        # Later ETA is the safe side. On a tie, the less confident one keeps the bigger margin.
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        best = max(candidates, key=lambda c: (c[2], -order[c[3]]))
        src = next(s for s in newest if newest[s] is best)
        return build(best[2], src, best[3], [best[1]])

    plan_ts = ship[1] or ship[0]
    return build(to_epoch(plan_ts), "SHIPMENT_PLAN", policy()["eta"].get("plan_confidence", "MEDIUM"), [])
