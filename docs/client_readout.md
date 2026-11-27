# SetuHaul: driver-delay assistant. Client readout (one page)
*For the Head of Operations and the Warehouse Planner. Figures are from the prototype run on your 4 Aug 2026 snapshot (Jaipur, Gurugram).*

**What it does.** When a driver reports a delay, the assistant asks only what it does not already know (usually just "when will you reach the gate?"), shows up to three later dock slots, and books one only after the driver says yes **and** the system has saved it. It never says "confirmed" before the booking is saved. If the old booking is replaced, both changes happen together or not at all.

**The rule that protects you.** One dock slot, one booking. In our test, 10 drivers tried to take the same slot at the same instant, 100 times: **1,000 requests, 100 bookings, 0 double bookings.** With the protection switched off, the same test produced 900 double bookings, so the test really can catch the problem.

**How it chooses when slots run short (policy, pending your decision).** A confirmed promise is never taken back by the system. The first driver to hold a slot keeps it for 5 minutes while deciding. The last compatible slot of a scarce dock type (refrigerated, heavy) is kept for high-priority loads. Anything that conflicts goes to a coordinator. **Be aware:** at today's volume, two drivers asking at the same second are served first-come, not by priority. In our replay of five trucks chasing two noon slots, a NORMAL load could win over a CRITICAL one. Serving by priority needs a short queue per facility, which we recommend for the pilot.

**What it hands to a person.** Safety reports (before any scheduling), no-slot cases, moves more than 3 hours later than planned or to another day, contradictory data, penalties and regulated loads. The coordinator gets a complete record: shipment, what the driver said, the ETA and how sure we are, why no slot worked, what was shown, and what was **not** done. **Example from our run:** SHP1015, a 15,000 kg refrigerated load arriving 18:30. Dock D5 is Jaipur's only reefer dock and is under maintenance from 18:00 to 22:00, so no safe slot exists. It was handed to the Jaipur warehouse coordinator after **one** driver message, with a 15-minute deadline, and the driver was told nothing had changed. (Today, the email about this exact load, OM004, failed to send.)

**Results from the scenario run.** 1 of 2 cases resolved without a coordinator (the other was designed to escalate). 1 question per resolved driver. 0 options turned out infeasible at confirmation. 1 of 1 no-slot hand-offs complete. 0 policy violations across the competing-trucks replays. Planned wait after rescheduling: 80 minutes for SHP1013, including a 30-minute safety margin. Real waiting cannot be measured without gate-in times after rescheduling.

**Problems we found in your data (selected).** Three active bookings sit on docks that were broken or slowed (I-01). Two loads exceed their dock's weight limit: SHP1014 at 21,000 kg on a 20,000 kg dock (I-03). Two bookings end before the truck can arrive (I-04). The availability view ignores dock breakdowns (I-02). The Gurugram night-shift contact is a vacant position (I-13). Full list: 18 issues, each proved by a query.

**Limits (plain).**
- Tested on your snapshot with a simulated clock, not on live systems. No live GPS, so arrival times come from the plan or the driver, and the assistant says how sure it is.
- It cannot check e-way bill expiry or driver rest limits, so later or next-day moves go to a person.
- Hold time, safety margins (15/30/60 minutes), the 3-hour approval threshold, protected slots and response times are **our assumptions**. They sit in one settings file, not in code.
- Safety detection uses a word list, not a trained classifier.
- Sign-in is demo-level (phone number plus a coordinator PIN), not production security.
- Not built yet: coordinator web console, WhatsApp, tracing dashboard, the facility re-planning tool.

**What we need from you.**
1. Which system wins when the dock scheduler, gate check-in and chat disagree?
2. Your priority policy: first-come or by priority when two ask at once, and which slots to protect.
3. What counts as a safety report, and who answers it within how many minutes (the Gurugram night shift has nobody named).
4. Unload times per load type, and what "reduced capacity" means for a dock.
5. Detention cost per truck-hour, so we can turn this into a business case.
