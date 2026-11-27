"""Race harness for the integrity proof (T-01).

10 threads, each with its OWN database connection and its OWN truck, wait at a barrier and then
all try to book the same slot at the same instant. Repeated on a fresh database copy each time.

Three modes:
  protected        : our real code (BEGIN IMMEDIATE + re-check + hold index). Expect 1 winner.
  naive_index_on   : CONTROL. Check-then-insert with no lock, but the client's unique index
                     on appointments is still there. Expect the DATABASE to stop the extras.
  naive_index_off  : CONTROL. Same naive code AND the unique index dropped (only on a throwaway
                     copy). Expect double bookings: proves the test can fail.
"""
from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from src.capacity.commit import confirm_booking, hold_slot
from src.capacity.feasibility import check_slot
from src.config import policy
from src.db import connect, make_work_copy
from src.timeutil import to_epoch, to_ist

RACE_SLOT = "SLOT-JAI-048"   # Jaipur D4 13:00-14:00 (standard, 25,000 kg), free in the snapshot
N_THREADS = 10
ACTIVE = "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')"


@contextmanager
def approval_routing_off():
    """This is a contention test, not an approval test (approval has its own tests).
    Raise the approval threshold so all 10 trucks can legally take the slot."""
    p = policy()["approval"]
    old = p["max_shift_min"]
    p["max_shift_min"] = 10**6
    try:
        yield
    finally:
        p["max_shift_min"] = old


def contenders(db_path: Path, now: int, slot: str = RACE_SLOT, n: int = N_THREADS) -> list[tuple[str, str]]:
    """Pick n different trucks for which the slot is genuinely feasible."""
    c = connect(db_path)
    try:
        out = []
        fac = c.execute("SELECT facility_id FROM appointment_slots WHERE slot_id=?", (slot,)).fetchone()[0]
        for sid, drv in c.execute("SELECT shipment_id, driver_id FROM shipments WHERE destination_facility_id=? "
                                  "ORDER BY shipment_id", (fac,)).fetchall():
            if check_slot(c, sid, slot, now=now, driver_id=drv, thread_id=f"T-{sid}").feasible:
                out.append((sid, drv))
        if len(out) < n:
            raise RuntimeError(f"only {len(out)} trucks can take {slot}; need {n}")
        return out[:n]
    finally:
        c.close()


def _protected(db_path, sid, drv, slot, now, barrier, results, i):
    c = connect(db_path)
    try:
        thread_id = f"T-{sid}"
        barrier.wait()
        h = hold_slot(c, shipment_id=sid, slot_id=slot, thread_id=thread_id, driver_id=drv,
                      idempotency_key=f"{thread_id}:hold", now=now)
        if h["status"] != "ACTIVE":
            results[i] = "REFUSED"
            return
        r = confirm_booking(c, hold_id=h["hold_id"], thread_id=thread_id, driver_id=drv,
                            idempotency_key=f"{thread_id}:confirm", now=now)
        results[i] = r["status"]
    except Exception as e:  # any crash is recorded, never hidden
        results[i] = f"ERROR:{type(e).__name__}:{e}"
    finally:
        c.close()


def _naive(db_path, sid, drv, slot, now, barrier, results, i):
    """The UNSAFE pattern: read, think, then write, with no lock held in between."""
    c = connect(db_path)
    iso = to_ist(now)
    try:
        barrier.wait()
        taken = c.execute(f"SELECT 1 FROM appointments WHERE slot_id=? AND appointment_status IN {ACTIVE}",
                          (slot,)).fetchone()
        if taken:
            results[i] = "REFUSED"
            return
        time.sleep(0.005)   # the gap where another driver gets in
        try:
            c.execute(f"UPDATE appointments SET appointment_status='CANCELLED', is_current=0, updated_at=? "
                      f"WHERE shipment_id=? AND is_current=1 AND appointment_status IN {ACTIVE}", (iso, sid))
            c.execute("INSERT INTO appointments(appointment_id, shipment_id, slot_id, appointment_status, "
                      "booking_source, is_current, booked_at, updated_at) "
                      "VALUES (?,?,?,'CONFIRMED','DRIVER_CHAT',1,?,?)", (f"NAIVE-{sid}", sid, slot, iso, iso))
            results[i] = "CONFIRMED"
        except sqlite3.IntegrityError:
            results[i] = "DB_BLOCKED"
    except Exception as e:
        results[i] = f"ERROR:{type(e).__name__}:{e}"
    finally:
        c.close()


def run_race(workdir: Path, mode: str = "protected", repeats: int = 100, now: int | None = None,
             slot: str = RACE_SLOT) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    now = now if now is not None else to_epoch(policy()["demo"]["now"])
    template = make_work_copy(workdir / "template.db")
    worker = {"protected": _protected, "naive_index_on": _naive, "naive_index_off": _naive}[mode]
    totals = {"mode": mode, "repeats": repeats, "threads": N_THREADS, "slot": slot,
              "requests": 0, "CONFIRMED": 0, "REFUSED": 0, "DB_BLOCKED": 0, "ERROR": 0,
              "repeats_with_double_booking": 0, "double_bookings": 0, "per_repeat_confirmed": []}
    with approval_routing_off():
        trucks = contenders(template, now, slot)
        totals["trucks"] = [s for s, _ in trucks]
        for k in range(repeats):
            db = workdir / f"race_{mode}_{k}.db"
            shutil.copyfile(template, db)
            if mode == "naive_index_off":
                c = connect(db)
                c.execute("DROP INDEX ux_active_appointment_per_slot")
                c.close()
            barrier = threading.Barrier(N_THREADS)
            results: list[str | None] = [None] * N_THREADS
            threads = [threading.Thread(target=worker, args=(db, s, d, slot, now, barrier, results, i))
                       for i, (s, d) in enumerate(trucks)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            c = connect(db)
            on_slot = c.execute(f"SELECT COUNT(*) FROM appointments WHERE slot_id=? "
                                f"AND appointment_status IN {ACTIVE}", (slot,)).fetchone()[0]
            c.close()
            for r in results:
                key = r if r in ("CONFIRMED", "REFUSED", "DB_BLOCKED") else "ERROR"
                totals[key] += 1
                if key == "ERROR":
                    totals.setdefault("errors", []).append(r)
            totals["requests"] += N_THREADS
            totals["per_repeat_confirmed"].append(on_slot)
            if on_slot > 1:
                totals["repeats_with_double_booking"] += 1
                totals["double_bookings"] += on_slot - 1
            for suffix in ("", "-wal", "-shm"):
                Path(str(db) + suffix).unlink(missing_ok=True)
    return totals


def format_totals(t: dict) -> str:
    lines = [
        f"mode                         : {t['mode']}",
        f"slot                         : {t['slot']}",
        f"threads per repeat           : {t['threads']} (one truck each: {', '.join(t['trucks'])})",
        f"repeats                      : {t['repeats']}",
        f"requests sent                : {t['requests']}",
        f"bookings made (CONFIRMED)    : {t['CONFIRMED']}",
        f"refused by code              : {t['REFUSED']}",
        f"blocked by database index    : {t['DB_BLOCKED']}",
        f"errors                       : {t['ERROR']}",
        f"repeats with a double booking: {t['repeats_with_double_booking']}",
        f"double bookings (extra rows) : {t['double_bookings']}",
        f"live bookings on slot, per repeat (min/max): "
        f"{min(t['per_repeat_confirmed'])}/{max(t['per_repeat_confirmed'])}",
    ]
    if t.get("errors"):
        lines.append("first errors: " + "; ".join(t["errors"][:3]))
    return "\n".join(lines)
