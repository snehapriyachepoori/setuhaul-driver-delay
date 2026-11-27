# Problem Definition Sheet: SetuHaul Logistics Pvt. Ltd.

**Snapshot:** 4 August 2026, Asia/Kolkata (+05:30) | **Data:** SQLite, 18 tables + 4 views, 275 rows (as stated in the brief)
**Written:** 25 November 2026 | **Status: DRAFT FROM THE BRIEF ONLY**

> **The SQLite database was not in the upload.** Only the 10-page PDF brief arrived. So:
> - Nothing here is a proved **Fact**. Every number from the brief is tagged **Brief-stated** (the client says so, we have not checked it).
> - Every data issue in section 6 is a **Candidate**: its query is written in `01_audit_queries.sql` but has **not been run**.
> - Things I could only read off the brief's pictures (for example the dock chart on page 6) are tagged **From figure**.
> - To finish this step: put the `.db` file next to the queries, run `sqlite3 setuhaul.db < 01_audit_queries.sql`, and paste each result into section 6.

---

## 0. Context profile

Scored 25 Nov 2026. "High" lenses are developed below and must reappear later in the sheet (invariant, boundary, measure or question).

| # | Lens | Score | Reason | Shows up later in |
|---|---|---|---|---|
| 1 | Industry and business model | **High** | Third-party logistics: full-truckload freight, 280–360 loads/day, 190–240 dock appointments/day (Brief-stated). A late truck breaks truck, load, route, dock, labour and customer promises at once. | Problem statement, measures |
| 2 | Location and geography | **High** | North and West India; Jaipur DC in the data; Hindi/Hinglish likely (the brief's own example is "Tyre damaged near Neemrana"); highway connectivity unknown. | Questions Q1, Q2; invariant I-6 |
| 3 | Financial and commercial | **High** | Detention is "the cost of a poor schedule"; customer penalties and compensation are named as human decisions. No rates or contract terms supplied. | Measures M-10; boundary; questions |
| 4 | Legal and regulatory | **High** | E-way bill validity can run out during a delay; driver working-hour rules; (see 9.1). | Invariants I-7, I-8; questions |
| 5 | Compliance and audit | **Medium** | Brief demands a hand-off record and proof of no double booking, so an audit trail is needed. No regulator-mandated retention period known. | Invariants I-9; measure M-6 |
| 6 | Data privacy and security | **High** | Driver phone numbers (`drivers.phone`), chat text, and possibly location in messages. India's DPDP Act is being phased in (see 9.1). | Invariant I-10; questions |
| 7 | Safety and people | **High** | Brief lists "driver safety decisions" as human-only; a driver reporting a tyre failure or breakdown may be unsafe or tired. Contract vs employed drivers: unknown. | Invariants I-5, I-7; boundary |
| 8 | Technology and integration | **Medium** | No live GPS (0 feeds); five parties in five systems joined into one snapshot. Which chat channel drivers use (WhatsApp, SMS, app) is not stated. | Unknowns U-3, U-4 |
| 9 | Organisation and decision rights | **Medium** | 5 operations coordinators per shift; brief gives a "person approves" list. Who owns priority policy: not stated. | Boundary; question Q6 |
| 10 | Ethics and fairness | **Medium** | When capacity runs short, someone loses a slot. Rule for who loses is "not supplied" and must be defensible to carriers. | Invariant I-4; question Q6 |

### Glossary (starter, 18 terms)
| Term | Meaning |
|---|---|
| Dock door / bay | Place where a truck backs up to unload. The scarce resource. |
| Appointment slot | A time window on one dock. One slot holds one active booking. |
| Compatible dock | A dock that accepts this truck and load (reefer and heavy have few). |
| ETA | Estimated arrival time. From plan, driver, warehouse or an operations override. Can be wrong. |
| Exception | An event making the plan uncertain (breakdown, delay). Starts a conversation. |
| Detention | Waiting beyond the expected unloading time. |
| Reefer | Refrigerated truck/load. Needs a reefer dock (D5 in the figure). |
| Heavy | Heavy-load vehicle/load. Needs a heavy dock (D6 in the figure). |
| Gate-in / check-in | Evidence the truck has actually arrived (`facility_checkins`). |
| No-show | Booked truck that did not arrive. |
| Reduced capacity | A dock or window that works at partial throughput. |
| Planned maintenance | Dock offline on purpose. |
| System of record | The one system that owns a fact. |
| Invariant | A rule that must never break. |
| Partial unique index | Uniqueness enforced only for rows matching a filter (here: active appointments). |
| E-way bill | GST document that must accompany goods in transit; has an expiry. |
| FTL | Full truckload. |
| Hold | A temporary claim on a slot while a driver decides (concept the schema may not have; see I-17). |

---

## 1. Problem statement (one sentence)

**How might** SetuHaul give drivers a conversational way to report delays, ask questions and consider revised appointments, **so that** each driver gets a clear, true answer, **while** many simultaneous requests compete for limited dock capacity without infeasible or conflicting promises?

## 2. Surface vs underlying problem

- **Surface (one driver):** a driver says they are late. They need the right questions asked, only the facts the backend lacks, a plain reply at each turn, and a revised slot or a human.
- **Underlying (many drivers):** 20–35 messages can arrive within 30 minutes (Brief-stated), while the usable replacement slots stay few. Two conversations can read the same open slot and both be told yes. Only one promise can be true.

Sub-problems:
1. **Replies:** what the driver hears at each turn.
2. **Re-scheduling:** what replaces the slot that will be missed.
3. **Warehouse constraints:** docks, hours, local rules, other bookings.
4. **Truck and driver constraints:** vehicle, load, next pickup, latest acceptable finish.
5. **Many requests at once:** many drivers, one limited slot set.
6. **Changing world:** options change or disappear mid-conversation; messages repeat.

## 3. System map

### 3.1 Actors
| Party | Knows | Needs during an exception |
|---|---|---|
| Driver | Real location, breakdown, traffic, likely delay | Clear choices, instructions, confirmation |
| Dispatcher / carrier | Vehicle assignment, driver availability | Revised plan, escalation status |
| SetuHaul operations (5 coordinators/shift) | Shipment plan, customer commitment, open exceptions | One consistent view across many simultaneous requests |
| Warehouse planner | Dock capacity, labour, equipment, local rules | Feasible arrivals without overbooking |
| Consignee / customer | Inventory or production dependency | Reliable revised arrival information |

### 3.2 Systems of record (Brief-stated; the snapshot joins them)
| Fact | Owner |
|---|---|
| Shipments, drivers, vehicles | Transport system |
| Dock capacity, slots, appointments | Dock scheduler |
| Who has actually arrived | Gate check-in |
| What the driver says, ETA updates | Chat / ETA updates |
| Confirmations sent | Messaging system |

Open: which system wins when two disagree. See Unknown U-1.

### 3.3 Lifecycle of one truck
| # | Stage | Data created or changed | Tables |
|---|---|---|---|
| 1 | Shipment planned | origin, destination, goods, priority | `shipments` |
| 2 | Driver and truck assigned | carrier, driver, vehicle | `carriers`, `drivers`, `vehicles` |
| 3 | Appointment booked | receiving window promised | `appointment_slots`, `appointments` |
| 4 | Truck travels | original ETA; driver may declare a new one | `eta_updates` |
| 5 | Gate and yard | check-in, may wait for a dock | `facility_checkins` |
| 6 | Dock and unload | truck on a bay | `facility_checkins`, `dock_status_events` |

### 3.4 Scarce resource
Dock appointment slots (time on a dock). Only stage 6 consumes it. Also scarce, per brief: labour and equipment, operating hours and safety capacity.

### 3.5 Entity model, enforced constraints, and gaps
Chain: driver, vehicle, shipment, facility, dock, slot, appointment. (ER diagram, brief p.7.)

**Enforced (Brief-stated; confirm with Q-00):**
- One active appointment per slot (partial unique index).
- One current active appointment per shipment (partial unique index).

**What these do NOT cover (Candidate gaps, each with its check):**
| Gap | Why the indexes miss it | Check |
|---|---|---|
| A slot being *held* while a driver decides | Only active appointments are counted; a "hold" may not exist as a state | Q-18 |
| Overlapping slots on one dock | Uniqueness is per `slot_id`, not per time range | Q-10 |
| Booking on a broken, blocked or maintenance dock | No link between appointment and dock status | Q-06, Q-07 |
| Dock type vs load type (reefer, heavy) | Not an index concern | Q-08 |
| Slot outside facility hours or rules | Rule table is separate | Q-09, Q-17 |
| Appointment earlier than the latest ETA | No time rule between ETA and slot | Q-11 |
| Duplicate chat messages and retries | Not in appointments | Q-14 |
| Conflicting ETAs from different sources | `eta_updates` allows many | Q-12 |
| Views disagreeing with base tables | Views are not constraints | Q-19 |
| FKs declared but not enforced (SQLite default) | `PRAGMA foreign_keys` is off unless set | Q-00 |

## 4. One input read like an FDE

Message from the brief: *"Tyre damaged near Neemrana. Around 90 minutes late. Can I get something after 7? I also have another pickup tonight."*

| **Ask the driver** (only they know) | **Look up in the backend** (system holds it) |
|---|---|
| What broke, and is it fixed? | Which active shipment this driver means |
| Is 90 minutes the repair time or the total arrival delay? | Current appointment and when it stops working |
| Latest time you can finish unloading? (next pickup tonight) | Priority of this load |
| Do you want to see options, or book one? | Which docks and later slots accept this truck and load |
| | Has the truck arrived? Is any slot held, requested or confirmed? |

Rule applied: never ask for what the backend holds; never trust the driver over a fact the backend holds.
The three example chats required for Decision 1 (THR003, THR010, THR011) are pulled by Q-21. **Not yet done: no data.**

## 5. Facts, Estimates, Assumptions, Unknowns

Types: **Fact** (proved by data, carries query ID), **Estimate**, **Assumption**, **Unknown**, **External rule**, and for this draft **Brief-stated** (client says so, not yet checked).

**Facts: none yet.** (No data.)

**Brief-stated (verify with Q-01 and others)**
| ID | Statement | Check |
|---|---|---|
| B-1 | 280–360 loads/day; 6 destination facilities; 32 dock doors; 190–240 appointments/day | Operating profile; the snapshot is smaller (2 facilities, 9 docks, 21 shipments) |
| B-2 | 15–25 driver exception messages on a normal day; 20–35 in 30 min during a spike | Q-01 counts only the snapshot |
| B-3 | 5 coordinators per shift; 0 live GPS feeds | Unknown U-4 |
| B-4 | 18 tables; 275 rows; 2 facilities; 9 docks; 21 shipments; 106 slots; 20 appointments | Q-01 |
| B-5 | Snapshot 4 Aug 2026 Asia/Kolkata, timestamps +05:30 | Q-02 |
| B-6 | Two partial unique indexes exist | Q-00, Q-05 |

**From figure (brief p.6; Jaipur DC, 4 Aug 2026), to check against data**
- 6 docks D1–D6; D1–D4 Standard, D5 Reefer, D6 Heavy. 9 docks overall means 3 elsewhere.
- D3 appears blocked after SHP1005; D2 shows a breakdown marker near SHP1002; D5 appears under planned maintenance after SHP1015; SHP1014 and SHP1013 are pending confirmation; SHP1008, 1016, 1019 cancelled; SHP1018 no-show.
- Status of the legend is read from a picture, not a table.

**Estimates:** none. (ATRI's 39.3% detention and 135 million hours are **US figures, not SetuHaul data**; context only.)

**Assumptions** (how we would test)
| ID | Assumption | Test |
|---|---|---|
| A-1 | Drivers write in Hinglish or mixed scripts | Read `chat_messages` (Q-21) |
| A-2 | Gate check-in is the only reliable arrival evidence | Q-13 |
| A-3 | `shipments.latest_eta_ts` equals `v_latest_eta` | Q-12 |
| A-4 | Messages can arrive twice from the chat channel | Q-14 |
| A-5 | Facility opening hours bind slot choice | Q-09, Q-17 |

**Unknowns** (who to ask)
| ID | Unknown | Owner |
|---|---|---|
| U-1 | Which system wins when two disagree | SetuHaul operations head |
| U-2 | Unload duration per load type | Warehouse planner |
| U-3 | Which chat channel drivers use | SetuHaul technology |
| U-4 | Whether coordinators can act on a hand-off in real time | Operations head |
| U-5 | Detention charges, penalty terms, SLA credits | SetuHaul finance |
| U-6 | Whether the e-way bill expiry is stored anywhere in the data | Data owner |
| U-7 | What happened after 4 Aug 2026 (snapshot limit) | n/a, cannot be known |

## 6. Data audit issues (all CANDIDATE: query drafted, NOT RUN)

Format: ID | What | Query | Result | Why it matters | Severity.
Severity is my expectation, not a finding.

| ID | What | Query | Result | Why it matters | Sev (expected) |
|---|---|---|---|---|---|
| I-01 | Mixed time zones or formats | Q-02 | not run | Wrong comparison of ETA and slot | H |
| I-02 | NULLs in shipment keys, ETA, dock type, priority | Q-03 | not run | Cannot judge feasibility | H |
| I-03 | Orphan rows across links | Q-04 | not run | A message or booking points at nothing | M |
| I-04 | Control: both indexes hold | Q-05 | not run | Confirms what the DB really protects | M |
| I-05 | Active booking on broken or maintenance dock | Q-06 | not run | Promised slot is unusable | H |
| I-06 | Active booking on a blocked slot | Q-07 | not run | Same | H |
| I-07 | Dock type does not match load | Q-08 | not run | Truck cannot unload | H |
| I-08 | Slot outside facility hours | Q-09 | not run | Infeasible slot offered | M |
| I-09 | Overlapping slots on one dock | Q-10 | not run | Two trucks, one bay, index silent | H |
| I-10 | Appointment earlier than latest ETA | Q-11 | not run | Existing promise already broken | H |
| I-11 | Several ETA sources disagree | Q-12 | not run | Which delay is true | H |
| I-12 | Status contradictions (cancelled but checked in, etc.) | Q-13 | not run | Wrong state for the driver | M |
| I-13 | Duplicate chat messages | Q-14 | not run | A repeated "take it" could double-act | H |
| I-14 | Driver with several shipments/threads; thread without shipment | Q-15 | not run | Wrong shipment is linked | H |
| I-15 | Exception rows missing thread, shipment or ETA | Q-16 | not run | Hand-off record incomplete | M |
| I-16 | Facility rule clashes (RULE005 named in ladder) | Q-17 | not run | Rules contradict a dock or hours | M |
| I-17 | No "held" state in slot or appointment vocabulary | Q-18 | not run | Decision 5 and 6 have nothing to stand on | H |
| I-18 | Views disagree with base tables | Q-19 | not run | A "free" slot that is not free | H |
| I-19 | Phone numbers in free text or contact tables | Q-20 | not run | Privacy exposure | M |

## 7. Scale and load

| | Normal | Peak | In the snapshot |
|---|---|---|---|
| Loads/day | 280–360 | n/a | 21 |
| Appointments/day | 190–240 | n/a | 20 |
| Driver exception messages | 15–25/day | 20–35 within 30 min | 20 messages, 12 threads, 10 exceptions |
| Dock doors | 32 over 6 facilities | n/a | 9 over 2 facilities |
| Coordinators | 5 per shift | n/a | n/a |

**Design for:** 35 messages in 30 minutes across 6 facilities (about 1 per minute averaged, but bunched into the same few slots, so contention matters more than rate).
**Test on:** the snapshot (about 7% of daily scale by loads). The snapshot is too small to show real queue behaviour; concurrency tests must be synthetic.

## 8. Invariants (must never happen; each must be testable)

| ID | Rule | Test idea |
|---|---|---|
| I-1 | Two shipments never hold active appointments on the same slot | Parallel booking test, count active per slot = 1 |
| I-2 | No driver is told a slot is theirs unless the system of record has it committed | Compare each message to DB state |
| I-3 | A slot the driver is told about is re-checked at the moment of commitment | Change slot state between offer and accept; expect refusal |
| I-4 | Priority ranking follows the stated policy; no silent re-ranking | Replay competing trucks; check against policy |
| I-5 | A safety-related report (injury, unsafe vehicle) is never auto-resolved | Seed message; expect hand-off |
| I-6 | The right shipment is confirmed before any action | Driver with 2 shipments; expect a question |
| I-7 | Never confirm a plan whose arrival would pass a known e-way bill expiry without escalation | Seed expiry case; expect hand-off (needs data, U-6) |
| I-8 | Never confirm a plan that breaks a known driver rest or hours limit without a human | Seed case; expect hand-off |
| I-9 | Every escalation leaves a complete hand-off record (who, what, state, options shown, why) | Field completeness check |
| I-10 | Driver phone number or location is not copied into logs or messages beyond purpose | Log scan |
| I-11 | Duplicate or retried messages never cause a second booking or a second change | Replay same message twice |
| I-12 | A stale option is never booked | Option shown, then slot lost; expect refusal and new options |
| I-13 | No-slot case never ends in an invented answer | Seed SHP1015; expect escalation |
| I-14 | The agent never decides capacity, dock fit, ranking or commit by itself (brief boundary) | Code review: these live in code, not in prompt |

## 9. Scope and boundaries

| **The agent never decides alone** | **A person approves or takes over** | **Out of scope** |
|---|---|---|
| Whether two drivers can be promised the same capacity | Driver safety decisions | National transport-network optimisation |
| Whether a vehicle fits a dock | Penalties, compensation, customer commitments | Carrier selection and freight-rate talks |
| How scarce capacity is ranked when rules conflict | Cases with no feasible slot | Autonomous driver-safety decisions |
| Whether a booking is committed in the system of record | Contradictory data, regulated loads, emergencies | Customs, hazardous-material, legal workflows |
| | | Commercial penalty approval |

(From brief p.9.) **In scope:** conversational exception service, capacity layer that holds/confirms/releases, escalation path, a test that tries to double-book and fails. **Optional:** facility-level scheduling tool.

### 9.1 External rules (not legal advice; to be confirmed by SetuHaul's legal/compliance owner)

Checked 25 Nov 2026 against web sources. Treated as **Assumptions** until the owner confirms.

| Rule | What I found | Source(s) | Date checked | Owner to confirm |
|---|---|---|---|---|
| **DPDP Act 2023 / DPDP Rules 2025** (driver phones, chat text, location) | Rules notified 13–14 Nov 2025, phased. Consent Manager framework (Rule 4) scheduled for mid-Nov 2026. The main notice, consent and security obligations (Rules 3, 5–16, 22, 23) scheduled for about 13–14 May 2027. Sources give slightly different day-of-month (12, 13, 14), so use the official gazette text. | Delhi govt. IT dept. Annexure-I; AZB & Partners; Legal500 | 25 Nov 2026 | SetuHaul legal / data protection lead |
| **GST e-way bill validity** (a long delay or next-day reschedule can run past expiry) | Regular cargo: 1 day per 200 km or part thereof; over-dimensional cargo: 1 day per 20 km; extension is possible before expiry for reasons such as breakdown. One page I found still says 100 km per day, which is the pre-2021 rule; I treat it as outdated. Exact expiry time (some pages say midnight of the last day) and limits on number of extensions are **not confirmed**. | ClearTax; Tally; Angel One; VATupdate (cites CGST Rule 138(10)) | 25 Nov 2026 | SetuHaul tax / compliance |
| **Driver hours** (rest) | Motor Vehicles Act 1988 s.91 sends hours of work to the Motor Transport Workers Act 1961. That Act: 8 hours/day, 48/week (s.13, with exceptions); 30-min rest after 5 hours (s.15); 9 consecutive hours' rest between duties (s.15); spread-over 12 hours (s.16). Enforced by states. Contracted drivers may fall under the carrier, not SetuHaul. 2026 labour-code changes (OSH Code) were mentioned in press; I did **not** verify their current in-force status. | Indian Kanoon text of ss.13, 15, 16; Lok Sabha reply 13 Mar 2025 | 25 Nov 2026 | SetuHaul legal and carriers' HR |
| **City truck-entry windows** (Jaipur, Delhi NCR) | **Not checked.** Listed as a starter question. | n/a | not checked | Operations head |

## 10. Success measures

Brief measures plus two extra for High lenses. Baselines are all Unknown until the scenario run.

| ID | Measure | Why it matters | How measured | Baseline |
|---|---|---|---|---|
| M-1 | Time from first message to usable outcome | Speed | Turns and elapsed time per scenario | Unknown |
| M-2 | Share resolved without manual takeover | Automation coverage | Count over scenario set | Unknown |
| M-3 | Conflicting or duplicate allocations | Correctness under concurrency | Integrity test result (target 0) | Unknown |
| M-4 | Options later found infeasible | Freshness | Re-check each shown option at confirmation | Unknown |
| M-5 | No-slot escalations handled correctly | Safe failure | Completeness of each hand-off record | Unknown |
| M-6 | Hand-off record completeness (audit lens) | Audit trail | % of escalations with all required fields | Unknown |
| M-7 | Average driver waiting after rescheduling | Operational outcome | Gate-in to dock-in in scenario run | Unknown |
| M-8 | Warehouse slot utilisation | Capacity efficiency | Slots used / slots open in window | Unknown |
| M-9 | Priority-policy violations | Policy compliance | Decision vs stated policy | Unknown |
| M-10 | Detention hours avoided (financial lens) | Money | Waiting beyond unload time, before vs after | Unknown; rate unknown (U-5) |
| M-11 | Driver clarification turns | Conversation effort | Questions asked per resolved case | Unknown |
| M-12 | Cases where an e-way bill or rest-hour risk was flagged to a human (legal/safety lens) | Compliance | Seeded cases, expect 100% | Unknown |

## 11. Situation ladder (from the brief; IDs are the brief's)

| Level | Situation | Where to look | What it proves |
|---|---|---|---|
| 1 | Driver only asks about options | THR011, SHP1017 | Separating asking from booking |
| 2 | Message misses key facts | THR003, SHP1013, THR010, DRV004 | Ask before calling a tool |
| 3 | Rules and compatibility narrow choices | SHP1010, SHP1015, SHP1016, RULE005 | Feasibility is more than an empty row |
| 4 | Several delayed trucks chase nearby slots | SHP1006, SHP1012, SHP1013, SHP1014, SHP1009 | A defensible allocation policy |
| 5 | World changes mid-conversation | SHP1005, APT1008, THR001, THR009, SHP1002 | Recovery and safe retries |
| 6 | No feasible slot exists | SHP1015, THR005, OM004 | Escalation, not invention |
| + | Early truck, late truck, work in progress share a facility | SHP1002, SHP1003, SHP1004, SHP1006 | Optional facility-level objective |

Solve bottom-up. Contents of these rows are **not yet read** (no data).

## 12. Open questions (owner)

| # | Question | Owner |
|---|---|---|
| Q1 | Which chat channel and languages do drivers use? | SetuHaul technology / operations |
| Q2 | Are there city truck-entry windows or local restrictions at destination facilities? | Operations head |
| Q3 | Which system wins when shipment plan, dock scheduler and gate check-in disagree? | Operations head |
| Q4 | Is the e-way bill number and expiry available per shipment? Who extends it? | Tax / compliance |
| Q5 | Which hours and rest rules does SetuHaul apply to contracted drivers? | Legal + carriers' HR |
| Q6 | What is the priority policy when capacity is short, and who owns it? | Operations head |
| Q7 | Detention charges, penalty terms, who pays? | Finance |
| Q8 | How long should an offered slot be reserved while a driver decides? | Warehouse planner |
| Q9 | Retention and purpose limits for chat text and phone numbers? | Legal / data protection lead |
| Q10 | How do coordinators receive hand-offs, and how fast must they respond? | Operations head |
| Q11 | Unload duration by load type and dock? | Warehouse planner |
| Q12 | Can the database file be shared so the audit queries can be run? | You / FDE Academy (delivery@fde.academy) |

## 13. Parking lot (solution ideas for later steps; NOT decisions)

- Explicit hold state with expiry for offered slots.
- Atomic "check and commit" in one transaction.
- Idempotency key per inbound message.
- Re-validate every shown option at the moment of confirmation.
- Deterministic scoring for feasibility and ranking in code.
- Scheduling tool for the optional extension; start with a simple dispatch rule.
- Structured hand-off record template.

---

## What this data cannot tell us (snapshot limits)
- Nothing after 4 Aug 2026; no history of how often slots clash.
- No live GPS, so ETAs are plan, driver, warehouse or override only.
- Snapshot is about 7% of daily load by shipments; real contention behaviour must be simulated.
- Chat text exists for 20 messages only; language mix cannot be generalised.
- No contract, rate or e-way bill data is listed in the tables.

## Quality gate (before handing to step 2)
| Check | Status |
|---|---|
| Every fact has a query ID and the query was run | **FAIL: no data uploaded; queries drafted only** |
| No causes or solutions in the body; ideas in Parking Lot | Pass |
| Problem statement names who, outcome, hard constraint | Pass |
| Single-user and many-users problems both covered | Pass |
| Invariants written as testable rules | Pass |
| Gaps in DB constraints listed | Pass (candidates, checks drafted) |
| Ladder uses real IDs from the data | Pass for IDs from brief; contents not read |
| Snapshot limits stated | Pass |
| All 10 lenses scored with reason | Pass |
| Every High lens appears later | Pass (see table in section 0) |
| Every external rule has source, date, owner, and no legal advice | Pass; city truck-entry rule marked not checked |

**Do not start step 2 (WHY) until the database has been audited and the FAIL above turns to Pass.**
