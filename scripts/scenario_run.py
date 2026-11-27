"""Scripted scenario run -> docs/scenario_run.md (submission item 4).

Two drivers on the real snapshot, ending in ONE escalation:
  Case 1  SHP1013 (DRV013): vague "late" message -> clarify -> options -> hold -> confirm.
  Case 2  SHP1015 (DRV015): reefer, ETA 18:30, D5 under maintenance 18:00-22:00 -> no feasible slot
          -> code creates one complete hand-off for a coordinator.

Run:  python run.py scenario                 (uses MODEL_ROUTE from .env, e.g. openrouter)
      python run.py scenario --model rules   (no model, option A fallback)
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.graph import DelayService  # noqa: E402
from src.agent.llm import make_model  # noqa: E402
from src.auth import start_driver_session  # noqa: E402
from src.capacity.handoff import missing_fields  # noqa: E402
from src.db import connect, make_work_copy  # noqa: E402
from src.timeutil import hhmm, to_epoch, to_ist  # noqa: E402

CASES = [
    {"title": "Case 1: SHP1013, vague delay, clarify, rebook", "phone": "+91-9000010013", "thread": "SCN-1013",
     "start": "2026-08-04T10:00:00+05:30",
     "turns": ["Late", "I will reach the gate at 11:40", "1", "yes"]},
    {"title": "Case 2: SHP1015, reefer with no feasible slot, escalation", "phone": "+91-9000010015",
     "thread": "SCN-1015", "start": "2026-08-04T16:30:00+05:30",
     "turns": ["SHP1015 reefer is delayed, I will reach Jaipur at 18:30. Any slot?",
               "Is there anything at all tonight?"]},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="openrouter | ollama | rules (default: MODEL_ROUTE in .env)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "scenario_run.md"))
    a = ap.parse_args()

    db = make_work_copy(ROOT / "data" / "work_scenario.db")
    ck = ROOT / "data" / "checkpoints_scenario.db"
    for s in ("", "-wal", "-shm"):
        Path(str(ck) + s).unlink(missing_ok=True)
    conn = connect(db)
    model = make_model(a.model)
    model_name = getattr(model, "models", ["rules (option A)"])[0]
    clock = {"now": 0}
    svc = DelayService(conn, model, ck, clock=lambda: clock["now"])

    md = [f"# Scenario run: driver delays on the real SetuHaul snapshot\n",
          f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
          f"- Model route: `{a.model or 'from .env'}`; model: `{model_name}`",
          f"- Database: fresh copy of `data/setuhaul_original.db` (`{db.name}`), scenario clock in India time",
          "- Phones are masked before any log, checkpoint or model call. Tool calls and final state are what the "
          "tests assert on; wording may differ between runs.\n"]
    totals = {"tokens_in": 0, "tokens_out": 0, "model_calls": 0, "turns": 0}

    for case in CASES:
        clock["now"] = to_epoch(case["start"])
        sess = start_driver_session(conn, case["phone"])
        md.append(f"## {case['title']}\n")
        md.append(f"Driver signs in with phone `{sess.phone_masked}` -> session for `{sess.driver_id}`.\n")
        for text in case["turns"]:
            r = svc.handle(case["thread"], sess.driver_id, text, msg_key=uuid.uuid4().hex)
            totals["turns"] += 1
            for x in r["log"]:
                if "model" in x:
                    totals["model_calls"] += 1
                    totals["tokens_in"] += x["tokens_in"]
                    totals["tokens_out"] += x["tokens_out"]
            md.append(f"**{hhmm(clock['now'])} Driver:** {text}\n")
            for t in r["tool_calls"]:
                md.append(f"- tool `{t['tool']}` {json.dumps(t['args'])} -> **{t['status']}** (stage {t['stage_after']})")
            for x in r["log"]:
                if "code" in x:
                    md.append(f"- code: `{x['code']}` {json.dumps({k: v for k, v in x.items() if k != 'code'})}")
            md.append(f"\n**Agent** (stage {r['stage']}): {r['reply']}\n")
            clock["now"] += 60

    # final database state
    md.append("## Final database state\n")
    md.append("### Appointments for the two shipments\n")
    md.append("| appointment | shipment | slot | dock | start | status | current | replaces |\n|---|---|---|---|---|---|---|---|")
    for r in conn.execute(
            "SELECT a.appointment_id, a.shipment_id, a.slot_id, d.dock_code, s.slot_start_ts, a.appointment_status, "
            "a.is_current, a.replaced_appointment_id FROM appointments a JOIN appointment_slots s USING(slot_id) "
            "JOIN docks d ON d.dock_id=s.dock_id WHERE a.shipment_id IN ('SHP1013','SHP1015') ORDER BY a.shipment_id, a.booked_at"):
        md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4][11:16]} | {r[5]} | {r[6]} | {r[7] or ''} |")
    md.append("\n### Holds\n")
    md.append("| hold | slot | shipment | state |\n|---|---|---|---|")
    for r in conn.execute("SELECT hold_id, slot_id, shipment_id, state FROM slot_holds"):
        md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    md.append("\n### Hand-offs (the escalation)\n")
    hs = conn.execute("SELECT * FROM handoffs").fetchall()
    for h in hs:
        md.append(f"- **{h['handoff_id']}** reason `{h['reason_code']}`, shipment {h['shipment_id']}, driver `{h['driver_ref']}`, "
                  f"owner {h['owner']}, created {hhmm(h['created_at'])}, deadline {hhmm(h['deadline_at'])}, "
                  f"missing fields: {missing_fields(h) or 'none'}")
        md.append(f"  - summary: `{h['summary_json']}`")
        md.append(f"  - state read: `{h['state_read']}`")
        md.append(f"  - options shown: `{h['options_shown']}`; not done: `{h['not_done']}`")
    dbl = conn.execute("SELECT COUNT(*) FROM (SELECT slot_id FROM appointments WHERE appointment_status IN "
                       "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') GROUP BY slot_id HAVING COUNT(*)>1)").fetchone()[0]
    acts = conn.execute("SELECT action, COUNT(*) FROM audit_events GROUP BY action ORDER BY 2 DESC").fetchall()
    md.append("\n### Checks\n")
    md.append(f"- Escalations: **{len(hs)}** ({', '.join(h['reason_code'] for h in hs)})")
    md.append(f"- Slots with more than one live booking: **{dbl}**")
    md.append(f"- Audit events: {', '.join(f'{x[0]} {x[1]}' for x in acts)}")
    md.append(f"- Turns: {totals['turns']}; model calls: {totals['model_calls']}; tokens in/out: "
              f"{totals['tokens_in']}/{totals['tokens_out']}")
    Path(a.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    svc.close()
    conn.close()
    from src.tracing import flush
    flush()                      # send any LangSmith traces before exiting (no-op when tracing is off)
    ok = len(hs) == 1 and hs[0]["reason_code"] == "NO_FEASIBLE_SLOT" and dbl == 0
    print("\n".join(md))
    print(f"\nsaved {a.out}  ->  {'PASS' if ok else 'CHECK: expected exactly one NO_FEASIBLE_SLOT escalation'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
