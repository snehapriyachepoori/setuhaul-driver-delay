# Extra marks plan: what to add beyond the core build

Do these AFTER the core (integrity test, tools, agent, scenario run, README). Order is by marks per hour. Each item says what to build and how to know it is done.

## E1. Measures table (about 45 min): `src/measures.py`
Reads the scenario run (`audit_events` plus the saved transcript) and prints a table to `docs/measures.md`. The brief judges nine measures:
| Measure | How to compute | Target |
|---|---|---|
| Time from first message to usable outcome | Turns and seconds per scenario, first driver message to CONFIRMED, options-only answer or hand-off | Report it |
| Share resolved without manual takeover | Scenarios ending CONFIRMED or options-only, divided by all scenarios | Report it |
| Conflicting or duplicate allocations | Slots with more than one live booking at the end (SQL) | 0 |
| Options later found infeasible | Re-run feasibility on every shown offer at confirm time; count failures | Report it, explain each |
| No-slot escalations handled correctly | Hand-off rows with every field filled, divided by no-slot cases | 100% |
| Average driver waiting after rescheduling | Gate-in to dock-in in the scenario run | Report it |
| Warehouse slot utilisation | Slots used divided by slots open in the window | Report it |
| Priority-policy violations | Each allocation checked against the written policy | 0 |
| Driver clarification turns | Questions asked per resolved case | Under 3 |
**Done when:** `python src/measures.py` prints all nine with a number or a stated reason it cannot be measured.

## E2. Failure tests (about 1 hour): `tests/failure/`
| ID | Test | Pass rule |
|---|---|---|
| T-19 | Duplicate message (THR009 "Take the 11 o'clock slot" twice) | One booking action; the second reply is the stored first reply |
| T-20 | Stale option: driver is shown slot X, a coordinator blocks X, the driver says "take it" | Refused with a reason and new options; no booking |
| T-21 | Crash between "cancel old booking" and "create new" (raise an error in the middle) | Database unchanged; old booking still active |
| T-22 | Force the commit to fail | The driver is never told "confirmed" |
| T-23 | Expired hold | A confirm after expiry is refused |
| T-24 | Wrong driver (T-18 from the architecture): unknown phone, or another driver's shipment | No session or MISMATCH; no data leaked |
**Done when:** `pytest tests/failure -q` is green; save output to `docs/failure_tests.txt`.

## E3. Competing trucks and the ordering policy (about 45 min)
- Replay SHP1006, SHP1012, SHP1013, SHP1014 and SHP1009 asking for nearby slots at the same time.
- Show for each: who got what, which rule decided (P-1 to P-5), and the exact message each loser received.
- Test T-11: no allocation breaks the written policy.
**Done when:** `docs/competing_trucks.md` has a table of requests, outcomes and the rule applied, and you can explain each in one sentence.

## E4. One-page client readout (about 45 min): `06_client_readout_TEMPLATE.md`
Fill it with real numbers from E1 to E3 after the run. Plain words, no jargon, for the head of operations and a warehouse planner. Keep it to one page.

## E5. LangSmith trace (about 30 min, last)
Add after everything works. Make a free account and key, put the key in `.env`, and follow LangSmith's own documentation for the variable names (not checked here). Run one scenario with tracing on and save a screenshot or share link in `docs/`. Synthetic data only.

## E6. Optional scheduling tool (about 1.5 hours, only if time remains)
- **Tool:** `propose_facility_plan(facility_id)` reads a structured snapshot (never free text) and returns a ranked sequence. It proposes; the capacity module and a coordinator still decide.
- **Objective in plain words:** less waiting, fewer missed appointments, fewer changes to a schedule already told to a driver.
- **Rule first:** earliest latest-finish first, weighted by priority. Trucks already unloading are fixed. Gate-in proves a truck is available now. Use a 60-minute unload time (unknown; say so).
- **Replay:** an early truck (SHP1002), a late truck (SHP1003) and trucks in progress (SHP1004, SHP1006) share one facility. Compare total waiting with first-come-first-served.
- **Done when:** `docs/scheduler_replay.md` shows both results and what changed for the already-promised trucks.
