"""The eight typed tools (architecture 9.3) and `dispatch`, where safety lives.

dispatch() does, in order:
  1. unknown tool            -> UNKNOWN_TOOL
  2. not allowed at stage     -> TOOL_NOT_ALLOWED_AT_STAGE   (stage machine, code-owned)
  3. Pydantic validation      -> INVALID_ARGUMENTS            (unknown fields rejected)
  4. ownership                -> MISMATCH                     (driver comes from the session, never the model)
  5. run the tool; errors become data ({"ok": False, "error": ...}), never a stack trace
  6. move the stage from the RESULT (code decides, not the model)
Idempotency keys are made by code: thread + turn + tool + arguments.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.capacity import commit
from src.capacity.eta import (Declaration, DelayKind, NeedClockTime, declaration_from_driver, resolve_eta)
from src.capacity.feasibility import find_feasible_slots, reason_summary
from src.capacity.handoff import create_handoff
from src.capacity.ranking import rank_options
from src.config import policy
from src.guardrails.input import is_explicit_yes
from src.stages import Event, Stage, next_stage, tools_for
from src.timeutil import at_clock, hhmm, to_epoch

ID_RE = r"^[A-Z]{2,4}[-A-Z0-9]*$"
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# --- conversation state (stored by the LangGraph checkpointer; no phone numbers in here) ---
class ConversationState(BaseModel):
    stage: Stage = Stage.SAFETY
    shipment_id: str | None = None
    declared_eta: int | None = None
    declared_confidence: str | None = None
    latest_finish: int | None = None
    offer_ids: list[str] = Field(default_factory=list)
    hold_id: str | None = None
    appointment_id: str | None = None
    handoff_id: str | None = None
    turn: int = 0
    last_user_text: str = ""       # masked
    safety_checked: bool = False

    def declaration(self) -> Declaration | None:
        if self.declared_eta is None:
            return None
        return Declaration(self.declared_eta, self.declared_confidence or "MEDIUM")


@dataclass
class ToolContext:
    conn: sqlite3.Connection
    driver_id: str
    thread_id: str
    state: ConversationState
    now: int


# --- input schemas -----------------------------------------------------------
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolveShipmentIn(_In):
    hint: str | None = Field(None, max_length=40, description="Shipment id or words the driver used, if any")


class ShipmentIn(_In):
    shipment_id: str = Field(pattern=r"^SHP\d{3,6}$")


class RecordEtaIn(_In):
    shipment_id: str = Field(pattern=r"^SHP\d{3,6}$")
    kind: Literal["ARRIVAL_DELAY", "CLOCK_TIME", "REPAIR_TIME", "NO_CHANGE"]
    delay_minutes: int | None = Field(None, ge=0, le=1440)
    clock_time: str | None = Field(None, pattern=HHMM)


class FeasibleIn(_In):
    shipment_id: str = Field(pattern=r"^SHP\d{3,6}$")
    latest_finish: str | None = Field(None, pattern=HHMM, description="Latest clock time the driver can finish unloading")
    limit: int = Field(3, ge=1, le=3)


class HoldIn(_In):
    offer_id: str = Field(pattern=r"^OFF-[0-9a-f]{10}$")


class HoldIdIn(_In):
    hold_id: str = Field(pattern=r"^HOLD-[0-9a-f]{10}$")


class EscalateIn(_In):
    reason_code: Literal["DRIVER_REQUEST", "POLICY_CONFLICT", "REPEATED_CLARIFICATION", "PENALTY_QUESTION",
                         "CONTRADICTORY_DATA", "SAFETY", "OUT_OF_SCOPE"]
    summary: str = Field(max_length=500)


# --- helpers -----------------------------------------------------------------
def _err(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": code, "message": message, **extra}


def _key(ctx: ToolContext, tool: str, args: dict) -> str:
    h = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]
    return f"{ctx.thread_id}:{ctx.state.turn}:{tool}:{h}"


def _owned(ctx: ToolContext, shipment_id: str) -> dict | None:
    row = ctx.conn.execute("SELECT driver_id FROM shipments WHERE shipment_id=?", (shipment_id,)).fetchone()
    if row is None:
        return _err("NOT_FOUND", "No such shipment.")
    if row["driver_id"] != ctx.driver_id:
        return _err("MISMATCH", "That shipment is not assigned to you. I cannot share or change it.")
    if ctx.state.shipment_id and shipment_id != ctx.state.shipment_id:
        return _err("MISMATCH", f"This conversation is about {ctx.state.shipment_id}.")
    return None


def _advance(ctx: ToolContext, event: Event) -> None:
    ctx.state.stage = next_stage(ctx.state.stage, event)


def _clock_to_epoch(ctx: ToolContext, clock: str) -> int:
    t = at_clock(ctx.now, clock)
    return t if t >= ctx.now - 3600 else t + 86400   # a time well before now means tomorrow


def _state_read(ctx: ToolContext, shipment_id: str) -> dict:
    eta = resolve_eta(ctx.conn, shipment_id, ctx.state.declaration())
    appt = ctx.conn.execute(
        "SELECT a.appointment_id, a.appointment_status, d.dock_code, s.slot_start_ts, s.slot_end_ts "
        "FROM appointments a JOIN appointment_slots s USING(slot_id) JOIN docks d ON d.dock_id=s.dock_id "
        "WHERE a.shipment_id=? AND a.is_current=1 AND a.appointment_status IN "
        "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')", (shipment_id,)).fetchone()
    return {"eta": hhmm(eta.eta_epoch), "eta_source": eta.source, "eta_confidence": eta.confidence,
            "margin_min": eta.margin_min,
            "current_appointment": dict(appt) if appt else None}


# --- the tools ---------------------------------------------------------------
def resolve_shipment(ctx: ToolContext, a: ResolveShipmentIn) -> dict:
    live = policy()["feasibility"]["rebookable_shipment_statuses"]
    mine = ctx.conn.execute(
        "SELECT shipment_id, destination_facility_id, original_eta_ts, current_status FROM shipments "
        "WHERE driver_id=? ORDER BY original_eta_ts", (ctx.driver_id,)).fetchall()
    active = [r for r in mine if r["current_status"] in live]
    hint = (a.hint or "").upper().replace(" ", "")
    if hint.startswith("SHP"):
        owner = ctx.conn.execute("SELECT driver_id, current_status FROM shipments WHERE shipment_id=?",
                                 (hint,)).fetchone()
        if owner is None:
            return {"ok": True, "status": "NONE", "message": f"No shipment {hint} found."}
        if owner["driver_id"] != ctx.driver_id:
            return {"ok": True, "status": "MISMATCH",
                    "message": "That shipment is not assigned to you. I cannot share or change it."}
        if owner["current_status"] not in live:
            return {"ok": True, "status": "NOT_ACTIVE", "shipment_id": hint,
                    "shipment_status": owner["current_status"],
                    "message": f"{hint} is {owner['current_status']}; it cannot be rebooked."}
        active = [r for r in active if r["shipment_id"] == hint]
    if len(active) == 1:
        ctx.state.shipment_id = active[0]["shipment_id"]
        _advance(ctx, Event.SHIPMENT_CONFIRMED)
        return {"ok": True, "status": "UNIQUE", "shipment_id": ctx.state.shipment_id,
                "planned_eta": hhmm(to_epoch(active[0]["original_eta_ts"]))}
    if not active:
        return {"ok": True, "status": "NONE", "message": "You have no active shipment I can rebook."}
    return {"ok": True, "status": "AMBIGUOUS",
            "candidates": [{"shipment_id": r["shipment_id"], "planned_eta": hhmm(to_epoch(r["original_eta_ts"]))}
                           for r in active]}


def get_shipment_context(ctx: ToolContext, a: ShipmentIn) -> dict:
    s = ctx.conn.execute("SELECT shipment_id, priority_code, required_dock_type, temperature_control_required, "
                         "load_weight_kg, expected_unload_min, current_status FROM shipments WHERE shipment_id=?",
                         (a.shipment_id,)).fetchone()
    return {"ok": True, "status": "OK", "shipment": {**dict(s), "refrigerated": bool(s["temperature_control_required"])},
            **_state_read(ctx, a.shipment_id)}


def record_eta_declaration(ctx: ToolContext, a: RecordEtaIn) -> dict:
    if a.kind == "NO_CHANGE":
        _advance(ctx, Event.FACTS_KNOWN)
        return {"ok": True, "status": "UNCHANGED", **_state_read(ctx, a.shipment_id)}
    base = resolve_eta(ctx.conn, a.shipment_id).eta_epoch
    plan = ctx.conn.execute("SELECT original_eta_ts FROM shipments WHERE shipment_id=?",
                            (a.shipment_id,)).fetchone()[0]
    try:
        d = declaration_from_driver(
            DelayKind(a.kind), base_eta_epoch=to_epoch(plan) if a.kind == "ARRIVAL_DELAY" else base,
            delay_minutes=a.delay_minutes,
            clock_epoch=_clock_to_epoch(ctx, a.clock_time) if a.clock_time else None,
            confidence=policy()["eta"]["confirmed_declaration_confidence"])
    except NeedClockTime as e:
        return _err("NEED_CLOCK_TIME", str(e))
    except ValueError as e:
        return _err("INVALID_ARGUMENTS", str(e))
    ctx.state.declared_eta, ctx.state.declared_confidence = d.eta_epoch, d.confidence
    ctx.conn.execute("INSERT INTO audit_events(ts, actor, action, thread_id, shipment_id, detail_json) "
                     "VALUES (?,?,?,?,?,?)", (ctx.now, "driver", "ETA_DECLARED", ctx.thread_id, a.shipment_id,
                                              json.dumps({"kind": a.kind, "eta": hhmm(d.eta_epoch)})))
    _advance(ctx, Event.FACTS_KNOWN)
    return {"ok": True, "status": "RECORDED", **_state_read(ctx, a.shipment_id),
            "note": "Read this time back to the driver."}


def get_feasible_slots(ctx: ToolContext, a: FeasibleIn) -> dict:
    if a.latest_finish:
        ctx.state.latest_finish = _clock_to_epoch(ctx, a.latest_finish)
    eta = resolve_eta(ctx.conn, a.shipment_id, ctx.state.declaration())
    feasible, checks = find_feasible_slots(ctx.conn, a.shipment_id, now=ctx.now, driver_id=ctx.driver_id,
                                           eta=eta, latest_finish=ctx.state.latest_finish,
                                           thread_id=ctx.thread_id)
    if not feasible:
        summary = reason_summary(checks)
        ho = create_handoff(ctx.conn, thread_id=ctx.thread_id, shipment_id=a.shipment_id,
                            driver_id=ctx.driver_id, reason_code="NO_FEASIBLE_SLOT",
                            summary={"what_driver_said": ctx.state.last_user_text,
                                     "why": "No slot passes every check", "reason_counts": summary},
                            options_shown=[], state_read={**_state_read(ctx, a.shipment_id), "reason_counts": summary},
                            not_done=["No slot offered", "Existing booking not changed",
                                      "No priority override attempted"], now=ctx.now)
        ctx.state.handoff_id = ho["handoff_id"]
        if ctx.state.stage == Stage.OFFER:
            _advance(ctx, Event.NO_FEASIBLE_SLOT)
        else:
            _advance(ctx, Event.ESCALATED)
        return {"ok": True, "status": "NO_FEASIBLE_SLOT", "reason_counts": summary,
                "eta": hhmm(eta.eta_epoch), "handoff_id": ho["handoff_id"], "owner": ho["owner"],
                "coordinator_deadline": hhmm(ho["deadline_at"])}
    opts = rank_options(feasible, eta, a.limit)
    out = []
    with_ids = []
    for o in opts:
        oid = "OFF-" + uuid.uuid4().hex[:10]
        ctx.conn.execute("INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?)",
                         (oid, ctx.thread_id, a.shipment_id, o.slot_id, eta.eta_epoch, eta.source, o.rank,
                          int(o.needs_approval), ctx.now))
        with_ids.append(oid)
        out.append({"option": o.rank, "offer_id": oid, "dock": o.dock_code, "start": hhmm(o.start),
                    "end": hhmm(o.end), "needs_approval": o.needs_approval, "why": o.why})
    ctx.state.offer_ids = with_ids
    return {"ok": True, "status": "OPTIONS", "nothing_reserved": True, "eta": hhmm(eta.eta_epoch),
            "eta_confidence": eta.confidence, "options": out}


def hold_slot(ctx: ToolContext, a: HoldIn) -> dict:
    off = ctx.conn.execute("SELECT * FROM offers WHERE offer_id=?", (a.offer_id,)).fetchone()
    if off is None or off["thread_id"] != ctx.thread_id or off["shipment_id"] != ctx.state.shipment_id:
        return _err("UNKNOWN_OFFER", "That option was not shown in this conversation.")
    r = commit.hold_slot(ctx.conn, shipment_id=off["shipment_id"], slot_id=off["slot_id"], thread_id=ctx.thread_id,
                         driver_id=ctx.driver_id, idempotency_key=_key(ctx, "hold_slot", a.model_dump()),
                         now=ctx.now, offer_id=a.offer_id, confirmed=ctx.state.declaration())
    if r["status"] == "ACTIVE":
        ctx.state.hold_id = r["hold_id"]
        if ctx.state.stage == Stage.OFFER:
            _advance(ctx, Event.PICKED)
        return {"ok": True, "status": "HELD", "hold_id": r["hold_id"], "held_until": hhmm(r["expires_at"]),
                "needs_approval": r["needs_approval"], "slot": _slot_label(ctx, off["slot_id"]),
                "note": "Not booked yet. Ask the driver to reply YES to confirm."}
    return {"ok": True, "status": "REFUSED", "reason_codes": r["reason_codes"],
            "note": "That slot is no longer available. Call get_feasible_slots for fresh options."}


def confirm_booking(ctx: ToolContext, a: HoldIdIn) -> dict:
    if a.hold_id != ctx.state.hold_id:
        return _err("UNKNOWN_HOLD", "That hold is not this conversation's current hold.")
    if not is_explicit_yes(ctx.state.last_user_text):
        return _err("NEEDS_EXPLICIT_YES", "The driver has not clearly said yes in this message. Ask them to reply YES.")
    _advance(ctx, Event.SAID_YES)
    r = commit.confirm_booking(ctx.conn, hold_id=a.hold_id, thread_id=ctx.thread_id, driver_id=ctx.driver_id,
                               idempotency_key=_key(ctx, "confirm_booking", a.model_dump()), now=ctx.now,
                               confirmed=ctx.state.declaration())
    if r["status"] == "CONFIRMED":
        ctx.state.appointment_id = r["appointment_id"]
        _advance(ctx, Event.COMMITTED)
        return {"ok": True, "status": "CONFIRMED", "appointment_id": r["appointment_id"],
                "slot": _slot_label(ctx, r["slot_id"]), "replaced_appointment_id": r["replaced_appointment_id"]}
    if r["status"] == "NEEDS_APPROVAL":
        ho = create_handoff(ctx.conn, thread_id=ctx.thread_id, shipment_id=ctx.state.shipment_id,
                            driver_id=ctx.driver_id, reason_code="NEEDS_APPROVAL",
                            summary={"what_driver_said": ctx.state.last_user_text,
                                     "approval_reasons": r["approval_reasons"], "hold_id": a.hold_id},
                            options_shown=ctx.state.offer_ids,
                            state_read=_state_read(ctx, ctx.state.shipment_id),
                            not_done=["Booking NOT confirmed; slot held pending approval"], now=ctx.now)
        ctx.state.handoff_id = ho["handoff_id"]
        _advance(ctx, Event.NEEDS_APPROVAL)
        return {"ok": True, "status": "NEEDS_APPROVAL", "approval_reasons": r["approval_reasons"],
                "handoff_id": ho["handoff_id"], "coordinator_deadline": hhmm(ho["deadline_at"]),
                "slot": _slot_label(ctx, r["slot_id"])}
    ctx.state.hold_id = None
    _advance(ctx, Event.REFUSED)
    return {"ok": True, "status": "REFUSED", "reason_codes": r["reason_codes"],
            "note": "Not booked. Existing booking unchanged. Offer fresh options."}


def release_hold(ctx: ToolContext, a: HoldIdIn) -> dict:
    r = commit.release_hold(ctx.conn, hold_id=a.hold_id, thread_id=ctx.thread_id,
                            idempotency_key=_key(ctx, "release_hold", a.model_dump()), now=ctx.now)
    if r["status"] == "RELEASED":
        ctx.state.hold_id = None
        if ctx.state.stage in (Stage.HOLD, Stage.CONFIRM):
            _advance(ctx, Event.HOLD_LOST)
        return {"ok": True, "status": "RELEASED"}
    return _err("UNKNOWN_HOLD", "No such hold in this conversation.")


def escalate_to_coordinator(ctx: ToolContext, a: EscalateIn) -> dict:
    sid = ctx.state.shipment_id
    ho = create_handoff(ctx.conn, thread_id=ctx.thread_id, shipment_id=sid, driver_id=ctx.driver_id,
                        reason_code=a.reason_code,
                        summary={"agent_summary": a.summary, "what_driver_said": ctx.state.last_user_text},
                        options_shown=ctx.state.offer_ids,
                        state_read=_state_read(ctx, sid) if sid else {"shipment": "not identified"},
                        not_done=["No booking change made by the agent"], now=ctx.now)
    ctx.state.handoff_id = ho["handoff_id"]
    _advance(ctx, Event.ESCALATED)
    return {"ok": True, "status": "ESCALATED", "handoff_id": ho["handoff_id"],
            "coordinator_deadline": hhmm(ho["deadline_at"])}


def _slot_label(ctx: ToolContext, slot_id: str) -> dict:
    r = ctx.conn.execute("SELECT d.dock_code, t.start_epoch, t.end_epoch FROM appointment_slots s "
                         "JOIN docks d ON d.dock_id=s.dock_id JOIN slot_times t USING(slot_id) WHERE slot_id=?",
                         (slot_id,)).fetchone()
    return {"dock": r["dock_code"], "start": hhmm(r["start_epoch"]), "end": hhmm(r["end_epoch"])}


# --- registry and dispatch -----------------------------------------------------
TOOLS: dict[str, tuple[type[_In], Callable[[ToolContext, Any], dict], str]] = {
    "resolve_shipment": (ResolveShipmentIn, resolve_shipment,
                         "Find which of the signed-in driver's shipments this chat is about. Use first."),
    "get_shipment_context": (ShipmentIn, get_shipment_context,
                             "Read the shipment's booking, priority, dock type and resolved ETA. Read-only."),
    "record_eta_declaration": (RecordEtaIn, record_eta_declaration,
                               "Store the driver's CONFIRMED arrival statement. kind=ARRIVAL_DELAY needs "
                               "delay_minutes (minutes later than planned); CLOCK_TIME needs clock_time HH:MM; "
                               "REPAIR_TIME means you must ask for a clock time; NO_CHANGE if the ETA is unchanged."),
    "get_feasible_slots": (FeasibleIn, get_feasible_slots,
                           "The ONLY source of slot options (max 3). Nothing is reserved. If none exist, code "
                           "escalates to a coordinator automatically."),
    "hold_slot": (HoldIn, hold_slot, "Hold the option the driver picked (offer_id from get_feasible_slots) for 5 minutes. Not a booking."),
    "confirm_booking": (HoldIdIn, confirm_booking,
                        "Commit the held slot. Only after the driver clearly said YES in their latest message."),
    "release_hold": (HoldIdIn, release_hold, "Give back a held slot if the driver changes their mind."),
    "escalate_to_coordinator": (EscalateIn, escalate_to_coordinator,
                                "Hand off to a human coordinator with a short summary. Use when the driver asks "
                                "for a person, asks about penalties, or you cannot proceed."),
}

SHIPMENT_ARG_TOOLS = {"get_shipment_context", "record_eta_declaration", "get_feasible_slots"}


def dispatch(name: str, args: dict | None, ctx: ToolContext) -> dict:
    if name not in TOOLS:
        return _err("UNKNOWN_TOOL", f"No tool named {name}.")
    if name not in tools_for(ctx.state.stage):
        return _err("TOOL_NOT_ALLOWED_AT_STAGE", f"{name} is not available at stage {ctx.state.stage.value}.",
                    allowed=sorted(tools_for(ctx.state.stage)))
    schema, fn, _ = TOOLS[name]
    try:
        parsed = schema.model_validate(args or {})
    except ValidationError as e:
        return _err("INVALID_ARGUMENTS", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
    if name in SHIPMENT_ARG_TOOLS:
        bad = _owned(ctx, parsed.shipment_id)
        if bad:
            return bad
    try:
        out = fn(ctx, parsed)
    except commit.IdempotencyConflict as e:
        return _err("IDEMPOTENCY_CONFLICT", str(e))
    except sqlite3.OperationalError as e:
        return _err("DATABASE_BUSY", "The booking system is busy. A coordinator will help.", detail=str(e)[:80])
    except KeyError as e:
        return _err("NOT_FOUND", f"Not found: {e}")
    out["stage"] = ctx.state.stage.value
    return out


def tool_schemas(stage: Stage) -> list[dict]:
    """OpenAI-style function schemas for the tools allowed at this stage only."""
    out = []
    for name in sorted(tools_for(stage)):
        schema, _, desc = TOOLS[name]
        js = schema.model_json_schema()
        js.pop("title", None)
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": js}})
    return out
