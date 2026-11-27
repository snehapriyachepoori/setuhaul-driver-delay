"""The commit layer: hold_slot, confirm_booking, release_hold (architecture 9.7).

Every write is ONE `BEGIN IMMEDIATE` transaction that:
  1. replays the stored answer if this idempotency key was seen before;
  2. re-runs the full feasibility check (an option shown earlier may be stale);
  3. writes the change, an audit row and (for confirm) an outbox row;
  4. stores the answer under the idempotency key;
  5. commits. The reply to the driver is built only from the committed result.

The partial unique index on slot_holds and the client's unique index on appointments are the
last line of defence if this code is ever wrong.
"""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
import uuid

from src.capacity.eta import Declaration
from src.capacity.feasibility import check_slot
from src.config import policy
from src.db import write_txn
from src.timeutil import to_ist

MAX_LOCK_RETRIES = 3


class IdempotencyConflict(ValueError):
    """The same key was reused for a DIFFERENT request."""


# --- small helpers -----------------------------------------------------------
def _hash(req: dict) -> str:
    return hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()


def _replay(conn, key: str, action: str, req: dict) -> dict | None:
    row = conn.execute("SELECT action, request_hash, result_json FROM idempotency_log WHERE key=?",
                       (key,)).fetchone()
    if row is None:
        return None
    if row["action"] != action or row["request_hash"] != _hash(req):
        raise IdempotencyConflict(f"key {key} reused for a different request")
    out = json.loads(row["result_json"])
    out["replayed"] = True
    return out


def _remember(conn, key: str, action: str, req: dict, result: dict, now: int) -> None:
    conn.execute("INSERT INTO idempotency_log VALUES (?,?,?,?,?)",
                 (key, action, _hash(req), json.dumps(result), now))


def _audit(conn, now, actor, action, thread_id=None, shipment_id=None, slot_id=None, **detail):
    conn.execute("INSERT INTO audit_events(ts, actor, action, thread_id, shipment_id, slot_id, detail_json) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (now, actor, action, thread_id, shipment_id, slot_id, json.dumps(detail)))


def _with_retry(fn):
    """Retry a locked database up to 3 times with jittered backoff, then give up (caller escalates)."""
    def wrapper(*a, **kw):
        for attempt in range(MAX_LOCK_RETRIES + 1):
            try:
                return fn(*a, **kw)
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() or attempt == MAX_LOCK_RETRIES:
                    raise
                time.sleep((2 ** attempt) * 0.05 + random.random() * 0.05)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _expire_stale_holds(conn, now: int) -> None:
    """Tidy-up only. Correctness never depends on this: every check reads expires_at itself."""
    conn.execute("UPDATE slot_holds SET state='EXPIRED', updated_at=? "
                 "WHERE state='ACTIVE' AND expires_at <= ?", (now, now))


# --- hold --------------------------------------------------------------------
@_with_retry
def hold_slot(conn: sqlite3.Connection, *, shipment_id: str, slot_id: str, thread_id: str,
              driver_id: str, idempotency_key: str, now: int, offer_id: str | None = None,
              confirmed: Declaration | None = None) -> dict:
    """Exclusive, expiring claim. Returns status ACTIVE or REFUSED (with reason codes)."""
    req = {"shipment_id": shipment_id, "slot_id": slot_id, "thread_id": thread_id, "offer_id": offer_id}
    with write_txn(conn):
        if (prev := _replay(conn, idempotency_key, "hold_slot", req)) is not None:
            return prev
        _expire_stale_holds(conn, now)
        check = check_slot(conn, shipment_id, slot_id, now=now, driver_id=driver_id, thread_id=thread_id,
                           confirmed=confirmed)
        if not check.feasible:
            result = {"status": "REFUSED", "slot_id": slot_id, "reason_codes": check.reasons}
            _audit(conn, now, "code", "HOLD_REFUSED", thread_id, shipment_id, slot_id, reasons=check.reasons)
        else:
            # One live hold per thread: picking a new option releases the previous one.
            conn.execute("UPDATE slot_holds SET state='RELEASED', updated_at=? "
                         "WHERE thread_id=? AND state='ACTIVE'", (now, thread_id))
            hold_id = "HOLD-" + uuid.uuid4().hex[:10]
            expires = now + int(policy()["holds"]["expiry_min"]) * 60
            try:
                conn.execute("INSERT INTO slot_holds VALUES (?,?,?,?,?,'ACTIVE',?,?,?,?)",
                             (hold_id, slot_id, shipment_id, thread_id, offer_id, expires, now, now,
                              idempotency_key))
            except sqlite3.IntegrityError:
                # The database's own rule caught a second live hold (should not happen; logged).
                result = {"status": "REFUSED", "slot_id": slot_id, "reason_codes": ["HELD_BY_OTHER"]}
                _audit(conn, now, "db", "HOLD_BLOCKED_BY_INDEX", thread_id, shipment_id, slot_id)
            else:
                result = {"status": "ACTIVE", "hold_id": hold_id, "slot_id": slot_id,
                          "expires_at": expires, "needs_approval": check.needs_approval,
                          "approval_reasons": check.approval_reasons}
                _audit(conn, now, "code", "HOLD_PLACED", thread_id, shipment_id, slot_id, hold_id=hold_id)
        _remember(conn, idempotency_key, "hold_slot", req, result, now)
        return result


# --- confirm -----------------------------------------------------------------
@_with_retry
def confirm_booking(conn: sqlite3.Connection, *, hold_id: str, thread_id: str, driver_id: str,
                    idempotency_key: str, now: int, confirmed: Declaration | None = None) -> dict:
    """Commit. Returns CONFIRMED, NEEDS_APPROVAL or REFUSED. All-or-nothing."""
    req = {"hold_id": hold_id, "thread_id": thread_id}
    with write_txn(conn):
        if (prev := _replay(conn, idempotency_key, "confirm_booking", req)) is not None:
            return prev
        result = _confirm_inside_txn(conn, hold_id, thread_id, driver_id, now, confirmed)
        _remember(conn, idempotency_key, "confirm_booking", req, result, now)
        return result


def _confirm_inside_txn(conn, hold_id, thread_id, driver_id, now, confirmed=None) -> dict:
    h = conn.execute("SELECT * FROM slot_holds WHERE hold_id=?", (hold_id,)).fetchone()
    if h is None or h["thread_id"] != thread_id:
        return {"status": "REFUSED", "reason_codes": ["NO_SUCH_HOLD"]}
    if h["state"] != "ACTIVE":
        return {"status": "REFUSED", "reason_codes": [f"HOLD_{h['state']}"]}
    if h["expires_at"] <= now:                       # expiry checked here, never trusted to a job
        conn.execute("UPDATE slot_holds SET state='EXPIRED', updated_at=? WHERE hold_id=?", (now, hold_id))
        _audit(conn, now, "code", "HOLD_EXPIRED", thread_id, h["shipment_id"], h["slot_id"], hold_id=hold_id)
        return {"status": "REFUSED", "reason_codes": ["HOLD_EXPIRED"], "slot_id": h["slot_id"]}

    shipment_id, slot_id = h["shipment_id"], h["slot_id"]
    check = check_slot(conn, shipment_id, slot_id, now=now, driver_id=driver_id, thread_id=thread_id,
                       confirmed=confirmed)
    if not check.feasible:
        conn.execute("UPDATE slot_holds SET state='RELEASED', updated_at=? WHERE hold_id=?", (now, hold_id))
        _audit(conn, now, "code", "CONFIRM_REFUSED", thread_id, shipment_id, slot_id, reasons=check.reasons)
        return {"status": "REFUSED", "slot_id": slot_id, "reason_codes": check.reasons}
    if check.needs_approval:
        conn.execute("UPDATE slot_holds SET state='PENDING_APPROVAL', updated_at=? WHERE hold_id=?",
                     (now, hold_id))
        _audit(conn, now, "code", "NEEDS_APPROVAL", thread_id, shipment_id, slot_id,
               reasons=check.approval_reasons)
        return {"status": "NEEDS_APPROVAL", "hold_id": hold_id, "slot_id": slot_id,
                "approval_reasons": check.approval_reasons}

    # Rebooking: old booking out and new booking in, in the SAME transaction.
    old = conn.execute(
        "SELECT appointment_id FROM appointments WHERE shipment_id=? AND is_current=1 "
        "AND appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')",
        (shipment_id,)).fetchone()
    iso_now = to_ist(now)
    if old is not None:
        conn.execute("UPDATE appointments SET appointment_status='CANCELLED', is_current=0, cancelled_at=?, "
                     "cancellation_reason='REPLACED_BY_DRIVER_REBOOKING', updated_at=? WHERE appointment_id=?",
                     (iso_now, iso_now, old["appointment_id"]))
    appt_id = "APT-" + uuid.uuid4().hex[:10]
    conn.execute("INSERT INTO appointments(appointment_id, shipment_id, slot_id, appointment_status, "
                 "booking_source, is_current, booked_at, confirmed_at, replaced_appointment_id, updated_at) "
                 "VALUES (?,?,?,'CONFIRMED','DRIVER_CHAT',1,?,?,?,?)",
                 (appt_id, shipment_id, slot_id, iso_now, iso_now,
                  old["appointment_id"] if old else None, iso_now))
    conn.execute("UPDATE slot_holds SET state='CONFIRMED', updated_at=? WHERE hold_id=?", (now, hold_id))
    result = {"status": "CONFIRMED", "appointment_id": appt_id, "slot_id": slot_id,
              "replaced_appointment_id": old["appointment_id"] if old else None}
    _audit(conn, now, "code", "CONFIRMED", thread_id, shipment_id, slot_id,
           appointment_id=appt_id, replaced_appointment_id=result["replaced_appointment_id"])
    conn.execute("INSERT INTO outbox VALUES (?,?,?,?,?,NULL)",
                 ("OUT-" + uuid.uuid4().hex[:10], thread_id, "BOOKING_CONFIRMED", json.dumps(result), now))
    return result


# --- release -----------------------------------------------------------------
@_with_retry
def release_hold(conn: sqlite3.Connection, *, hold_id: str, thread_id: str, idempotency_key: str,
                 now: int) -> dict:
    req = {"hold_id": hold_id, "thread_id": thread_id}
    with write_txn(conn):
        if (prev := _replay(conn, idempotency_key, "release_hold", req)) is not None:
            return prev
        h = conn.execute("SELECT * FROM slot_holds WHERE hold_id=?", (hold_id,)).fetchone()
        if h is None or h["thread_id"] != thread_id:
            result = {"status": "REFUSED", "reason_codes": ["NO_SUCH_HOLD"]}
        elif h["state"] not in ("ACTIVE", "PENDING_APPROVAL"):
            result = {"status": "RELEASED", "hold_id": hold_id, "note": f"already {h['state']}"}
        else:
            conn.execute("UPDATE slot_holds SET state='RELEASED', updated_at=? WHERE hold_id=?", (now, hold_id))
            _audit(conn, now, "code", "HOLD_RELEASED", thread_id, h["shipment_id"], h["slot_id"], hold_id=hold_id)
            result = {"status": "RELEASED", "hold_id": hold_id}
        _remember(conn, idempotency_key, "release_hold", req, result, now)
        return result


def live_claims_per_slot(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Integrity check: slots with MORE than one active appointment. Must always be empty."""
    return [tuple(r) for r in conn.execute(
        "SELECT slot_id, COUNT(*) FROM appointments "
        "WHERE appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') "
        "GROUP BY slot_id HAVING COUNT(*) > 1")]
