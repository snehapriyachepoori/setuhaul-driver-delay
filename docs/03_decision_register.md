# Decision register: SetuHaul driver-delay service

**Written:** 25 November 2026. **Updated:** 27 November 2026 with evidence from the real snapshot (`setuhaul_freight_operations.db`); audit IDs (I-xx, Q-xx) refer to `01_submission_problem_sheet.md` and `01_audit_queries.sql`.
Evidence labels: **Data** (proved by a query on the real snapshot), **Brief** (stated in the brief), **Mechanism** (shown in step 2), **Test** (produced by the build; filled in when it runs), **Assumption** (value with a named owner).
Each entry: options, chosen, reason, evidence, consequences, revisit trigger. Section numbers point to `03_architecture.md`.

## Brief decisions 1 to 13

### D-01 What to collect before showing options (brief 1)
- **Options:** ask for everything up front; ask only what the backend lacks; show options first and ask later.
- **Chosen:** ask only for missing facts: which load (only if more than one), the **arrival time at the gate** and what a stated delay means (arrival delay or repair time), the latest time they can finish unloading, and whether they want options or a booking. Never ask for appointment, priority, dock type or arrival state: those are looked up.
- **Reason:** asking for backend facts wastes the driver's time; trusting the driver over the backend risks a wrong promise (Brief p.3). Measure M-11.
- **Evidence (three real chats, Data Q-21/Q-23):**

| Chat | Driver wrote | Looked up (never asked) | Asked for |
|---|---|---|---|
| THR003, SHP1013 | "I am late by one hour." (flagged for review) | slot D2 11:00 (pending), NORMAL priority, STANDARD dock | the arrival time: "So you reach the gate about 11:00?"; latest finish |
| THR010, DRV004, no shipment | "I will be late by 45 minutes." | DRV004 has SHP1004 and SHP1020 | which load first; then the arrival time |
| THR011, SHP1017 | "What slots are possible after 1 PM if I reach around 12:45?" | LOW priority, STANDARD dock | nothing: show options only, reserve nothing |

- **Consequences:** two to three questions at most per case.
- **Revisit if:** the scenario run shows average clarification turns above 3.

### D-02 Linking a conversation to driver, shipment and appointment (brief 2)
- **Options:** trust the thread's shipment link; trust the text; derive from the channel identity and confirm.
- **Chosen:** driver from the channel identity (phone matched to `drivers.phone`, never shown to the model); candidates = that driver's live shipments; ask if more than one; every tool re-checks the shipment belongs to that driver.
- **Reason:** a thread's shipment link is optional (THR010 has none) and 4 drivers hold two live loads (Data Q-13).
- **Evidence, message-to-rows trace for THR010 (Data):** MSG016 "I will be late by 45 minutes." in THR010 -> `chat_threads.driver_id` = DRV004, `shipment_id` NULL -> `shipments` where driver_id = DRV004 and status not COMPLETED/CANCELLED -> SHP1004 (WAITING in the Jaipur yard since 09:25, appointment APT1004 on D2 09:00) and SHP1020 (ASSIGNED, appointment APT1020 on D2 18:00, ETA 18:00) -> two rows -> AMBIGUOUS -> ask "ORD-260804-004 or ORD-260804-020?". SHP1004 is already at the gate (Data Q-13, check-ins), so a 45-minute delay can only refer to SHP1020: the agent may suggest it, but the driver confirms.
- **Control:** thread driver equals shipment driver for every linked thread (Data Q-14, 0 rows), so the MISMATCH path is tested with a seeded case, not real data.
- **Consequences:** one extra question for multi-load drivers.
- **Revisit if:** the real channel cannot give a trustworthy identity.

### D-03 Revised ETA and how sure we are (brief 3)
- **Options:** latest update wins (today's `v_latest_eta`); plan time; a rule with source, confidence and margin.
- **Chosen:** section 9.4: operations override > driver's time confirmed in this chat > newest driver or warehouse estimate (the later one if both). Margin by confidence: HIGH 15, MEDIUM 30, LOW 60 minutes (**Assumption**, owner warehouse planner). The **kind** is kept: a repair time is not an arrival time. All times converted to one zone and compared as numbers.
- **Reason:** `v_latest_eta` takes the newest row even when it is a guess: SHP1013 and SHP1017 are LOW confidence (Data Q-10, I-06). SHP1006 has two ETAs, 10:50 then 11:20 (Data Q-11).
- **Evidence, the rule applied to two real messages:**

| Message | Kind | Steps | Planning ETA |
|---|---|---|---|
| THR003 "I am late by one hour." (SHP1013, stored as 11:00 LOW) | Delay amount, unclear | Ask: "So you reach the gate about 11:00?" If yes: confirmed, HIGH. If no answer: keep 11:00 LOW | 11:15 if confirmed; 12:00 if not (LOW + 60), and the reply says it is an estimate |
| THR002 "Tyre repaired. I can reach 11:10. I need to leave the warehouse before 1:30" (SHP1012) | Repair is done; 11:10 is an arrival time | Repair time is not used; 11:10 is the arrival. Ask whether 1:30 is the latest gate-out or latest start (the seed agent asked this) | 11:25 (HIGH + 15); latest finish 13:30 if it is gate-out |

- **Consequences:** offers are slightly conservative; margins are assumptions until gate-in history exists.
- **Revisit if:** gate-in history shows margins too large or too small.

### D-04 What makes a slot feasible (brief 4)
- **Chosen:** ten ordered checks with reason codes (section 9.5), **plus a weight check** found in the real data: load weight must not exceed the dock's limit. One function is used when showing, holding and confirming.
- **Reason:** the database accepts infeasible bookings: active bookings on a broken dock (Data Q-04), over the weight limit (Q-06), ending before the truck arrives (Q-08); and the availability view ignores dock events (Q-05).
- **Evidence, the written check run on three shipments (Data; standard query in the build, re-run by the feasibility code in build step 3):**

| Shipment | All Jaipur slots | View says AVAILABLE | Dock type | Weight | No dock event | After ETA + margin | Before 21:00 (RULE005) | Result |
|---|---|---|---|---|---|---|---|---|
| SHP1015 reefer 15,000 kg, ETA 18:30 HIGH | 79 | 58 | 8 | 8 | 8 | **0** | 0 | **No slot: escalate** |
| SHP1010 reefer 16,000 kg, ETA 10:55 HIGH | 79 | 58 | 8 | 8 | 8 | 5 | 5 | D5 12:00 to 16:00 |
| SHP1013 standard 14,000 kg, ETA 11:00 LOW | 79 | 58 | 42 | 42 | 42 | 37 | 37 | First options 12:00 |

Not yet applied in this table: unload overrun beyond the slot (Q-09), driver's latest finish, live holds, priority protection. The code adds them.
- **Revisit if:** the planner supplies real unload durations or a buffer rule.

### D-05 Meaning of "available" while another driver decides (brief 5)
- **Chosen:** availability belongs to (slot, shipment, moment), never to the slot alone. A slot is available to a shipment when all D-04 checks pass **and** no other thread holds it. State needed: slot status, active appointment, live hold (owner, expiry), dock events, the offer record, the resolved ETA.
- **Evidence:** the schema has no "held" state (Data Q-21, I-11), so today two readers both see the same slot as AVAILABLE in `v_slot_availability` (Mechanism M1). Pending warehouse confirmations APT1013A and APT1014A have no expiry (Data Q-16).

### D-06 Option, hold, request, reservation, confirmed booking (brief 6)
- **Chosen:** SHOWN (offer recorded, nothing reserved), ACTIVE hold (exclusive, 5-minute expiry), PENDING_APPROVAL (needs a person), CONFIRMED (appointment committed). No separate "reserved".

| State | Who moves it | What the driver sees |
|---|---|---|
| SHOWN | `get_feasible_slots` (code) | "Here are options. Nothing is reserved yet." |
| ACTIVE hold | `hold_slot`, after the driver picks | "I have held 12:00 at D5 until 11:47. Reply YES to confirm." |
| PENDING_APPROVAL | `confirm_booking` when a rule needs a person | "A coordinator must approve this. You will hear by ..." |
| CONFIRMED | `confirm_booking`, after the commit | "Confirmed: 12:00, D5. Your old booking is released." |
| Expired, released, refused | clock, driver, re-check | "That hold has ended. Here are the current options." |

- **Options rejected:** hold on show (35 browsing drivers would lock the day); no holds (the second driver loses after saying yes).
- **Hold time:** 5 minutes (**Assumption**, owner warehouse planner).
- **Evidence:** the seed's own agent already separates them: "warehouse confirmation is still pending. I will not treat it as confirmed" (THR004, Data). Tested by the stale-option and expiry tests (**Test**, T-03: passed; `test_stale_option_refused_at_confirm`, `test_expired_hold_is_not_trusted`).
- **Revisit if:** holds expire often or utilisation drops.

### D-07 Ordering simultaneous requests (brief 7)
- **Chosen:** policy P-1 to P-5 (section 9.6): a confirmed promise is never taken back automatically; first hold wins; the last compatible slot of a scarce type is kept for CRITICAL loads; pre-emption or a policy conflict goes to a person; in a queue, order by priority, then earliest latest-finish, then arrival, with ageing.
- **What a losing carrier is told:** "Another truck confirmed this slot first. Here is what is still open." If P-3 hid a slot: "That slot is kept for time-critical loads."
- **Evidence:** the seed's competing set: SHP1006 (HIGH, ETA 11:20), SHP1012 (NORMAL, 11:10), SHP1013 (NORMAL, 11:00 LOW), SHP1014 (CRITICAL, 11:25), and SHP1009 (CRITICAL, 10:50) (Data, database guide). Replay result (**Test**, T-11, `docs/competing_trucks.md`): 0 policy violations in both replays. Finding: at XS tier simultaneous requests are first-hold-wins, so a NORMAL load can beat a CRITICAL one; P-5 ordering applies only with the pilot queue (CHG-009). **Owner of the policy:** operations head.
- **Revisit if:** the owner supplies a different policy.

### D-08 Facility recalculation (optional, brief 8)
- **Chosen:** a dispatch rule as a read-only tool. Recalculate on a new ETA, a dock event or a cancellation. Fixed: trucks in a dock (SHP1002 IN_PROGRESS) and confirmed promises unless a person agrees. Objective in plain words: less waiting, fewer missed appointments, fewer changes to promises already given. CP-SAT only with a reason.
- **Evidence:** one replay with SHP1002 (in dock, overran), SHP1003 (early, waiting), SHP1004 (late, waiting), SHP1005 (waiting, dock broke) against first-come-first-served (**Test**, optional: **not attempted yet**).

### D-09 Stale options, cancellations, duplicates, retries (brief 9)
- **Chosen:** re-check at hold and at confirm; offers recorded; an idempotency key on every write; inbound message key (thread + external id + text hash); cancel-old and create-new in one transaction; the reply is built only after the commit.
- **Evidence, one replayed case each (Test, T-03 to T-05):**
  - Results: all passed (`test_duplicate_message_acts_once`, `test_stale_option_refused_at_confirm`, `test_failure_mid_commit_leaves_no_half_state`, `test_cancelled_shipment_gets_nothing`).
  - Duplicate: THR009 repeats THR001's message (MSG015, `is_duplicate` = 1), and today it created a second exception with the same dedupe key (EXC001, EXC009; Data Q-12). Replay: one action.
  - Stale option: offer a slot, block it, then accept: refused with new options.
  - Cancellation: APT1008 was cancelled and freed SLOT-JAI-017 (Data). Replay rebooking with a forced failure between writes: nothing half-done.
  - Cancelled shipment: THR012 asks about SHP1019 (cancelled, Data Q-15): no options offered.

### D-10 No feasible slot (brief 10)
- **Chosen:** escalate with a complete hand-off record; never invent a slot (invariant 7).
- **Evidence:** SHP1015 has 0 feasible slots (Data Q-19, D-04 table). Today's escalation, OM004, **FAILED** to deliver, and APT1015A still shows CONFIRMED for 17:00 to 18:00, a slot the truck cannot reach (Data Q-08, Q-17). So the hand-off is stored in our own table and shown to a coordinator, not only emailed. Message and record fields in section 9.9.

### D-11 Preferred slot not granted (brief 11)
- **Chosen:** every refusal names the reason and offers a next step. Two messages, with real data:
  1. Slot taken: "Sorry, 12:00 at Dock 2 was just confirmed for another truck before I could book it. I have not changed your booking. The next options are 13:00 at Dock 2 or 13:00 at Dock 4."
  2. Dock type: "I cannot offer Dock 3 because your load is refrigerated, and only Dock 5 takes refrigerated loads. Dock 5 is closed for maintenance from 6 PM, so I have asked a coordinator to call you with options."

### D-12 What needs a person (brief 12)
- **Chosen:** nine triggers (section 9.9): safety cue; no feasible slot; option beyond the approval threshold (another day, more than 3 hours after plan, or a start after 21:00, RULE005); pre-empting a booking or a policy conflict; contradictory data (for example a booking on a broken dock, Data Q-04); money, penalties, disputes; regulated load or emergency; two failed clarifications; model, tool or budget failure. Each has a type (approve, review, take over), an owner and a target time.
- **Evidence:** the hand-off target must exist: CON005 (Gurugram night shift) is "Vacant Position" and OM004 went to an address not in `facility_contacts` (Data Q-18, Q-17).

### D-13 Proving no double booking (brief 13)
- **Chosen:** ten threads, each with its own connection, try to confirm the same slot at once; exactly one succeeds; repeat 100 times; an SQL check shows at most one active booking per slot; a control run with the protection switched off does double-book (so the test can fail); and the losing driver is never told "confirmed".
- **Evidence:** the database's own index `ux_active_appointment_per_slot` already holds on the snapshot (Data Q-03, 0 rows). Concurrency result (**Test**, T-01, `docs/integrity_proof.txt`): 1,000 requests, 100 bookings, 0 double bookings over 100 repeats; control without lock and index: 900 double bookings; control without lock but with the index: 0 double bookings but 900 database errors (the code must not rely on the index alone).

## Architecture decisions

### D-14 Tier and orchestration
- **Options:** A rules-first workflow, B single agent with stage-gated tools, C multi-agent.
- **Chosen:** B on an A-shaped spine, tier XS.
- **Reason:** A 420, B 425, C 335 of 500 (`03_option_scoring.py`): a near tie between A and B. B chosen for the brief's conversation needs; A remains the fallback on the same tools.
- **Revisit if:** more than 1 in 5 turns picks a wrong tool (switch to A); a second team needs its own agent (C).

### D-15 Source of truth when systems disagree
- **Chosen (default):** committed appointments and slots: dock scheduler; arrival: gate check-in; ETA: the D-03 rule; dock usability: dock events override slot status (Data Q-05). A disagreement raises a review hand-off. **Owner:** operations head.

### D-16 Data layer
- **Chosen:** new tables only (the client's tables stay as they are), SQLite WAL, foreign keys switched on for every connection (they are off by default, Data Q-00b), `BEGIN IMMEDIATE` writes, epoch-number time columns, a partial unique index on live holds, an append-only audit table. Postgres with an exclusion constraint for a pilot.
- **Evidence:** Data Q-00, Q-00b, Q-21; Mechanisms M2, M3.

### D-17 Model route
- **Options:** hosted model via an API key; local open-weight model; both behind one adapter.
- **Chosen:** one adapter over an OpenAI-style chat API with two settings: **Ollama** (local, free, for development) and **OpenRouter** (hosted, for the final recording if the local model's tool calling is unreliable). The model used is named in the README. No model decides capacity, ranking or commit.
- **Reason:** no paid Claude key in this project; OpenRouter key available; Ollama installed.
- **Evidence:** scenario run on `anthropic/claude-haiku-5.5` (**Test**): 14 model calls, about 35,000 tokens in and 2,250 out for 6 driver messages (about 2,500 in per call). Still to copy into `03_cost_estimate.xlsx`.
- **Revisit if:** tool-calling errors exceed 1 in 5 turns on both routes (fall back to option A).

### D-18 Observability
- **Chosen:** our own audit table is the record; LangSmith free tier optional, used only on non-personal data.

### D-19 What is not used
- **No RAG** (rules are 6 structured rows, Data Q-20), **no ML** (no GPS or gate-in history), **no queue** at XS. **Revisit if** rules become long documents, history exists, or load exceeds one writer.
