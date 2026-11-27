# Submission item 1: Problem Definition Sheet and data audit (short version)

> **Data status: STAND-IN.** The audit below ran on `dummy_setuhaul.db`, a synthetic database built to match the brief's table names and counts. Its problems were planted on purpose. **Do not submit these results as findings about the client's data.** Rerun on the real file, then replace the Result column: `python3 run_audit.py REAL.db`. If you cannot get the real file, say "audited on a synthetic stand-in" in your submission.

## Client and problem
- **Client:** SetuHaul Logistics, a third-party logistics company. Full-truckload freight in North and West India: 280 to 360 loads a day, 6 facilities, 32 docks (brief-stated).
- **Problem (one sentence):** How might SetuHaul let drivers report delays and consider new appointments by chat, while many requests compete for a few dock slots, without false or conflicting promises?
- **Surface vs underlying:** one driver needs a clear, true answer. Underneath, 20 to 35 messages in 30 minutes chase the same few slots, so two drivers can both be told yes to one slot.
- **Design target:** 35 messages in 30 minutes across 6 facilities. Test on the snapshot (21 shipments, 9 docks).

## Facts, assumptions, unknowns
- **Brief-stated:** 0 live GPS feeds; 5 coordinators a shift; the database already enforces one active appointment per slot and one current appointment per shipment.
- **Assumptions:** drivers write in mixed Hindi and English; gate check-in is the only reliable arrival proof; duplicate chat messages happen.
- **Unknowns (owner):** which system wins in a conflict (operations head); unload time per load (warehouse planner); detention cost (finance); e-way bill and driver rest data (data owner).

## Rules that must never break (invariants)
1. Never two active bookings on one slot.
2. Never tell a driver a slot is theirs before it is committed.
3. Re-check a slot at the moment of commit; never book a stale option.
4. A safety report always goes to a person.
5. Confirm the right shipment before acting.
6. A repeated message never causes a second action.
7. No feasible slot means escalate, never invent an answer.
8. The model never decides capacity, ranking or commit.

## Data audit (query file: `01_audit_queries.sql`)
| Issue | Query | Stand-in result | Why it matters |
|---|---|---|---|
| Foreign keys are off by default | Q-00 | `foreign_keys = 0` | Orphan rows possible |
| One ETA stored in UTC (`Z`), the rest +05:30 | Q-02 | 1 of 12 | Wrong time comparisons |
| Booking on a dock in breakdown | Q-06, Q-07 | APT1002 | Promised slot unusable |
| Appointment ends before the truck's latest ETA | Q-11 | 3 (SHP1013, 1014, 1015) | Promise already broken |
| Several different ETAs for one shipment | Q-12 | 3 shipments | Which delay is true |
| Booked on one dock, checked in at another | Q-13 | SHP1004 | Conflicting state |
| Duplicate chat message | Q-14 | THR009 | A repeated "take it" could double-act |
| Driver with two loads; thread with no shipment | Q-15 | DRV004, THR010 | Wrong shipment risk |
| Rule clash: D5 closes 19:00, facility open to 22:00 | Q-17 | RULE005 | Infeasible slot offered |
| No "held" state exists | Q-18 | none found | Nothing prevents two promises while a driver decides |
| Availability view shows a blocked slot as free | Q-19 | SLT0521 | A "free" slot that is not free |
| Phone number typed into a chat | Q-20 | MSG014 | Privacy |
| Clean on the stand-in | Q-03, 04, 05, 08, 09, 10 | 0 rows | Controls that behaved |

Also found (stand-in): thread THR011's driver differs from the driver assigned to SHP1017. Add it as a query when you rerun.

**Top data issue for the template (stand-in):** the booked slot ends before the truck's latest ETA (Q-11), so a promise is already broken. Replace this after the real run.

## Short submission lines
- **How you order competing requests:** a confirmed promise is never taken back; the first hold on a slot wins; the last compatible slot is kept for top-priority loads; any conflict goes to a coordinator.
- **Which case escalates and why:** SHP1015, a refrigerated load with no feasible slot (the only reefer dock is in maintenance from 19:00).
