"""Ranking policy (9.6) and the code-owned stage machine (9.1)."""
import pytest

from src.capacity.eta import resolve_eta
from src.capacity.feasibility import find_feasible_slots
from src.capacity.ranking import QueuedRequest, order_requests, rank_options
from src.stages import Event, IllegalTransition, Stage, next_stage, tools_for
from src.timeutil import hhmm


def test_rank_gives_at_most_three_and_puts_approval_last(conn, now):
    eta = resolve_eta(conn, "SHP1010")
    feasible, _ = find_feasible_slots(conn, "SHP1010", now=now, eta=eta)
    opts = rank_options(feasible, eta, limit=5)
    assert [hhmm(o.start) for o in opts] == ["12:00", "13:00", "14:00", "15:00", "16:00"]
    assert [o.needs_approval for o in opts] == [False, False, False, True, True]
    assert len(rank_options(feasible, eta)) == 3


def test_p5_queue_order_priority_then_latest_finish_then_arrival():
    reqs = [QueuedRequest("a", "NORMAL", 500, 0), QueuedRequest("b", "CRITICAL", 900, 50),
            QueuedRequest("c", "NORMAL", 400, 10)]
    assert [r.request_id for r in order_requests(reqs, now=60)] == ["b", "c", "a"]


def test_p5_waiting_request_moves_up_a_class():
    low_waiting = QueuedRequest("old", "LOW", None, 0)
    normal_new = QueuedRequest("new", "NORMAL", None, 1200)
    # After 20 minutes LOW has climbed two classes (to HIGH) and goes first.
    assert order_requests([normal_new, low_waiting], now=1200)[0].request_id == "old"


def test_happy_path_through_the_stages():
    s = Stage.SAFETY
    for e in [Event.NO_CUE, Event.SHIPMENT_CONFIRMED, Event.FACTS_KNOWN, Event.PICKED,
              Event.SAID_YES, Event.COMMITTED]:
        s = next_stage(s, e)
    assert s == Stage.DONE


def test_no_slot_goes_to_escalate():
    assert next_stage(Stage.OFFER, Event.NO_FEASIBLE_SLOT) == Stage.ESCALATE
    assert next_stage(Stage.SAFETY, Event.SAFETY_CUE) == Stage.ESCALATE


def test_cannot_skip_to_commit():
    with pytest.raises(IllegalTransition):
        next_stage(Stage.IDENTIFY, Event.COMMITTED)


def test_confirm_tool_not_available_before_confirm_stage():
    assert "confirm_booking" not in tools_for(Stage.IDENTIFY)
    assert "confirm_booking" not in tools_for(Stage.OFFER)
    assert "confirm_booking" in tools_for(Stage.CONFIRM)
    assert tools_for(Stage.SAFETY) == {"escalate_to_coordinator"}
    assert tools_for(Stage.DONE) == frozenset()


def test_escalate_allowed_from_any_open_stage():
    for s in [Stage.IDENTIFY, Stage.CLARIFY, Stage.OFFER, Stage.HOLD, Stage.CONFIRM]:
        assert next_stage(s, Event.ESCALATED) == Stage.ESCALATE
