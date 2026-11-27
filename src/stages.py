"""Stage machine (architecture 9.1). CODE owns the stage; the model never changes it.

Each stage exposes only some tools. A tool outside the allowlist is simply not offered,
and dispatch refuses it if the model asks anyway.
"""
from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    SAFETY = "SAFETY"
    IDENTIFY = "IDENTIFY"
    CLARIFY = "CLARIFY"
    OFFER = "OFFER"
    HOLD = "HOLD"
    CONFIRM = "CONFIRM"
    ESCALATE = "ESCALATE"
    DONE = "DONE"


class Event(str, Enum):
    SAFETY_CUE = "SAFETY_CUE"
    NO_CUE = "NO_CUE"
    SHIPMENT_CONFIRMED = "SHIPMENT_CONFIRMED"
    MISMATCH_OR_NONE = "MISMATCH_OR_NONE"
    FACTS_KNOWN = "FACTS_KNOWN"
    PICKED = "PICKED"
    NO_FEASIBLE_SLOT = "NO_FEASIBLE_SLOT"
    SAID_YES = "SAID_YES"
    HOLD_LOST = "HOLD_LOST"          # expired or released
    COMMITTED = "COMMITTED"
    REFUSED = "REFUSED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    ESCALATED = "ESCALATED"          # allowed from any stage


TRANSITIONS: dict[tuple[Stage, Event], Stage] = {
    (Stage.SAFETY, Event.SAFETY_CUE): Stage.ESCALATE,
    (Stage.SAFETY, Event.NO_CUE): Stage.IDENTIFY,
    (Stage.IDENTIFY, Event.SHIPMENT_CONFIRMED): Stage.CLARIFY,
    (Stage.IDENTIFY, Event.MISMATCH_OR_NONE): Stage.ESCALATE,
    (Stage.CLARIFY, Event.FACTS_KNOWN): Stage.OFFER,
    (Stage.OFFER, Event.PICKED): Stage.HOLD,
    (Stage.OFFER, Event.NO_FEASIBLE_SLOT): Stage.ESCALATE,
    (Stage.HOLD, Event.SAID_YES): Stage.CONFIRM,
    (Stage.HOLD, Event.HOLD_LOST): Stage.OFFER,
    (Stage.HOLD, Event.REFUSED): Stage.OFFER,
    (Stage.CONFIRM, Event.COMMITTED): Stage.DONE,
    (Stage.CONFIRM, Event.REFUSED): Stage.OFFER,
    (Stage.CONFIRM, Event.NEEDS_APPROVAL): Stage.ESCALATE,
    (Stage.CONFIRM, Event.HOLD_LOST): Stage.OFFER,
}

ALLOWED_TOOLS: dict[Stage, frozenset[str]] = {
    Stage.SAFETY: frozenset(),
    Stage.IDENTIFY: frozenset({"resolve_shipment"}),
    Stage.CLARIFY: frozenset({"get_shipment_context", "record_eta_declaration"}),
    Stage.OFFER: frozenset({"get_shipment_context", "get_feasible_slots", "hold_slot"}),
    # confirm_booking is offered at HOLD, but dispatch only runs it after an explicit "yes" from the
    # driver (checked in code); the call then moves HOLD -> CONFIRM -> DONE/OFFER/ESCALATE.
    Stage.HOLD: frozenset({"hold_slot", "release_hold", "get_feasible_slots", "confirm_booking"}),
    Stage.CONFIRM: frozenset({"confirm_booking", "release_hold"}),
    Stage.ESCALATE: frozenset(),
    Stage.DONE: frozenset(),
}
ANY_STAGE_TOOLS = frozenset({"escalate_to_coordinator"})
TERMINAL = {Stage.ESCALATE, Stage.DONE}


class IllegalTransition(ValueError):
    pass


def next_stage(stage: Stage, event: Event) -> Stage:
    if event == Event.ESCALATED and stage not in TERMINAL:
        return Stage.ESCALATE
    try:
        return TRANSITIONS[(stage, event)]
    except KeyError:
        raise IllegalTransition(f"{event.value} is not allowed at stage {stage.value}") from None


def tools_for(stage: Stage) -> frozenset[str]:
    if stage in TERMINAL:
        return frozenset()
    return ALLOWED_TOOLS[stage] | ANY_STAGE_TOOLS
