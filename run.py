"""One command for everything (Windows has no `make`).

  python run.py test         all tests that need no model (unit, tools, concurrency, guardrails, scenarios, failure)
  python run.py integrity    integrity proof -> docs/integrity_proof.txt
  python run.py scenario     scripted SHP1015 scenario -> docs/scenario_run.md (needs the model key)
  python run.py chat         talk to the agent as a driver (needs the model key)
  python run.py coordinator  coordinator hand-off view (asks for the PIN from .env)
  python run.py demo         test + integrity + scenario
  python run.py failure      failure tests T-19 to T-24 -> docs/failure_tests.txt
  python run.py audit        rerun the data audit
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def sh(*args: str) -> int:
    print(">", " ".join(args), flush=True)
    return subprocess.call(list(args), cwd=ROOT)


def main() -> int:
    task = sys.argv[1] if len(sys.argv) > 1 else "help"
    extra = sys.argv[2:]
    if task == "test":
        return sh(PY, "-m", "pytest", "tests/unit", "tests/tools", "tests/concurrency", "tests/guardrails",
                  "tests/scenarios", "tests/failure", "-q", *extra)
    if task == "failure":
        return sh(PY, "scripts/failure_tests.py", *extra)
    if task == "integrity":
        return sh(PY, "scripts/integrity_proof.py", *extra)
    if task == "scenario":
        return sh(PY, "scripts/scenario_run.py", *extra)
    if task == "chat":
        return sh(PY, "-m", "src.channels.cli", *extra)
    if task == "coordinator":
        return sh(PY, "-m", "src.channels.coordinator", *extra)
    if task == "audit":
        return sh(PY, "run_audit.py", *extra)
    if task == "demo":
        for t in (["test"], ["integrity"], ["scenario"]):
            rc = sh(PY, "run.py", *t)
            if rc:
                return rc
        return 0
    print(__doc__)
    return 0 if task == "help" else 2


if __name__ == "__main__":
    raise SystemExit(main())
