# Dummy SetuHaul database (synthetic)

**Why this exists:** the real SQLite snapshot was not supplied, so this is a stand-in with the
same table names and row counts as the brief (18 tables, 275 rows, 2 facilities, 9 docks,
21 shipments, 106 slots, 20 appointments). It follows the Jaipur dock chart on page 6 of the brief.
Column names beyond the brief's ER diagram are invented. All names and phone numbers are fictional.

**It is not client data.** Results from it prove the queries work. They are not findings about SetuHaul.

## Run
    python3 build_dummy_db.py          # creates dummy_setuhaul.db
    python3 run_audit.py               # runs ../01_audit_queries.sql, prints every result
    python3 run_audit.py REAL.db       # same queries on the real file when you get it

## Problems planted on purpose (so each query has something to find)
| Query | Planted problem |
|---|---|
| Q-02 | One ETA stored in UTC ("Z"), SHP1012 |
| Q-06, Q-07 | APT1002 active on D2 while the dock is in breakdown |
| Q-11 | SHP1013, SHP1014, SHP1015: latest ETA is after the booked slot ends |
| Q-12 | Several ETAs per shipment: SHP1013 has three, all different |
| Q-13 | SHP1004 booked on D2 but checked in at D1 |
| Q-14 | THR009: same "Take the 11 o'clock slot" message twice |
| Q-15 | Drivers with two active shipments; THR010 has no shipment |
| Q-16 | Exceptions missing a thread or an ETA |
| Q-17 | RULE005 says D5 closes at 19:00 while the facility is open until 22:00 |
| Q-18 | No "held" state exists in any status list |
| Q-19 | SLT0521 shown available although a maintenance event covers it |
| Q-20 | A phone number typed into a chat message (MSG014) |

Checks that correctly came back clean on the dummy data: Q-03, Q-04, Q-05, Q-08, Q-09, Q-10, Q-13a/b.

`audit_results_DUMMY.txt` is the saved output of one run.
