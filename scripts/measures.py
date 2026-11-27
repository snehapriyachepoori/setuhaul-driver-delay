"""E1: the nine measures the brief judges -> docs/measures.md

Reads the last scenario run (data/work_scenario.db, made by `python run.py scenario`),
docs/integrity_proof.txt and docs/competing_trucks.md. Says plainly when a measure cannot be measured.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capacity.handoff import missing_fields  # noqa: E402
from src.db import connect  # noqa: E402
from src.timeutil import to_epoch  # noqa: E402

ACTIVE = "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')"


def main() -> int:
    conn = connect(ROOT / "data" / "work_scenario.db")
    turns = conn.execute("SELECT thread_id, ts, detail_json FROM audit_events WHERE action='TURN' ORDER BY event_id").fetchall()
    threads: dict[str, list] = {}
    for t in turns:
        threads.setdefault(t[0], []).append((t[1], json.loads(t[2])))

    rows = []
    # 1 time to usable outcome
    per = []
    resolved, clar_q = 0, []
    for th, ts in threads.items():
        n_to_outcome, outcome = None, None
        questions = 0
        for i, (when, d) in enumerate(ts, start=1):
            statuses = [x.get("status") for x in d["log"] if "tool" in x]
            codes = [x.get("code") for x in d["log"] if "code" in x]
            if "CONFIRMED" in statuses or "NO_FEASIBLE_SLOT" in statuses or "OPTIONS" in statuses and outcome is None \
                    or "SAFETY_HANDOFF" in codes:
                if outcome is None or "CONFIRMED" in statuses:
                    n_to_outcome = i
                    outcome = ("CONFIRMED" if "CONFIRMED" in statuses else
                               "ESCALATED" if "NO_FEASIBLE_SLOT" in statuses or "SAFETY_HANDOFF" in codes else "OPTIONS")
            if outcome is None and not statuses or (statuses and all(s in ("UNIQUE", "AMBIGUOUS") for s in statuses)):
                questions += 1
        per.append(f"{th}: {outcome} in {n_to_outcome} driver message(s)")
        if outcome in ("CONFIRMED", "OPTIONS"):
            resolved += 1
            clar_q.append(questions)
    rows.append(("Time from first message to usable outcome", "; ".join(per),
                 "Counted in driver messages (the scenario clock is simulated, so seconds are not meaningful)."))
    rows.append(("Share resolved without manual takeover", f"{resolved}/{len(threads)}",
                 "The scenario is designed with one escalation (SHP1015), so 1 of 2 is the expected value."))
    # 3 conflicts
    dbl = conn.execute(f"SELECT COUNT(*) FROM (SELECT slot_id FROM appointments WHERE appointment_status IN {ACTIVE} "
                       "GROUP BY slot_id HAVING COUNT(*)>1)").fetchone()[0]
    proof = (ROOT / "docs" / "integrity_proof.txt").read_text(encoding="utf-8") if (ROOT / "docs" / "integrity_proof.txt").exists() else ""
    m = re.search(r"RUN 1.*?requests sent\s*:\s*(\d+).*?bookings made \(CONFIRMED\)\s*:\s*(\d+).*?double bookings \(extra rows\)\s*:\s*(\d+)", proof, re.S)
    rows.append(("Conflicting or duplicate allocations", f"{dbl} in the scenario; integrity test "
                 + (f"{m.group(1)} requests / {m.group(2)} bookings / {m.group(3)} double bookings" if m else "not run"), "Target 0."))
    # 4 infeasible at confirm
    conf = conn.execute("SELECT COUNT(*) FROM audit_events WHERE action IN ('CONFIRMED','CONFIRM_REFUSED','NEEDS_APPROVAL')").fetchone()[0]
    bad = conn.execute("SELECT COUNT(*) FROM audit_events WHERE action='CONFIRM_REFUSED'").fetchone()[0]
    rows.append(("Options later found infeasible", f"{bad} of {conf} confirmations",
                 "Every confirm re-runs all checks; the stale-option test (T-03) forces one and it is refused with a reason."))
    # 5 no-slot escalations
    ns = conn.execute("SELECT * FROM handoffs WHERE reason_code='NO_FEASIBLE_SLOT'").fetchall()
    complete = sum(1 for h in ns if not missing_fields(h))
    rows.append(("No-slot escalations handled correctly", f"{complete}/{len(ns)} complete hand-off records",
                 "Every field filled, owner named, deadline set; the driver was told nothing was changed."))
    # 6 waiting
    waits = []
    for r in conn.execute("SELECT a.shipment_id, t.start_epoch FROM appointments a JOIN slot_times t USING(slot_id) "
                          "WHERE a.booking_source='DRIVER_CHAT' AND a.appointment_id LIKE 'APT-%'"):
        d = conn.execute("SELECT detail_json FROM audit_events WHERE action='ETA_DECLARED' AND shipment_id=? "
                         "ORDER BY event_id DESC", (r[0],)).fetchone()
        if d:
            eta = json.loads(d[0])["eta"]
            eta_e = to_epoch(f"2026-08-04T{eta}:00+05:30")
            waits.append(f"{r[0]}: {(r[1] - eta_e) // 60} min between declared arrival and new slot start")
    rows.append(("Average driver waiting after rescheduling", "; ".join(waits) or "no rebooking in run",
                 "PLANNED wait only (includes the safety margin). Real waiting needs gate-in and dock-in times after "
                 "rescheduling, which the snapshot does not have."))
    # 7 utilisation
    lo, hi = to_epoch("2026-08-04T10:00:00+05:30"), to_epoch("2026-08-04T22:00:00+05:30")
    open_ = conn.execute("SELECT COUNT(*) FROM appointment_slots s JOIN slot_times t USING(slot_id) WHERE s.facility_id='FAC-JAI-01' "
                         "AND s.slot_status='OPEN' AND t.start_epoch>=? AND t.start_epoch<?", (lo, hi)).fetchone()[0]
    used = conn.execute(f"SELECT COUNT(*) FROM appointments a JOIN appointment_slots s USING(slot_id) JOIN slot_times t USING(slot_id) "
                        f"WHERE s.facility_id='FAC-JAI-01' AND a.appointment_status IN {ACTIVE} AND t.start_epoch>=? AND t.start_epoch<?",
                        (lo, hi)).fetchone()[0]
    rows.append(("Warehouse slot utilisation", f"{used}/{open_} open Jaipur slots booked, 10:00 to 22:00 ({100 * used // max(open_, 1)}%)",
                 "Snapshot-level figure; it moves only slightly in a two-driver scenario."))
    # 8 policy
    ct = (ROOT / "docs" / "competing_trucks.md")
    viol = re.findall(r"Policy violations: \*\*(\d+)\*\*", ct.read_text(encoding="utf-8")) if ct.exists() else []
    rows.append(("Priority-policy violations", f"{sum(map(int, viol))} across {len(viol)} replays" if viol else "replay not run",
                 "From docs/competing_trucks.md (five competing trucks, simultaneous and queued)."))
    rows.append(("Driver clarification turns", f"{sum(clar_q) / max(len(clar_q), 1):.1f} questions per resolved case",
                 "Target under 3."))

    md = ["# Measures (E1)\n", "Source: last `python run.py scenario` run (`data/work_scenario.db`), the integrity proof, "
          "and the competing-trucks replay. Real snapshot data, simulated clock.\n",
          "| # | Measure | Result | Note |", "|---|---|---|---|"]
    md += [f"| {i} | {a} | {b} | {c} |" for i, (a, b, c) in enumerate(rows, start=1)]
    (ROOT / "docs" / "measures.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
