"""Hand-off to a coordinator (architecture 9.9). A complete record, so the person never has to re-ask.

Fields: thread, shipment, driver (masked), reason code, summary, what the driver said, resolved ETA
with source, options shown, state read, what was NOT done, owner, deadline, acknowledged_at.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

from src.config import policy
from src.db import write_txn
from src.guardrails.input import mask_pii

REQUIRED_FIELDS = ["handoff_id", "thread_id", "driver_ref", "reason_code", "summary_json",
                   "options_shown", "state_read", "not_done", "owner", "created_at", "deadline_at"]


def pick_owner(conn: sqlite3.Connection, facility_id: str | None) -> str:
    """The facility's warehouse coordinator; a vacant or missing role falls back to the shift manager
    (audit I-13: CON005 is 'Vacant Position')."""
    if facility_id:
        rows = {r["contact_role"]: r for r in conn.execute(
            "SELECT contact_id, contact_role, contact_name FROM facility_contacts "
            "WHERE facility_id=? AND active_flag=1", (facility_id,))}
        for role in ("WAREHOUSE_COORDINATOR", "SHIFT_MANAGER", "NIGHT_SHIFT_COORDINATOR"):
            r = rows.get(role)
            if r and "vacant" not in r["contact_name"].lower():
                return f"{r['contact_id']} ({role})"
    return "UNASSIGNED (operations head must pick an owner)"


def create_handoff(conn: sqlite3.Connection, *, thread_id: str, shipment_id: str | None, driver_id: str,
                   reason_code: str, summary: dict, options_shown: list, state_read: dict,
                   not_done: list[str], now: int) -> dict:
    """Idempotent per (thread, reason): a repeated escalation returns the existing open hand-off."""
    with write_txn(conn):
        existing = conn.execute(
            "SELECT handoff_id, deadline_at, owner FROM handoffs WHERE thread_id=? AND reason_code=? "
            "AND acknowledged_at IS NULL", (thread_id, reason_code)).fetchone()
        if existing:
            return {"status": "ESCALATED", "handoff_id": existing["handoff_id"],
                    "deadline_at": existing["deadline_at"], "owner": existing["owner"], "replayed": True}
        fac = None
        if shipment_id:
            r = conn.execute("SELECT destination_facility_id FROM shipments WHERE shipment_id=?",
                             (shipment_id,)).fetchone()
            fac = r[0] if r else None
        owner = pick_owner(conn, fac)
        deadlines = policy()["escalation"]["deadline_min"]
        deadline = now + int(deadlines.get(reason_code, 15)) * 60
        hid = "HO-" + uuid.uuid4().hex[:8]
        clean = json.loads(mask_pii(json.dumps(summary)))
        conn.execute(
            "INSERT INTO handoffs(handoff_id, thread_id, shipment_id, driver_ref, reason_code, summary_json, "
            "options_shown, state_read, not_done, owner, created_at, deadline_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (hid, thread_id, shipment_id, driver_id, reason_code, json.dumps(clean), json.dumps(options_shown),
             json.dumps(state_read), json.dumps(not_done), owner, now, deadline))
        conn.execute("INSERT INTO audit_events(ts, actor, action, thread_id, shipment_id, detail_json) "
                     "VALUES (?,?,?,?,?,?)", (now, "code", "HANDOFF_CREATED", thread_id, shipment_id,
                                              json.dumps({"handoff_id": hid, "reason_code": reason_code})))
        conn.execute("INSERT INTO outbox VALUES (?,?,?,?,?,NULL)",
                     ("OUT-" + uuid.uuid4().hex[:10], thread_id, "HANDOFF_ALERT",
                      json.dumps({"handoff_id": hid, "owner": owner, "reason_code": reason_code}), now))
    return {"status": "ESCALATED", "handoff_id": hid, "deadline_at": deadline, "owner": owner}


def open_handoffs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM handoffs WHERE acknowledged_at IS NULL ORDER BY deadline_at").fetchall()


def acknowledge(conn: sqlite3.Connection, handoff_id: str, who: str, now: int) -> bool:
    with write_txn(conn):
        cur = conn.execute("UPDATE handoffs SET acknowledged_at=?, acknowledged_by=? "
                           "WHERE handoff_id=? AND acknowledged_at IS NULL", (now, who, handoff_id))
        if cur.rowcount:
            conn.execute("INSERT INTO audit_events(ts, actor, action, detail_json) VALUES (?,?,?,?)",
                         (now, who, "HANDOFF_ACKNOWLEDGED", json.dumps({"handoff_id": handoff_id})))
    return cur.rowcount == 1


def missing_fields(row: sqlite3.Row) -> list[str]:
    """Measure M-6: hand-off completeness."""
    # options_shown may legitimately be an empty list (no feasible slot); everything else must be filled.
    return [f for f in REQUIRED_FIELDS
            if row[f] in (None, "") or (f != "options_shown" and row[f] in ("[]", "{}"))]
