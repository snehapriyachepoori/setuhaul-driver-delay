"""Driver chat in the terminal:  python run.py chat  [--model rules] [--now 2026-08-04T10:00:00+05:30]

Sign in with a driver phone from the snapshot (for example +91-9000010013). Type 'quit' to leave.
Works on data/work_chat.db (a copy; the original is never changed). Use --fresh to start over.
"""
from __future__ import annotations

import argparse
import time
import uuid

from src.agent.graph import DelayService
from src.agent.llm import make_model
from src.auth import start_driver_session
from src.config import ROOT, policy
from src.db import connect, make_work_copy
from src.timeutil import to_epoch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--now", default=policy()["demo"]["now"], help="scenario clock start (India time)")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    db = ROOT / "data" / "work_chat.db"
    if a.fresh or not db.exists():
        make_work_copy(db)
        (ROOT / "data" / "checkpoints_chat.db").unlink(missing_ok=True)
    conn = connect(db)
    start, wall = to_epoch(a.now), time.time()
    svc = DelayService(conn, make_model(a.model), ROOT / "data" / "checkpoints_chat.db",
                       clock=lambda: start + int(time.time() - wall))
    phone = input("Phone number: ").strip()
    sess = start_driver_session(conn, phone)
    if sess is None:
        print("Sorry, that number is not registered.")
        return
    thread = f"CLI-{sess.driver_id}-{uuid.uuid4().hex[:6]}"
    print(f"Signed in as {sess.driver_name} ({sess.phone_masked}). Thread {thread}. Type quit to leave.")
    while True:
        text = input("you> ").strip()
        if text.lower() in ("quit", "exit"):
            break
        if not text:
            continue
        r = svc.handle(thread, sess.driver_id, text)
        for t in r["tool_calls"]:
            print(f"   [tool {t['tool']} -> {t['status']}]")
        print(f"agent> {r['reply']}   [stage {r['stage']}]")
    svc.close()
    from src.tracing import flush
    flush()


if __name__ == "__main__":
    main()
