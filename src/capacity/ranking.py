"""Ranking policy P-1 to P-5 (architecture 9.6). Code applies it; the model never ranks.

P-1 A confirmed promise is never taken back automatically
      -> check_slot marks a booked slot TAKEN; nothing here can pre-empt it.
P-2 First to hold wins until the hold expires or is released
      -> check_slot marks it HELD_BY_OTHER; the partial unique index backs it up.
P-3 Protected last slot of a scarce dock type for top-priority loads
      -> find_feasible_slots marks it PROTECTED.
P-4 Pre-emption or a policy conflict goes to a coordinator
      -> needs_preemption() returns True; the caller escalates.
P-5 Queue order: priority, then earliest latest-finish, then arrival; +1 class per 10 min waiting
      -> order_requests().
"""
from __future__ import annotations

from dataclasses import dataclass

from src.capacity.eta import ResolvedEta
from src.capacity.feasibility import SlotCheck
from src.config import policy
from src.timeutil import hhmm


@dataclass(frozen=True)
class RankedOption:
    rank: int
    slot_id: str
    dock_code: str
    start: int
    end: int
    wait_min: int
    needs_approval: bool
    why: str


def rank_options(feasible: list[SlotCheck], eta: ResolvedEta, limit: int | None = None) -> list[RankedOption]:
    """Order feasible slots for the driver. No-approval first, then the least waiting
    after the truck can be there, then the dock code (stable tie-break)."""
    limit = limit or int(policy()["offers"]["max_options"])
    ordered = sorted(feasible, key=lambda c: (c.needs_approval, c.start, c.dock_code))
    out = []
    for i, c in enumerate(ordered[:limit], start=1):
        wait = max(0, (c.start - eta.eta_epoch) // 60)
        why = f"{hhmm(c.start)} to {hhmm(c.end)} at {c.dock_code}; starts {wait} min after your ETA {hhmm(eta.eta_epoch)}"
        if c.needs_approval:
            why += "; a coordinator must approve (" + ", ".join(c.approval_reasons) + ")"
        out.append(RankedOption(i, c.slot_id, c.dock_code, c.start, c.end, wait, c.needs_approval, why))
    return out


def needs_preemption(feasible: list[SlotCheck]) -> bool:
    """P-4: if nothing is free, taking someone else's confirmed slot is never automatic."""
    return not feasible


@dataclass(frozen=True)
class QueuedRequest:
    request_id: str
    priority_code: str
    latest_finish: int | None
    arrived_at: int


def effective_class(req: QueuedRequest, now: int) -> int:
    """0 = highest. Moves up one class for every `aging_bump_min` minutes waited."""
    pr = policy()["priority"]
    base = pr["order"].index(req.priority_code)
    bumps = max(0, (now - req.arrived_at) // (int(pr["aging_bump_min"]) * 60))
    return max(0, base - bumps)


def order_requests(reqs: list[QueuedRequest], now: int) -> list[QueuedRequest]:
    big = 2**62
    return sorted(reqs, key=lambda r: (effective_class(r, now),
                                       r.latest_finish if r.latest_finish is not None else big,
                                       r.arrived_at))
