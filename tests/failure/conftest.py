"""Shared helpers for the failure tests T-19 to T-24.

These tests break things on purpose. They run the REAL graph, tools and database with the free rules
model (option A), so no API key is needed. Assertions are on tool calls and database state, plus one
safety check on the reply: the driver is never told "confirmed" unless a commit really happened.
"""
import pytest

from src.agent.graph import DelayService
from src.agent.rules_model import RulesModel
from tests.conftest import ts


class Clock:
    """A clock the test can move forward (for the expired-hold test)."""

    def __init__(self, start: int):
        self.now = start

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def clock():
    return Clock(ts("10:00"))


@pytest.fixture
def svc(conn, tmp_path, clock):
    s = DelayService(conn, RulesModel(), tmp_path / "ck.db", clock=clock)
    yield s
    s.close()


def tools_called(result) -> list[str]:
    return [t["tool"] for t in result["tool_calls"]]


def statuses(result) -> list[tuple[str, str]]:
    return [(t["tool"], t["status"]) for t in result["tool_calls"]]


def says_confirmed(reply: str) -> bool:
    """True if the reply claims a booking is done (ignores 'not confirmed yet' and similar)."""
    from src.agent.graph import FAKE_DONE
    import re
    return bool(re.search(r"\b(confirmed|booked)\b", FAKE_DONE.sub("", reply), re.I))


def current_booking(conn, shipment_id: str):
    row = conn.execute("SELECT appointment_id, slot_id, appointment_status FROM appointments "
                       "WHERE shipment_id=? AND is_current=1", (shipment_id,)).fetchone()
    return tuple(row) if row else None


def chat_bookings(conn) -> int:
    """New bookings made through the chat (the client's own rows start APT1..., ours APT-...)."""
    return conn.execute("SELECT COUNT(*) FROM appointments WHERE appointment_id LIKE 'APT-%'").fetchone()[0]
