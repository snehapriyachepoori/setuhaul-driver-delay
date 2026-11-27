# Submission item 1: Problem Definition Sheet and data audit

> **Data:** the real SetuHaul snapshot `setuhaul_freight_operations.db` (4 Aug 2026, Asia/Kolkata, +05:30). Every issue below is proved by a query in `01_audit_queries.sql`; the full output is in `audit_results_REAL.txt`. Rerun with `python run_audit.py` (opens the database read-only). An earlier draft used a synthetic stand-in; it is kept in `archive_standin/` and is not used here.

## Client and problem
- **Client:** SetuHaul Logistics, a third-party logistics company. Full-truckload freight in North and West India: 280 to 360 loads a day, 6 facilities, 32 docks (brief-stated). The snapshot covers 2 facilities (Jaipur, Gurugram), 9 docks, 21 shipments.
- **Problem (one sentence):** How might SetuHaul let drivers report delays and consider new appointments by chat, while many requests compete for a few dock slots, without false or conflicting promises?
- **Surface vs underlying:** one driver needs a clear, true answer. Underneath, 20 to 35 messages in 30 minutes chase the same few slots, so two drivers can both be told yes to one slot, and promises already in the system can be broken without anyone noticing.
- **Design target:** 35 messages in 30 minutes across 6 facilities. Tested on the snapshot.

## Facts, assumptions, unknowns
- **Brief-stated or proved:** 0 live GPS feeds; 5 coordinators a shift; the database enforces one active appointment per slot and one current appointment per shipment (Q-00, control Q-03 holds); all times use +05:30 (Q-02).
- **Assumptions:** drivers write in mixed Hindi and English; gate check-in is the only reliable arrival proof; duplicate chat messages happen (proved once, Q-12).
- **Unknowns (owner):** which system wins in a conflict (operations head); how long a pending warehouse confirmation may last (warehouse planner); detention cost (finance); e-way bill and driver rest data (data owner); who covers the Jaipur night shift (operations head, Q-17/Q-18).

## Rules that must never break (invariants)
1. Never two active bookings on one slot.
2. Never tell a driver a slot is theirs before it is committed.
3. Re-check a slot at the moment of commit; never book a stale option.
4. A safety report always goes to a person.
5. Confirm the right shipment, for the right driver, before acting.
6. A repeated message never causes a second action.
7. No feasible slot means escalate, never invent an answer.
8. The model never decides capacity, ranking or commit.

## Data audit (query file: `01_audit_queries.sql`, output: `audit_results_REAL.txt`)
| ID | Issue | Query | Real result | Why it matters |
|---|---|---|---|---|
| I-01 | Active bookings on a dock that is broken or slowed | Q-04 | 3: APT1005 (D3 breakdown 09:15 to 13:00), APT1004 and APT1002 (D2 capacity reduction to 09:20) | The promise cannot be kept; SHP1005 is already waiting in the yard |
| I-02 | The availability view ignores dock events | Q-05 | 3 slots (SLOT-JAI-015, 016, 030) show OCCUPIED, not unusable | Any tool built on the view would trust a broken dock |
| I-03 | Load heavier than the dock's weight limit | Q-06 | 2: SHP1014 21,000 kg on D1 (max 20,000); SHP1005 20,500 kg on D3 (max 20,000) | Dock type alone is not enough; weight must be checked |
| I-04 | Booking ends before the truck can arrive | Q-08 | 2: APT1006 (slot ends 11:00, ETA 11:20); APT1015A (slot ends 18:00, ETA 18:30) | Promises already broken, still marked CONFIRMED |
| I-05 | Unload longer than the slot | Q-09 | 4: SHP1002 (70 min), SHP1005, SHP1009, SHP1014 (75 min) in 60-minute slots | The next truck on that dock starts late |
| I-06 | "Latest ETA" view uses the newest update even when it is a guess | Q-10 | 2 LOW-confidence ETAs: SHP1013 ("late by one hour"), SHP1017 ("12:30 to 13:00") | Booking on a guess; the agent must ask, then add a margin |
| I-07 | Several ETAs for one shipment | Q-11 | SHP1006: 10:50 (medium) then 11:20 (high) | Which delay is true must be a rule, not luck |
| I-08 | Duplicate driver message created a second exception | Q-12 | MSG015 (THR009) repeats THR001; dedupe key used twice (EXC001, EXC009) | A repeated "yes, take it" could act twice |
| I-09 | Unclear which shipment the driver means | Q-13 | 4 drivers have 2 live shipments (DRV003, 004, 006, 007); THR010 has no shipment | Acting on the wrong load |
| I-10 | Driver asks about a cancelled shipment | Q-15 | THR012 asks about SHP1019 (cancelled) | Must not offer slots for a cancelled load |
| I-11 | Pending warehouse confirmations have no expiry, and no "held" state exists | Q-16, Q-21 | APT1013A, APT1014A pending since 09:32 and 09:52; no HELD status in any table | A slot can be tied up for ever, and nothing stops two promises while a driver decides |
| I-12 | Escalation message never arrived | Q-17 | OM004 (SHP1015 reefer exception) FAILED; OM002 still QUEUED | A manual decision is needed and nobody was told |
| I-13 | Contact with no name or email | Q-18 | CON005: Gurugram night-shift coordinator is "Vacant Position", no email | A hand-off can go to nobody |
| I-14 | No feasible slot for SHP1015 | Q-19 | 0 rows: D5 (only Jaipur reefer dock) slots 18:00 to 22:00 are BLOCKED for maintenance; ETA 18:30 | The escalation case: a person must decide |
| I-15 | Facility rules are text, not enforced | Q-20 | RULE004 (heavy > 25,000 kg), RULE005 (no new start after 21:00 without approval) | Code must enforce them, or an infeasible slot is offered |
| I-16 | Foreign keys are off on a new connection | Q-00b | `foreign_keys = 0` (stored rows are clean: Q-00c 0 rows) | Our code must switch them on for every connection |
| I-17 | Phone numbers in several tables | Q-22 | 15 driver phones, 5 contact phones, 1 SMS recipient; 0 in chat text | Must never reach a prompt or a log |
| I-18 | Vague messages flagged for a person | Q-23 | MSG005 "late by one hour", MSG016 "late by 45 minutes" | The agent must clarify before acting |
| - | Controls that held | Q-00c, Q-03, Q-07, Q-14 | 0 rows each | No orphans, no double booking, dock types match, thread driver matches shipment driver |

**Top data issue:** SHP1015's booking is a broken promise that nobody is acting on. Its appointment APT1015A is still CONFIRMED for 17:00 to 18:00, but the truck arrives at 18:30 (Q-08). Every reefer slot after that is blocked for maintenance (Q-19). The email asking the night shift to decide FAILED (Q-17).

## Short submission lines
- **How you order competing requests:** a confirmed promise is never taken back automatically; the first hold on a slot wins (5-minute expiry); the last compatible slot of a scarce dock type is kept for top-priority loads; any conflict goes to a coordinator.
- **Which case escalates and why:** SHP1015, a refrigerated 15,000 kg load with ETA 18:30. D5 is the only reefer dock at Jaipur and is under maintenance from 18:00 to 22:00, so no feasible slot exists and a person must decide.
