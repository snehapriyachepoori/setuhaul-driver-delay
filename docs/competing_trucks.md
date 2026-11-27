# Competing trucks and the ordering policy (E3, test T-11)

Five trucks from the brief ask for a new slot at 10:00 on the real snapshot. Only **D2 12:00** and **D4 12:00** are free at noon for standard loads (D1 12:00 is booked by SHP1017, D3 is broken until 13:00).

## A. Today's tier (XS): everyone picks at the same instant

Rule P-2 decides: the first hold wins, whatever the priority. The losers are told the truth and offered the next option.

| truck | priority | weight kg | ETA (conf, +margin) | wanted | got | status | rule that decided |
|---|---|---|---|---|---|---|---|
| SHP1006 | HIGH | 7,800 | 11:20 (HIGH, +15) | D2 12:00 | D3 13:00 | CONFIRMED | wanted slot already held/booked (TAKEN): P-1/P-2, all 3 shown options went, fresh options fetched |
| SHP1009 | CRITICAL | 20,000 | 10:50 (MEDIUM, +30) | D2 12:00 | D1 13:00 | CONFIRMED | wanted slot already held/booked (TAKEN): P-1/P-2, next shown option |
| SHP1012 | NORMAL | 8,000 | 11:10 (HIGH, +15) | D2 12:00 | D4 12:00 | CONFIRMED | wanted slot already held/booked (TAKEN): P-1/P-2, next shown option |
| SHP1013 | NORMAL | 14,000 | 11:00 (LOW, +60) | D2 12:00 | D2 12:00 | CONFIRMED | first to hold (P-2) |
| SHP1014 | CRITICAL | 21,000 | 11:25 (HIGH, +15) | D2 12:00 | D2 13:00 | CONFIRMED | wanted slot already held/booked (TAKEN): P-1/P-2, next shown option |

Policy violations: **0** 

## B. Pilot tier: requests queued and served in P-5 order

Served in this order: SHP1009, SHP1014, SHP1006, SHP1012, SHP1013 (priority first, then earliest latest-finish, then arrival; a request waiting 10 minutes moves up one class).

| truck | priority | weight kg | ETA (conf, +margin) | wanted | got | status | rule that decided |
|---|---|---|---|---|---|---|---|
| SHP1009 | CRITICAL | 20,000 | 10:50 (MEDIUM, +30) | D2 12:00 | D2 12:00 | CONFIRMED | first to hold (P-2) |
| SHP1014 | CRITICAL | 21,000 | 11:25 (HIGH, +15) | D4 12:00 | D4 12:00 | CONFIRMED | first to hold (P-2) |
| SHP1006 | HIGH | 7,800 | 11:20 (HIGH, +15) | D1 13:00 | D1 13:00 | CONFIRMED | first to hold (P-2) |
| SHP1012 | NORMAL | 8,000 | 11:10 (HIGH, +15) | D2 13:00 | D2 13:00 | NEEDS_APPROVAL | first to hold (P-2); needs approval (check 10) |
| SHP1013 | NORMAL | 14,000 | 11:00 (LOW, +60) | D3 13:00 | D3 13:00 | CONFIRMED | first to hold (P-2) |

Policy violations: **0** 

## What each losing driver is told

- Slot taken first: "Sorry, that slot was just taken before I could secure it. Your booking is unchanged. Here are the next options." (P-2)
- Option more than 3 hours after the plan: shown, held, then "A coordinator must approve this" (check 10).
- A slot hidden by P-3 (scarce dock type): "That slot is kept for time-critical loads." Not triggered here: standard docks have more than 3 free slots in the 4-hour window.

## Honest note
At XS tier the system does not reorder simultaneous requests by priority; it is first hold wins (P-2), with P-3 protecting scarce dock types. Priority ordering (P-5) needs the per-facility queue planned for the pilot. Whether that is the right policy is the operations head's decision (open question).
