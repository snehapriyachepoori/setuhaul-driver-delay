"""Demo-level authentication (architecture addendum). NOT production security.

Driver: starts a session with a phone number, checked against `drivers.phone`.
        A phone number is not proof of identity; a real channel (WhatsApp) supplies a verified one.
Coordinator: the hand-off view needs COORDINATOR_PIN from the git-ignored .env.
"""
from __future__ import annotations

import hmac
import os
import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DriverSession:
    driver_id: str
    driver_name: str
    phone_masked: str


def _digits(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def mask_phone_number(phone: str) -> str:
    d = _digits(phone)
    return f"******{d[-4:]}" if d else "******"


def start_driver_session(conn: sqlite3.Connection, phone: str) -> DriverSession | None:
    """Returns a session for a known ACTIVE driver, else None. Never says WHY it failed."""
    want = _digits(phone)
    if not want:
        return None
    for row in conn.execute("SELECT driver_id, driver_name, phone, driver_status FROM drivers"):
        if _digits(row["phone"]) == want and row["driver_status"] == "ACTIVE":
            return DriverSession(row["driver_id"], row["driver_name"], mask_phone_number(row["phone"]))
    return None


def coordinator_pin_ok(pin: str) -> bool:
    expected = os.environ.get("COORDINATOR_PIN", "")
    if not expected:          # no PIN configured -> nobody gets in
        return False
    return hmac.compare_digest(pin.encode(), expected.encode())
