# Measures (E1)

Source: last `python run.py scenario` run (`data/work_scenario.db`), the integrity proof, and the competing-trucks replay. Real snapshot data, simulated clock.

| # | Measure | Result | Note |
|---|---|---|---|
| 1 | Time from first message to usable outcome | SCN-1013: CONFIRMED in 4 driver message(s); SCN-1015: ESCALATED in 1 driver message(s) | Counted in driver messages (the scenario clock is simulated, so seconds are not meaningful). |
| 2 | Share resolved without manual takeover | 1/2 | The scenario is designed with one escalation (SHP1015), so 1 of 2 is the expected value. |
| 3 | Conflicting or duplicate allocations | 0 in the scenario; integrity test 1000 requests / 100 bookings / 0 double bookings | Target 0. |
| 4 | Options later found infeasible | 0 of 1 confirmations | Every confirm re-runs all checks; the stale-option test (T-03) forces one and it is refused with a reason. |
| 5 | No-slot escalations handled correctly | 1/1 complete hand-off records | Every field filled, owner named, deadline set; the driver was told nothing was changed. |
| 6 | Average driver waiting after rescheduling | SHP1013: 80 min between declared arrival and new slot start | PLANNED wait only (includes the safety margin). Real waiting needs gate-in and dock-in times after rescheduling, which the snapshot does not have. |
| 7 | Warehouse slot utilisation | 10/60 open Jaipur slots booked, 10:00 to 22:00 (16%) | Snapshot-level figure; it moves only slightly in a two-driver scenario. |
| 8 | Priority-policy violations | 0 across 2 replays | From docs/competing_trucks.md (five competing trucks, simultaneous and queued). |
| 9 | Driver clarification turns | 1.0 questions per resolved case | Target under 3. |
