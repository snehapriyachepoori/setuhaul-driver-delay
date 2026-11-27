"""Run the failure tests T-19 to T-24 and save the output to docs/failure_tests.txt.

    python run.py failure            (or: python scripts/failure_tests.py)
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "failure_tests.txt"

HEADER = """SetuHaul failure tests T-19 to T-24
===================================
What this is: tests that break things on purpose and check the system fails SAFELY.
Each test runs the full conversation (graph, tools, real database copy) with the free rules model,
so no API key is needed. Database: the client snapshot (data/), copied fresh for every test.

| ID   | What we break                                        | Pass rule                                              |
|------|------------------------------------------------------|--------------------------------------------------------|
| T-19 | Same message delivered twice (THR009 repeats THR001) | One action; the repeat gets the stored first reply      |
| T-20 | Coordinator blocks a slot after it was shown          | Refused with a reason, fresh options, nothing booked    |
| T-21 | Power cut after the old booking is cancelled          | Everything rolled back; old booking still live          |
| T-22 | The database refuses the COMMIT                       | Driver is never told "confirmed"                        |
| T-23 | Driver says yes six minutes after the hold            | Refused (hold expires after 5 min); control at 4 min OK |
| T-24 | Unknown phone, suspended driver, other driver's load  | No session or MISMATCH; no other driver's data shown    |

Known gaps these tests found (also in README "What does not work yet"):
- T-19: the real THR009 repeat came on a NEW thread with a NEW channel id, so the message key cannot
  catch it. Safe today because a repeat only shows options; nothing is booked unless the driver picks
  and says yes again. It is not flagged as a repeat.
- T-22: after a failed commit the reply says "A coordinator can help if needed", but no hand-off row is
  created and the conversation stays at stage CONFIRM. Nothing is booked, but nobody is alerted.

Run: {when}
Command: python -m pytest tests/failure -v
-----------------------------------------------------------------------------------------------
"""


def main() -> int:
    cmd = [sys.executable, "-m", "pytest", "tests/failure", "-v", "-p", "no:cacheprovider", *sys.argv[1:]]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    body = p.stdout + (p.stderr or "")
    # Keep the file stable and private: drop the machine-specific header lines pytest prints.
    lines = [ln for ln in body.splitlines() if not ln.startswith(("rootdir:", "platform ", "cachedir:", "configfile:"))]
    when = dt.datetime.now().strftime("%d %b %Y %H:%M")
    OUT.write_text(HEADER.format(when=when) + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-3:]))
    print(f"saved -> {OUT.relative_to(ROOT)}")
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
