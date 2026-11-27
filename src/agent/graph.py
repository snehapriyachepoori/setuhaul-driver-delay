"""The conversation layer: a LangGraph graph around the code-owned stage machine.

  entry  -> (duplicate | safety | injection | closed case) -> finish
         -> agent <-> tools   (max 6 tool calls per turn, stage allowlist enforced in dispatch)
         -> guard (output checks: no unbacked "confirmed", every time grounded in a tool result)
         -> finish (store reply for dedupe, write the audit row)

State is checkpointed in SQLite by thread_id, so a restart resumes the conversation.
Runtime objects (DB connection, model) are NOT stored in the checkpoint; they are looked up by id.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.agent.llm import ModelUnavailable
from src.agent.rules_model import RulesModel
from src.capacity.handoff import create_handoff
from src.guardrails.input import has_safety_cue, looks_like_injection, mask_pii
from src.stages import Event, Stage, TERMINAL, next_stage
from src.timeutil import hhmm
from src.tools.core import ConversationState, ToolContext, dispatch, tool_schemas

PROMPT = (Path(__file__).parent / "prompts" / "system_v1.md").read_text(encoding="utf-8")
PROMPT_VERSION = "system_v1"
MAX_TOOL_CALLS = 6
HISTORY_LIMIT = 24

SAFETY_MSG = ("Please stay safe. Are you and the truck safe and off the road? A coordinator has been alerted "
              "and will call you within 5 minutes. I will not change any booking until then.")
INJECTION_MSG = "I can only help with your own shipment's delay and dock slot. I cannot change my rules."
FALLBACK_MSG = "Sorry, I am having trouble right now. A coordinator has been asked to contact you. Your booking is unchanged."

_RUNTIME: dict[str, dict[str, Any]] = {}


class TurnState(TypedDict, total=False):
    input_text: str
    msg_key: str
    messages: list[dict]
    conv: dict
    reply: str
    route: str
    turn_calls: int
    turn_log: list[dict]


def _rt(config) -> dict:
    return _RUNTIME[config["configurable"]["runtime_id"]]


def _ctx(config, conv: ConversationState) -> ToolContext:
    rt = _rt(config)
    return ToolContext(rt["conn"], rt["driver_id"], config["configurable"]["thread_id"], conv, rt["now"]())


# --- nodes ---------------------------------------------------------------------
def entry(state: TurnState, config) -> dict:
    rt = _rt(config)
    conn: sqlite3.Connection = rt["conn"]
    thread_id = config["configurable"]["thread_id"]
    key = state.get("msg_key") or uuid.uuid4().hex
    dup = conn.execute("SELECT reply_json FROM inbound_messages WHERE channel_msg_key=?", (key,)).fetchone()
    if dup and dup[0]:
        return {"reply": json.loads(dup[0])["reply"], "route": "duplicate", "turn_log": [{"duplicate": key}]}

    conv = ConversationState(**(state.get("conv") or {}))
    text = mask_pii(state["input_text"])
    conv.turn += 1
    conv.last_user_text = text
    messages = list(state.get("messages") or []) + [{"role": "user", "content": text}]
    out = {"messages": messages, "turn_calls": 0, "turn_log": [], "reply": "", "msg_key": key}
    ctx = _ctx(config, conv)

    if has_safety_cue(text) and conv.stage not in TERMINAL:
        ho = create_handoff(conn, thread_id=thread_id, shipment_id=conv.shipment_id, driver_id=ctx.driver_id,
                            reason_code="SAFETY", summary={"what_driver_said": text, "why": "safety cue"},
                            options_shown=conv.offer_ids, state_read={"stage_before": conv.stage.value},
                            not_done=["No slot offered", "No booking changed"], now=ctx.now)
        conv.handoff_id = ho["handoff_id"]
        conv.stage = Stage.ESCALATE
        return {**out, "conv": conv.model_dump(mode="json"), "reply": SAFETY_MSG, "route": "finish",
                "turn_log": [{"code": "SAFETY_HANDOFF", "handoff_id": ho["handoff_id"]}]}
    if conv.stage == Stage.SAFETY:
        conv.stage = next_stage(conv.stage, Event.NO_CUE)
    if conv.stage in TERMINAL:
        return {**out, "conv": conv.model_dump(mode="json"), "reply": _closed_message(conn, conv), "route": "finish"}
    if looks_like_injection(text):
        return {**out, "conv": conv.model_dump(mode="json"), "reply": INJECTION_MSG, "route": "finish",
                "turn_log": [{"code": "INJECTION_REFUSED"}]}
    return {**out, "conv": conv.model_dump(mode="json"), "route": "agent"}


def agent(state: TurnState, config) -> dict:
    rt = _rt(config)
    conv = ConversationState(**state["conv"])
    facts = {k: v for k, v in {"shipment_id": conv.shipment_id, "hold_id": conv.hold_id,
                                "declared_eta": hhmm(conv.declared_eta) if conv.declared_eta else None,
                                "handoff_id": conv.handoff_id}.items() if v}
    tools = tool_schemas(conv.stage)
    system = PROMPT.format(stage=conv.stage.value, tools=", ".join(t["function"]["name"] for t in tools) or "none",
                           facts=json.dumps(facts))
    history = _trim(state["messages"])
    try:
        r = rt["model"].chat([{"role": "system", "content": system}] + history, tools)
    except ModelUnavailable as e:
        ctx = _ctx(config, conv)
        ho = create_handoff(rt["conn"], thread_id=ctx.thread_id, shipment_id=conv.shipment_id,
                            driver_id=ctx.driver_id, reason_code="SYSTEM_FAILURE",
                            summary={"what_driver_said": conv.last_user_text, "error": str(e)[:120]},
                            options_shown=conv.offer_ids, state_read={"stage": conv.stage.value},
                            not_done=["Model unavailable; nothing changed"], now=ctx.now)
        conv.handoff_id, conv.stage = ho["handoff_id"], Stage.ESCALATE
        return {"conv": conv.model_dump(mode="json"), "reply": FALLBACK_MSG, "route": "finish",
                "turn_log": state.get("turn_log", []) + [{"code": "MODEL_UNAVAILABLE"}]}
    log = state.get("turn_log", []) + [{"model": r.model, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                                         "latency_ms": r.latency_ms}]
    msg: dict = {"role": "assistant", "content": r.content or ""}
    if r.tool_calls:
        msg["tool_calls"] = [{"id": c["id"], "type": "function",
                              "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                             for c in r.tool_calls]
        return {"messages": state["messages"] + [msg], "route": "tools", "turn_log": log}
    return {"messages": state["messages"] + [msg], "reply": r.content or "", "route": "guard", "turn_log": log}


def tools(state: TurnState, config) -> dict:
    conv = ConversationState(**state["conv"])
    ctx = _ctx(config, conv)
    messages = list(state["messages"])
    calls = state.get("turn_calls", 0)
    log = list(state.get("turn_log", []))
    for c in messages[-1]["tool_calls"]:
        name = c["function"]["name"]
        try:
            args = json.loads(c["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {"_bad_json": True}
        if calls >= MAX_TOOL_CALLS:
            out = {"ok": False, "error": "TOOL_LIMIT", "message": "Too many tool calls this turn."}
        else:
            calls += 1
            out = dispatch(name, args, ctx)
        messages.append({"role": "tool", "tool_call_id": c["id"], "name": name, "content": json.dumps(out)})
        log.append({"tool": name, "args": json.loads(mask_pii(json.dumps(args))),
                    "status": out.get("status") or out.get("error"), "stage_after": ctx.state.stage.value})
    route = "agent"
    if calls >= MAX_TOOL_CALLS and conv.stage not in TERMINAL:
        ho = create_handoff(ctx.conn, thread_id=ctx.thread_id, shipment_id=conv.shipment_id, driver_id=ctx.driver_id,
                            reason_code="SYSTEM_FAILURE", summary={"why": "tool call limit reached",
                                                                   "what_driver_said": conv.last_user_text},
                            options_shown=conv.offer_ids, state_read={"stage": conv.stage.value},
                            not_done=["Turn stopped at the tool-call limit"], now=ctx.now)
        conv.handoff_id, conv.stage = ho["handoff_id"], Stage.ESCALATE
        route = "agent"
    return {"messages": messages, "conv": conv.model_dump(mode="json"), "turn_calls": calls, "turn_log": log, "route": route}


FAKE_DONE = re.compile(r"\b(not\s+(yet\s+)?(confirmed|booked)|(confirmed|booked)\s+yet|to\s+confirm)\b", re.I)


def guard(state: TurnState, config) -> dict:
    """Output guardrails: nothing the driver reads may outrun what code actually did."""
    msgs = state["messages"]
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    turn_results = [json.loads(m["content"]) for m in msgs[last_user + 1:] if m["role"] == "tool"]
    # A time is grounded if a tool returned it OR the driver said it (reading a driver's time back is allowed).
    all_results_text = " ".join(m["content"] or "" for m in msgs if m["role"] in ("tool", "user"))
    all_results_text += " " + " ".join(f"{int(h):02d}:{mm}" for h, mm in
                                       re.findall(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", all_results_text))
    reply = mask_pii(state.get("reply") or "")
    problems = []
    if not reply.strip():
        problems.append("EMPTY_REPLY")
    cleaned = FAKE_DONE.sub("", reply)
    if re.search(r"\b(confirmed|booked)\b", cleaned, re.I) and not any(r.get("status") == "CONFIRMED" for r in turn_results):
        problems.append("UNBACKED_CONFIRMATION")
    for t in re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", reply):
        hm = f"{int(t[0]):02d}:{t[1]}"
        if hm not in all_results_text:
            problems.append(f"UNGROUNDED_TIME_{hm}")
    log = list(state.get("turn_log", []))
    if problems:
        safe = RulesModel._template(turn_results[-1]) if turn_results else \
            "Sorry, let me check that again. Could you repeat what you need?"
        log.append({"code": "OUTPUT_GUARD_REPLACED", "problems": problems})
        reply = safe
    return {"reply": reply, "turn_log": log}


def finish(state: TurnState, config) -> dict:
    rt = _rt(config)
    conn = rt["conn"]
    thread_id = config["configurable"]["thread_id"]
    conv = ConversationState(**state["conv"])
    reply = state.get("reply") or ""
    now = rt["now"]()
    messages = list(state["messages"])
    if not messages or messages[-1]["role"] != "assistant" or messages[-1].get("content") != reply:
        messages.append({"role": "assistant", "content": reply})
    conn.execute("INSERT OR IGNORE INTO inbound_messages VALUES (?,?,?,?)",
                 (state["msg_key"], thread_id, now, json.dumps({"reply": reply})))
    conn.execute("INSERT INTO audit_events(ts, actor, action, thread_id, shipment_id, detail_json) VALUES (?,?,?,?,?,?)",
                 (now, "agent", "TURN", thread_id, conv.shipment_id,
                  json.dumps({"turn": conv.turn, "stage": conv.stage.value, "prompt": PROMPT_VERSION,
                              "log": state.get("turn_log", [])})))
    return {"messages": messages}


def _closed_message(conn, conv: ConversationState) -> str:
    if conv.stage == Stage.DONE:
        return "Your booking is already confirmed. If anything changes, start a new message and I will help."
    row = conn.execute("SELECT deadline_at FROM handoffs WHERE handoff_id=?", (conv.handoff_id,)).fetchone() \
        if conv.handoff_id else None
    by = f" by {hhmm(row[0])}" if row else ""
    return f"A coordinator has your case and will contact you{by}. I will not change anything in the meantime."


def _trim(messages: list[dict]) -> list[dict]:
    """Keep the last messages, but never start on a tool result without its assistant call."""
    m = messages[-HISTORY_LIMIT:]
    while m and m[0]["role"] == "tool":
        m = m[1:]
    return m


# --- build --------------------------------------------------------------------
def _route(state: TurnState) -> str:
    return state.get("route", "finish")


def build_graph(checkpointer):
    g = StateGraph(TurnState)
    g.add_node("entry", entry)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("guard", guard)
    g.add_node("finish", finish)
    g.add_edge(START, "entry")
    g.add_conditional_edges("entry", _route, {"duplicate": END, "finish": "finish", "agent": "agent"})
    g.add_conditional_edges("agent", _route, {"tools": "tools", "guard": "guard", "finish": "finish"})
    g.add_conditional_edges("tools", _route, {"agent": "agent"})
    g.add_edge("guard", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


class DelayService:
    """What a channel (CLI, test, scenario) talks to."""

    def __init__(self, conn: sqlite3.Connection, model, checkpoint_path: str | Path, clock=None):
        self.conn = conn
        self.model = model
        self.clock = clock or (lambda: int(time.time()))
        self._ck_conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        self.graph = build_graph(SqliteSaver(self._ck_conn))

    def handle(self, thread_id: str, driver_id: str, text: str, msg_key: str | None = None) -> dict:
        rid = uuid.uuid4().hex
        _RUNTIME[rid] = {"conn": self.conn, "model": self.model, "driver_id": driver_id, "now": self.clock}
        try:
            cfg = {"configurable": {"thread_id": thread_id, "runtime_id": rid}, "recursion_limit": 40}
            # Mask BEFORE invoke: LangGraph checkpoints the raw input, so a phone must never reach it.
            out = self.graph.invoke({"input_text": mask_pii(text), "msg_key": msg_key or uuid.uuid4().hex}, cfg)
        finally:
            _RUNTIME.pop(rid, None)
        conv = out.get("conv") or {}
        stage = conv.get("stage")
        return {"reply": out.get("reply", ""), "stage": getattr(stage, "value", stage),
                "tool_calls": [x for x in out.get("turn_log", []) if "tool" in x],
                "log": out.get("turn_log", []), "conv": conv}

    def state(self, thread_id: str) -> dict:
        snap = self.graph.get_state({"configurable": {"thread_id": thread_id}})
        return dict(snap.values) if snap else {}

    def close(self):
        self._ck_conn.close()
