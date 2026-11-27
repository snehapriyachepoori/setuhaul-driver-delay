"""Migration 001: NEW tables only. The client's tables are never altered.

Run on a work copy:  python -m src.migrate data/work.db
Safe to run twice (CREATE ... IF NOT EXISTS).
"""
from __future__ import annotations

import json
import sqlite3
import sys

from src.config import policy
from src.timeutil import to_epoch

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);

-- Slot times as numbers (epoch seconds), so comparisons never depend on text format.
CREATE TABLE IF NOT EXISTS slot_times (
    slot_id     TEXT PRIMARY KEY REFERENCES appointment_slots(slot_id),
    start_epoch INTEGER NOT NULL,
    end_epoch   INTEGER NOT NULL CHECK (end_epoch > start_epoch)
);

-- What we showed a driver. Nothing is reserved by an offer.
CREATE TABLE IF NOT EXISTS offers (
    offer_id     TEXT PRIMARY KEY,
    thread_id    TEXT NOT NULL,
    shipment_id  TEXT NOT NULL REFERENCES shipments(shipment_id),
    slot_id      TEXT NOT NULL REFERENCES appointment_slots(slot_id),
    eta_epoch    INTEGER NOT NULL,
    eta_source   TEXT NOT NULL,
    shown_rank   INTEGER NOT NULL,
    needs_approval INTEGER NOT NULL DEFAULT 0 CHECK (needs_approval IN (0,1)),
    shown_at     INTEGER NOT NULL
);

-- A hold: one thread's exclusive, expiring claim on a slot.
CREATE TABLE IF NOT EXISTS slot_holds (
    hold_id         TEXT PRIMARY KEY,
    slot_id         TEXT NOT NULL REFERENCES appointment_slots(slot_id),
    shipment_id     TEXT NOT NULL REFERENCES shipments(shipment_id),
    thread_id       TEXT NOT NULL,
    offer_id        TEXT REFERENCES offers(offer_id),
    state           TEXT NOT NULL CHECK (state IN
                      ('ACTIVE','PENDING_APPROVAL','CONFIRMED','RELEASED','EXPIRED','REJECTED')),
    expires_at      INTEGER NOT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);
-- Last line of defence: at most ONE live hold per slot.
CREATE UNIQUE INDEX IF NOT EXISTS ux_live_hold_per_slot
    ON slot_holds(slot_id) WHERE state IN ('ACTIVE','PENDING_APPROVAL');

-- Same key -> same answer (no second booking on a retry).
CREATE TABLE IF NOT EXISTS idempotency_log (
    key          TEXT PRIMARY KEY,
    action       TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    created_at   INTEGER NOT NULL
);

-- A repeated channel message is processed once.
CREATE TABLE IF NOT EXISTS inbound_messages (
    channel_msg_key TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    received_at     INTEGER NOT NULL,
    reply_json      TEXT
);

-- Complete hand-off record for a coordinator.
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id      TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    shipment_id     TEXT REFERENCES shipments(shipment_id),
    driver_ref      TEXT NOT NULL,          -- masked, never the phone number
    reason_code     TEXT NOT NULL,
    summary_json    TEXT NOT NULL,
    options_shown   TEXT NOT NULL,
    state_read      TEXT NOT NULL,
    not_done        TEXT NOT NULL,
    owner           TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    deadline_at     INTEGER NOT NULL,
    acknowledged_at INTEGER,
    acknowledged_by TEXT
);

-- Messages to send AFTER commit (outbox pattern).
CREATE TABLE IF NOT EXISTS outbox (
    outbox_id   TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    sent_at     INTEGER
);

-- Append-only record of every decision.
CREATE TABLE IF NOT EXISTS audit_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    thread_id   TEXT,
    shipment_id TEXT,
    slot_id     TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

-- The written allocation policy, versioned.
CREATE TABLE IF NOT EXISTS priority_policy (
    version     TEXT PRIMARY KEY,
    parameters  TEXT NOT NULL,
    owner       TEXT NOT NULL,
    valid_from  INTEGER NOT NULL
);
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    import time

    now = int(time.time())
    conn.execute("INSERT OR IGNORE INTO schema_version VALUES (1, ?)", (now,))
    rows = conn.execute("SELECT slot_id, slot_start_ts, slot_end_ts FROM appointment_slots").fetchall()
    conn.executemany(
        "INSERT OR IGNORE INTO slot_times VALUES (?,?,?)",
        [(r[0], to_epoch(r[1]), to_epoch(r[2])) for r in rows],
    )
    p = policy()
    conn.execute(
        "INSERT OR IGNORE INTO priority_policy VALUES (?,?,?,?)",
        (p["version"], json.dumps(p["priority"]), p["owner"], now),
    )


if __name__ == "__main__":
    from src.db import connect

    c = connect(sys.argv[1])
    migrate(c)
    print("migrated", sys.argv[1])
