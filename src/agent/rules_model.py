"""Option A fallback: a deterministic 'model' made of rules and templates.

Same interface as the LLM adapter (chat(messages, tools) -> ModelReply), so the graph, tools and
guardrails are identical. Used (1) when tool calling is unreliable or the model is down,
(2) as the free, repeatable fake model in conversation tests. It reads simple English/Hinglish only.
"""
from __future__ import annotations

import json
import re
import uuid

from src.agent.llm import ModelReply
from src.guardrails.input import is_explicit_yes

CLOCK_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
AMPM_RE = re.compile(r"\b(1[0-2]|0?[1-9])\s*(am|pm|baje)\b", re.I)
MIN_RE = re.compile(r"(\d{1,3})\s*(?:min|mins|minute|minutes)\b", re.I)
HOUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hour|hours|hr|hrs|ghanta|ghante)\b", re.I)
PICK_WORDS = {"1": 1, "2": 2, "3": 3, "first": 1, "second": 2, "third": 3, "pehla": 1, "doosra": 2, "teesra": 3}
NO_RE = re.compile(r"\b(no|nahi|nahin|cancel|release|don't|dont)\b", re.I)


def _clock(text: str) -> str | None:
    m = CLOCK_RE.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = AMPM_RE.search(text)
    if m:
        h = int(m.group(1)) % 12
        if m.group(2).lower() == "pm" or (m.group(2).lower() == "baje" and h < 7):
            h += 12
        return f"{h:02d}:00"
    return None


def _eta_args(text: str, shipment_id: str) -> dict | None:
    t = text.lower()
    finish = re.search(r"(?:finish|done|khatam|leave)\s*(?:by|before|tak)?\s*", t)
    clock = _clock(t)
    if clock and finish and t.find(clock[:2].lstrip("0")) > finish.start():
        clock = None   # that clock time is a latest-finish time, not an ETA
    if any(w in t for w in ("repair", "fixing", "mechanic", "theek ho")) and not clock:
        m = MIN_RE.search(t) or HOUR_RE.search(t)
        return {"shipment_id": shipment_id, "kind": "REPAIR_TIME", "delay_minutes": _minutes(m) if m else 0}
    if clock and any(w in t for w in ("reach", "arriv", "pahunch", "eta", "at ", "by ")):
        return {"shipment_id": shipment_id, "kind": "CLOCK_TIME", "clock_time": clock}
    m = MIN_RE.search(t) or HOUR_RE.search(t)
    if m and any(w in t for w in ("late", "delay", "der", "later")):
        return {"shipment_id": shipment_id, "kind": "ARRIVAL_DELAY", "delay_minutes": _minutes(m)}
    if clock:
        return {"shipment_id": shipment_id, "kind": "CLOCK_TIME", "clock_time": clock}
    if any(w in t for w in ("option", "slot", "available", "same time", "on time", "unchanged", "kya hai")):
        return {"shipment_id": shipment_id, "kind": "NO_CHANGE"}
    return None


def _minutes(m) -> int:
    v = float(m.group(1))
    return int(v * 60) if "h" in m.group(0).lower() or "ghant" in m.group(0).lower() else int(v)


def _latest_finish(text: str) -> str | None:
    m = re.search(r"(?:finish|done|khatam|leave)\s*(?:by|before|tak)?\s*(.{0,12})", text.lower())
    return _clock(m.group(1)) if m else None


def _call(name: str, args: dict) -> ModelReply:
    return ModelReply(None, [{"id": "call_" + uuid.uuid4().hex[:8], "name": name, "arguments": args}], "rules")


def _say(text: str) -> ModelReply:
    return ModelReply(text, [], "rules")


class RulesModel:
    def chat(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        allowed = {t["function"]["name"] for t in tools}
        last_user = next(i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user")
        text = messages[last_user]["content"] or ""
        turn_results = [json.loads(m["content"]) | {"_tool": m.get("name", "")}
                        for m in messages[last_user + 1:] if m["role"] == "tool"]
        facts = self._facts(messages)
        sid = facts.get("shipment_id")

        if turn_results:
            r = turn_results[-1]
            nxt = self._follow_up(r, text, sid, allowed)
            return nxt if nxt else _say(self._template(r))

        # first decision of the turn, from the user's words
        if "resolve_shipment" in allowed:
            m = re.search(r"SHP\d{3,6}", text.upper())
            return _call("resolve_shipment", {"hint": m.group(0)} if m else {})
        if "record_eta_declaration" in allowed and sid:
            a = _eta_args(text, sid)
            if a:
                return _call("record_eta_declaration", a)
            return _say("When do you expect to reach the gate? A clock time like 14:30 is best. "
                        "If your time is unchanged, say 'options'.")
        if "confirm_booking" in allowed and facts.get("hold_id"):
            if is_explicit_yes(text):
                return _call("confirm_booking", {"hold_id": facts["hold_id"]})
            if NO_RE.search(text):
                return _call("release_hold", {"hold_id": facts["hold_id"]})
            return _say("Please reply YES to confirm the held slot, or NO to release it.")
        if "hold_slot" in allowed and facts.get("offers"):
            pick = next((PICK_WORDS[w] for w in re.findall(r"\w+", text.lower()) if w in PICK_WORDS), None)
            if pick and pick <= len(facts["offers"]):
                return _call("hold_slot", {"offer_id": facts["offers"][pick - 1]})
        if "get_feasible_slots" in allowed and sid:
            args = {"shipment_id": sid}
            if lf := _latest_finish(text):
                args["latest_finish"] = lf
            return _call("get_feasible_slots", args)
        return _say("I can help you report a delay and look at new dock slots for your shipment.")

    @staticmethod
    def _facts(messages: list[dict]) -> dict:
        f: dict = {}
        for m in messages:
            if m["role"] != "tool":
                continue
            r = json.loads(m["content"])
            if r.get("shipment_id") and r.get("status") == "UNIQUE":
                f["shipment_id"] = r["shipment_id"]
            if r.get("status") == "OPTIONS":
                f["offers"] = [o["offer_id"] for o in r["options"]]
            if r.get("status") == "HELD":
                f["hold_id"] = r["hold_id"]
            if r.get("status") in ("RELEASED", "CONFIRMED", "REFUSED"):
                f.pop("hold_id", None)
        for m in messages:      # the system prompt carries the code-owned facts too
            if m["role"] == "system":
                mm = re.search(r'"shipment_id": "(SHP\d+)"', m["content"])
                if mm:
                    f.setdefault("shipment_id", mm.group(1))
                mm = re.search(r'"hold_id": "(HOLD-[0-9a-f]+)"', m["content"])
                if mm:
                    f.setdefault("hold_id", mm.group(1))
        return f

    @staticmethod
    def _follow_up(r: dict, text: str, sid: str | None, allowed: set) -> ModelReply | None:
        st = r.get("status")
        if st == "UNIQUE" and "record_eta_declaration" in allowed:
            a = _eta_args(text, r["shipment_id"])
            return _call("record_eta_declaration", a) if a else None
        if st in ("RECORDED", "UNCHANGED") and "get_feasible_slots" in allowed:
            args = {"shipment_id": sid or r.get("shipment_id")}
            if lf := _latest_finish(text):
                args["latest_finish"] = lf
            return _call("get_feasible_slots", args) if args["shipment_id"] else None
        if st == "REFUSED" and r["_tool"] == "hold_slot" and "get_feasible_slots" in allowed and sid:
            return _call("get_feasible_slots", {"shipment_id": sid})
        return None

    @staticmethod
    def _template(r: dict) -> str:
        st = r.get("status") or r.get("error")
        if st == "UNIQUE":
            return (f"I found your shipment {r['shipment_id']} (planned {r['planned_eta']}). When do you expect "
                    f"to reach the gate? If your time is unchanged, say 'options'.")
        if st == "AMBIGUOUS":
            c = ", ".join(f"{x['shipment_id']} (planned {x['planned_eta']})" for x in r["candidates"])
            return f"You have more than one load: {c}. Which one is this about?"
        if st in ("MISMATCH", "NONE", "NOT_ACTIVE"):
            return r.get("message", "I cannot act on that shipment.")
        if st == "OPTIONS":
            lines = [f"{o['option']}) Dock {o['dock']} {o['start']}-{o['end']}"
                     + (" (needs coordinator approval)" if o["needs_approval"] else "") for o in r["options"]]
            return (f"With your arrival about {r['eta']}, these slots work. Nothing is reserved yet: "
                    + "; ".join(lines) + ". Reply 1, 2 or 3.")
        if st == "NO_FEASIBLE_SLOT":
            return (f"I cannot find a safe automatic slot for your load after {r['eta']}. I have alerted a "
                    f"coordinator, who will contact you by {r['coordinator_deadline']}. Your current booking "
                    f"has not been changed.")
        if st == "HELD":
            s = r["slot"]
            extra = " A coordinator must approve it after you confirm." if r.get("needs_approval") else ""
            return (f"I have held Dock {s['dock']} {s['start']}-{s['end']} for you until {r['held_until']}. "
                    f"It is not booked yet. Reply YES to confirm.{extra}")
        if st == "CONFIRMED":
            s = r["slot"]
            return f"Confirmed: Dock {s['dock']}, {s['start']}-{s['end']}. Your old booking is released."
        if st == "NEEDS_APPROVAL":
            s = r["slot"]
            return (f"Dock {s['dock']} {s['start']} is held while a coordinator approves it. You will hear back "
                    f"by {r['coordinator_deadline']}. It is not confirmed yet.")
        if st == "REFUSED":
            return "Sorry, that slot was just taken before I could secure it. Your booking is unchanged."
        if st == "RELEASED":
            return "I released the hold. Your existing booking is unchanged. Say 'options' to see slots again."
        if st == "ESCALATED":
            return f"I have passed this to a coordinator, who will contact you by {r['coordinator_deadline']}."
        if st == "NEED_CLOCK_TIME":
            return "Is that the repair time? What time do you expect to reach the gate?"
        if st == "NEEDS_EXPLICIT_YES":
            return "Please reply YES to confirm the held slot, or NO to release it."
        return "Sorry, I could not do that. A coordinator can help if needed."
