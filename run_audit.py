"""Run the data audit: every query in docs/01_audit_queries.sql against the client database.

Usage:  python run_audit.py [db_path] [sql_path] [out_path]
Default: data/setuhaul_original.db -> docs/audit_results_REAL.txt
The database is opened READ-ONLY, so the audit can never change client data.
Standard library only.
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
db = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "data" / "setuhaul_original.db"
sql = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "docs" / "01_audit_queries.sql"
out = Path(sys.argv[3]) if len(sys.argv) > 3 else HERE / "docs" / "audit_results_REAL.txt"

con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)  # read-only
lines = [f"Audit of {db.name} using {sql.name}", ""]
buf, label = "", ""
for line in sql.read_text(encoding="utf-8").splitlines(keepends=True):
    s = line.strip()
    if s.startswith("-- ----------"):          # a new query title
        label = s.strip("- ").strip()
    buf += line
    if not sqlite3.complete_statement(buf):
        continue
    stmt, buf = buf.strip(), ""
    code = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
    if not code:
        continue
    lines.append(f"=== {label} ===")
    try:
        cur = con.execute(stmt)
        rows = cur.fetchall()
        if cur.description:
            lines.append(" | ".join(d[0] for d in cur.description))
            lines.append(f"({len(rows)} rows)")
            lines += [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    except sqlite3.Error as e:
        lines.append(f"ERROR: {e}")
    lines.append("")

out.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
print(f"\nSaved to {out}")
