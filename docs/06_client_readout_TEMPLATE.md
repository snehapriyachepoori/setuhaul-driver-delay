# SetuHaul: driver-delay assistant. Client readout (one page)
*For: Head of Operations and Warehouse Planner. Fill the [brackets] from your run. Delete this line.*

**What it does.** When a driver reports a delay, the assistant asks only what it does not already know, shows up to three later dock slots with reasons, and books one only after the driver says yes and the system confirms it. It never says "confirmed" before the booking is saved.

**The rule that protects you.** One dock slot, one booking. In our test, [10] drivers tried to take the same slot at once, [100] times: [1,000] requests, [100] bookings, **[0] double bookings.**

**How it chooses when slots run short (policy).** A confirmed promise is never taken back by the system. The first driver to hold a slot keeps it for [5] minutes. The last compatible slot of a scarce dock type (refrigerated, heavy) is kept for top-priority loads. Anything that conflicts goes to a coordinator.

**What it hands to a person.** Safety reports, no-slot cases, bookings far later than planned or on another day, contradictory data, penalties and regulated loads. The coordinator receives a complete record: the shipment, what the driver said, the ETA and how sure we are, the options shown, and what was not done. Example from our run: [SHP1015, a refrigerated load, no feasible slot, handed over in [x] turns].

**Results from the scenario run.** [x]% resolved without a coordinator. Average [x] questions per driver. [x] options turned out infeasible at confirmation, all refused with a reason. [Other measures from docs/measures.md.]

**Limits (be plain).**
- Built and tested on a synthetic copy of the data, not SetuHaul's live data.
- No live GPS: arrival times come from the plan or the driver, so the assistant states how sure it is.
- The system cannot check e-way bill expiry or driver rest limits, so later or next-day moves go to a person.
- Hold time, safety margins, approval threshold and response times are assumptions that need your decision.
- Authentication is demo-level (phone number and a coordinator PIN), not production security.
- [Not built yet: list it.]

**Open risks and what we need from you.**
1. Which system wins when the dock scheduler, gate check-in and chat disagree?
2. Your priority policy and which slots to protect.
3. What counts as a safety report, and who answers it within how many minutes.
4. Unload times per load type and what "reduced capacity" means for a dock.
5. Detention cost per truck-hour, to turn this into a business case.
