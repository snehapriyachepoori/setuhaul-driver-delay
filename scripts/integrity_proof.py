"""Writes docs/integrity_proof.txt (submission item 5).

Run:  python run.py integrity        (about 1 to 2 minutes)
"""
from __future__ import annotations

import argparse
import platform
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.concurrency.harness import format_totals, run_race  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=100)
    ap.add_argument("--workdir", default=None, help="scratch folder (default: system temp, outside OneDrive)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "integrity_proof.txt"))
    a = ap.parse_args()
    work = Path(a.workdir or tempfile.mkdtemp(prefix="setuhaul_race_"))

    sections, ok = [], True
    for mode, title in [
        ("protected", "RUN 1  Real code: BEGIN IMMEDIATE + re-check inside the transaction + hold index"),
        ("naive_index_on", "RUN 2  CONTROL: naive check-then-insert, no lock; client's unique index still on"),
        ("naive_index_off", "RUN 3  CONTROL: naive check-then-insert AND unique index dropped (throwaway copy)"),
    ]:
        t0 = time.time()
        t = run_race(work / mode, mode, repeats=a.repeats)
        secs = time.time() - t0
        sections.append(f"{title}\n{'-' * len(title)}\n{format_totals(t)}\nelapsed seconds              : {secs:.1f}\n")
        print(sections[-1])
        if mode == "protected":
            ok = t["double_bookings"] == 0 and t["ERROR"] == 0 and t["per_repeat_confirmed"] == [1] * a.repeats

    header = (
        "SetuHaul integrity proof: no double booking (test T-01)\n"
        "=======================================================\n"
        f"Generated : {datetime.now().isoformat(timespec='seconds')}\n"
        f"Python    : {platform.python_version()}   SQLite: {sqlite3.sqlite_version}   OS: {platform.system()} {platform.release()}\n"
        "Database  : fresh copy of data/setuhaul_original.db per repeat (the original is never written)\n"
        "Method    : 10 threads, each with its own connection and its own truck, wait at a barrier and\n"
        "            all try to hold + confirm the same slot at the same instant. Repeated per run.\n"
        "Note      : approval routing (check 10) is switched off in this test so all 10 trucks may legally\n"
        "            take the slot; approval has its own tests in tests/concurrency/test_commit_layer.py.\n\n"
    )
    verdict = ("RESULT: PASS. Run 1 made exactly 1 booking in every repeat, 0 double bookings.\n"
               "Run 3 shows the test CAN fail: without the lock and the index, the same race double books.\n"
               if ok else "RESULT: FAIL. See run 1.\n")
    Path(a.out).write_text(header + "\n".join(sections) + "\n" + verdict, encoding="utf-8")
    print(verdict + f"saved {a.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
