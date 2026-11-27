"""Coordinator hand-off view (terminal):  python run.py coordinator [--db data/work_scenario.db]

Asks for COORDINATOR_PIN from .env (demo-level, not production security). Lists open hand-offs,
newest deadline first, and lets the coordinator acknowledge one.
"""
from __future__ import annotations

import argparse
import getpass
import json
import time

from dotenv import load_dotenv

from src.auth import coordinator_pin_ok
from src.capacity.handoff import acknowledge, missing_fields, open_handoffs
from src.config import ROOT
from src.db import connect
from src.timeutil import hhmm


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "work_scenario.db"))
    a = ap.parse_args()
    if not coordinator_pin_ok(getpass.getpass("Coordinator PIN: ")):
        print("Wrong PIN (or COORDINATOR_PIN not set in .env).")
        return
    conn = connect(a.db)
    rows = open_handoffs(conn)
    if not rows:
        print("No open hand-offs.")
        return
    for h in rows:
        print(f"\n{h['handoff_id']}  {h['reason_code']}  shipment {h['shipment_id']}  driver {h['driver_ref']}")
        print(f"  owner {h['owner']}  deadline {hhmm(h['deadline_at'])}  missing fields: {missing_fields(h) or 'none'}")
        print(f"  summary   : {json.loads(h['summary_json'])}")
        print(f"  state read: {json.loads(h['state_read'])}")
        print(f"  not done  : {json.loads(h['not_done'])}")
    hid = input("\nAcknowledge which hand-off id (blank to skip)? ").strip()
    if hid:
        who = input("Your name: ").strip() or "coordinator"
        print("Acknowledged." if acknowledge(conn, hid, who, int(time.time())) else "Not found or already acknowledged.")


if __name__ == "__main__":
    main()
