"""E3 / T-11: competing trucks and the ordering policy -> docs/competing_trucks.md

Five trucks from the brief (SHP1006, SHP1009, SHP1012, SHP1013, SHP1014) ask for slots at 10:00.
Two replays:
  A  XS tier (today): all five pick their best option at the same instant (threads). P-2: first hold wins.
  B  Pilot tier: requests queued and served in P-5 order (priority, latest finish, arrival).
Every allocation is re-checked against the written policy afterwards (0 violations expected).
"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capacity.commit import confirm_booking, hold_slot  # noqa: E402
from src.capacity.eta import resolve_eta  # noqa: E402
from src.capacity.feasibility import find_feasible_slots  # noqa: E402
from src.capacity.ranking import QueuedRequest, order_requests, rank_options  # noqa: E402
from src.db import connect, make_work_copy  # noqa: E402
from src.timeutil import hhmm, to_epoch  # noqa: E402

TRUCKS = ["SHP1006", "SHP1009", "SHP1012", "SHP1013", "SHP1014"]
NOW = to_epoch("2026-08-04T10:00:00+05:30")


def info(conn, sid):
    r = conn.execute("SELECT driver_id, priority_code, load_weight_kg FROM shipments WHERE shipment_id=?", (sid,)).fetchone()
    e = resolve_eta(conn, sid)
    return {"sid": sid, "drv": r[0], "prio": r[1], "kg": r[2], "eta": e}


def book_best(db, sid, drv, now, results, barrier=None):
    c = connect(db)
    try:
        feas, _ = find_feasible_slots(c, sid, now=now, driver_id=drv)
        opts = rank_options(feas, resolve_eta(c, sid), limit=3)
        first = opts[0]
        if barrier:
            barrier.wait()
        tried = []
        for round_ in range(2):             # round 2 = fresh options after every shown one was taken
            if round_:
                feas, _ = find_feasible_slots(c, sid, now=now, driver_id=drv, thread_id=f"T-{sid}")
                opts = rank_options(feas, resolve_eta(c, sid), limit=3)
            for o in opts:                  # wanted the first; on refusal try the next shown option
                h = hold_slot(c, shipment_id=sid, slot_id=o.slot_id, thread_id=f"T-{sid}", driver_id=drv,
                              idempotency_key=f"T-{sid}:{round_}:{o.slot_id}", now=now)
                tried.append((o, h["status"], h.get("reason_codes")))
                if h["status"] == "ACTIVE":
                    r = confirm_booking(c, hold_id=h["hold_id"], thread_id=f"T-{sid}", driver_id=drv,
                                        idempotency_key=f"T-{sid}:c:{o.slot_id}", now=now)
                    results[sid] = {"wanted": first, "got": o, "status": r["status"], "tried": tried,
                                    "fresh": bool(round_)}
                    return
        results[sid] = {"wanted": first, "got": None, "status": "NO_OPTION_LEFT", "tried": tried}
    finally:
        c.close()


def label(o):
    return f"{o.dock_code} {hhmm(o.start)}" if o else "-"


def violations(conn) -> list[str]:
    """P-1: original confirmed bookings of OTHER shipments untouched. P-2/I-1: one live booking per slot."""
    out = []
    for slot, n in conn.execute("SELECT slot_id, COUNT(*) FROM appointments WHERE appointment_status IN "
                                "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') GROUP BY slot_id HAVING COUNT(*)>1"):
        out.append(f"double booking on {slot}")
    for (aid,) in conn.execute("SELECT appointment_id FROM appointments WHERE cancellation_reason='REPLACED_BY_DRIVER_REBOOKING' "
                               "AND shipment_id NOT IN (%s)" % ",".join("?" * len(TRUCKS)), TRUCKS):
        out.append(f"P-1 broken: {aid} cancelled for someone else")
    return out


def table(conn, results, order, info_by):
    rows = ["| truck | priority | weight kg | ETA (conf, +margin) | wanted | got | status | rule that decided |",
            "|---|---|---|---|---|---|---|---|"]
    for sid in order:
        r, i = results[sid], info_by[sid]
        e = i["eta"]
        if r["got"] and r["got"].slot_id == r["wanted"].slot_id:
            rule = "first to hold (P-2)" + ("; needs approval (check 10)" if r["status"] == "NEEDS_APPROVAL" else "")
        elif r["got"]:
            reason = r["tried"][0][2]
            rule = (f"wanted slot already held/booked ({', '.join(reason or [])}): P-1/P-2, "
                    + ("all 3 shown options went, fresh options fetched" if r.get("fresh") else "next shown option"))
            if r["status"] == "NEEDS_APPROVAL":
                rule += "; needs approval (check 10)"
        else:
            rule = "no option left: escalate (P-4)"
        rows.append(f"| {sid} | {i['prio']} | {i['kg']:,} | {hhmm(e.eta_epoch)} ({e.confidence}, +{e.margin_min}) | "
                    f"{label(r['wanted'])} | {label(r['got'])} | {r['status']} | {rule} |")
    return rows


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="setuhaul_compete_"))
    md = ["# Competing trucks and the ordering policy (E3, test T-11)\n",
          "Five trucks from the brief ask for a new slot at 10:00 on the real snapshot. Only **D2 12:00** and "
          "**D4 12:00** are free at noon for standard loads (D1 12:00 is booked by SHP1017, D3 is broken until 13:00).\n"]

    # Replay A: simultaneous
    db = make_work_copy(work / "a.db")
    c = connect(db)
    info_by = {s: info(c, s) for s in TRUCKS}
    c.close()
    results: dict = {}
    barrier = threading.Barrier(len(TRUCKS))
    ts = [threading.Thread(target=book_best, args=(db, s, info_by[s]["drv"], NOW, results, barrier)) for s in TRUCKS]
    [t.start() for t in ts]
    [t.join() for t in ts]
    c = connect(db)
    md.append("## A. Today's tier (XS): everyone picks at the same instant\n")
    md.append("Rule P-2 decides: the first hold wins, whatever the priority. The losers are told the truth and offered the next option.\n")
    md += table(c, results, TRUCKS, info_by)
    va = violations(c)
    md.append(f"\nPolicy violations: **{len(va)}** {va or ''}\n")
    c.close()

    # Replay B: queued in P-5 order
    db = make_work_copy(work / "b.db")
    reqs = [QueuedRequest(s, info_by[s]["prio"], None, NOW + k) for k, s in enumerate(TRUCKS)]
    order = [r.request_id for r in order_requests(reqs, NOW + 10)]
    results = {}
    for s in order:
        book_best(db, s, info_by[s]["drv"], NOW, results)
    c = connect(db)
    md.append("## B. Pilot tier: requests queued and served in P-5 order\n")
    md.append(f"Served in this order: {', '.join(order)} (priority first, then earliest latest-finish, then arrival; "
              "a request waiting 10 minutes moves up one class).\n")
    md += table(c, results, order, info_by)
    vb = violations(c)
    md.append(f"\nPolicy violations: **{len(vb)}** {vb or ''}\n")
    md.append("## What each losing driver is told\n")
    md.append('- Slot taken first: "Sorry, that slot was just taken before I could secure it. Your booking is unchanged. '
              'Here are the next options." (P-2)')
    md.append('- Option more than 3 hours after the plan: shown, held, then "A coordinator must approve this" (check 10).')
    md.append('- A slot hidden by P-3 (scarce dock type): "That slot is kept for time-critical loads." Not triggered here: '
              'standard docks have more than 3 free slots in the 4-hour window.')
    md.append("\n## Honest note\nAt XS tier the system does not reorder simultaneous requests by priority; it is first hold wins "
              "(P-2), with P-3 protecting scarce dock types. Priority ordering (P-5) needs the per-facility queue planned "
              "for the pilot. Whether that is the right policy is the operations head's decision (open question).")
    (ROOT / "docs" / "competing_trucks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0 if not va and not vb else 1


if __name__ == "__main__":
    raise SystemExit(main())
