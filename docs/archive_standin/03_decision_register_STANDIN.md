# Decision register: SetuHaul driver-delay service

**Written:** 25 November 2026 | Evidence labels: Brief-stated, Mechanism (proven in step 2), Stand-in (seen on the synthetic database only), Assumption. Nothing here is proven on SetuHaul data (steps 1 and 2 gates are still FAIL).
Each entry: options, chosen, reason, evidence, consequences, revisit trigger. Section numbers point to `03_architecture.md`.

## Brief decisions 1 to 13

### D-01 What to collect before showing options (brief 1)
- **Options:** ask for everything up front; ask only what the backend lacks; show options first and ask later.
- **Chosen:** ask only for missing facts: which load (only if more than one), the **total arrival time** and what the delay means (arrival delay or repair time), the latest time they can finish unloading, and whether they want options or a booking. Never ask for appointment, priority, dock type or arrival state.
- **Reason:** asking for backend facts wastes the driver's time; trusting the driver over the backend risks a wrong promise (brief p.3). Measure M-11.
- **Evidence (three stand-in chats):** THR003 "Late" (SHP1013): missing delay size, reason and arrival time. THR010 "Late hoon, call me on ..." (DRV004, no shipment): missing which load. THR011 "Show me options after 12, don't book yet." (SHP1017): nothing missing, options only, nothing reserved.
- **Consequences:** two to three questions at most per case.
- **Revisit if:** the scenario run shows average clarification turns above 3.

### D-02 Linking a conversation to driver, shipment and appointment (brief 2)
- **Options:** trust the thread's shipment link; trust the text; derive from channel identity and confirm.
- **Chosen:** driver from channel identity; candidates from active shipments of that driver; ask if more than one; verify ownership.
- **Reason:** a thread link is optional (THR010 has none) and drivers can hold two loads (C7).
- **Evidence, trace for THR010 (stand-in):** MSG014 from DRV004 at 09:35 -> `drivers.phone` match -> `shipments` where driver = DRV004: SHP1004 (in transit, Jaipur, P3, appointment APT1004 on D2 at 09:00) and SHP1021 (planned, Bhiwandi, P3, 09:00) -> two rows -> AMBIGUOUS -> ask which load. Also THR011's driver (DRV007) is not SHP1017's assigned driver (DRV010) -> MISMATCH -> refuse and review.
- **Consequences:** one extra question for multi-load drivers.
- **Revisit if:** the real channel cannot give a trustworthy identity.

### D-03 Revised ETA and how sure we are (brief 3)
- **Options:** latest timestamp wins; plan time; rule with source, confidence and margin.
- **Chosen:** section 9.4 (override > driver confirmed in chat > later of newest driver and warehouse; margin 15, 30, 60 minutes by confidence; kind kept; one time zone).
- **Reason:** "latest wins" picks SHP1013's low-confidence warehouse ETA (stand-in); a `Z` time compares wrongly as text (Mechanism M4).
- **Evidence:** the rule applied to THR003 and to the brief's tyre message (section 9.4).
- **Consequences:** margins are assumptions; offers are slightly conservative.
- **Revisit if:** gate-in history shows margins too large or small.

### D-04 What makes a slot feasible (brief 4)
- **Chosen:** ten ordered checks with reason codes (section 9.5), one function used when showing, holding and confirming.
- **Reason:** the database accepts infeasible bookings (Mechanism M2); an empty row is not feasibility.
- **Evidence:** run on SHP1015 (11 -> 0), SHP1010 (54 -> 6), SHP1013 (about 50 to 54 -> 35 to 38), stand-in upper bounds.
- **Revisit if:** the planner supplies unload durations or clarifies reduced capacity and buffer.

### D-05 Meaning of "available" while another driver decides (brief 5)
- **Chosen:** availability belongs to (slot, shipment, moment), never to the slot alone. State needed: slot status, live hold, offer record, resolved ETA id.
- **Evidence:** Mechanism M1: two readers both saw "free".

### D-06 Option, hold, request, reservation, confirmed booking (brief 6)
- **Chosen:** SHOWN (no reservation), ACTIVE hold (exclusive, expiring), PENDING_APPROVAL, CONFIRMED. No separate "reserved".
- **Options rejected:** hold on show (35 browsing drivers would lock the day, E13); no holds (second driver loses after saying yes).
- **Hold time:** 5 minutes (Assumption, owner warehouse planner). **Revisit if** utilisation (M-8) drops or holds expire often.
- **Evidence:** states table in section 9.2; tested by the stale-option and expiry tests.

### D-07 Ordering simultaneous requests (brief 7)
- **Chosen:** policy P-1 to P-5 (section 9.6): promises never taken back, first hold wins, protected last slot for P1, pre-emption to a person, priority queue with ageing in the pilot.
- **What a losing carrier is told:** "Another truck confirmed this slot first. Here is what is still open." If P-3 hid a slot: "That slot is kept for time-critical loads."
- **Evidence needed:** replay on SHP1006, SHP1012, SHP1013, SHP1014, SHP1009 (build step 11). **Owner:** operations head (Q6). **Revisit if** the owner supplies a policy.

### D-08 Facility recalculation (optional, brief 8)
- **Chosen:** dispatch rule first as a read-only tool; objective: less waiting, fewer missed appointments, fewer changes to told promises; running trucks are fixed. CP-SAT only with a reason.
- **Evidence needed:** one replay with SHP1002, SHP1003, SHP1004, SHP1006 against first-come-first-served.

### D-09 Stale options, cancellations, duplicates, retries (brief 9)
- **Chosen:** re-check at hold and confirm; offers recorded; idempotency table and inbound key; cancel-old and create-new in one transaction; outbox for replies.
- **Evidence needed, one replay each:** THR009 duplicate "Take the 11 o'clock slot"; offer then block then accept; APT1008 rebooking with a forced failure between writes.

### D-10 No feasible slot (brief 10)
- **Chosen:** escalate with a complete hand-off record; never invent a slot (I-13).
- **Evidence:** SHP1015 gives 0 feasible slots (stand-in); today's escalation OM004 is one line. Message and record fields in section 9.9.

### D-11 Preferred slot not granted (brief 11)
- **Chosen:** every refusal names the reason and offers a next step. Two messages in section 9.9.

### D-12 What needs a person (brief 12)
- **Chosen:** the nine triggers in section 9.9 (safety, no slot, approval threshold, pre-emption, contradictory data, money, regulated or emergency, failed clarifications, system failure), each with type, owner and target time.

### D-13 Proving no double booking (brief 13)
- **Chosen:** ten threads confirm the same slot at once; exactly one succeeds; repeat 100 times; SQL check shows one live booking per dock-time; also a test that the losing driver is never told "confirmed".
- **Evidence:** produced in build step 4 and saved as the integrity proof.

## Architecture decisions

### D-14 Tier and orchestration
- **Options:** A rules-first workflow, B single agent with stage-gated tools, C multi-agent.
- **Chosen:** B on an A-shaped spine, tier XS.
- **Reason:** A 420, B 425, C 335 of 500: a tie between A and B (sensitivity shown in section 8). Chosen for the brief's conversation requirements; A remains the fallback.
- **Revisit if:** more than 1 in 5 turns picks a wrong tool (switch to A); a second team needs its own agent (C); outbound "you may be late" messages are wanted (idea 14).

### D-15 Source of truth when systems disagree
- **Chosen (default):** committed appointments and slots: dock scheduler; arrival: gate check-in; ETA: resolved-ETA rule; any disagreement beyond thresholds raises a review hand-off. **Owner:** operations head (U-1). **Revisit if** the owner names a winner.

### D-16 Data layer
- **Chosen:** new tables only, SQLite WAL with foreign keys on every connection, epoch-based time columns, hold partial unique index, audit append-only. Postgres with exclusion constraint for a pilot.
- **Evidence:** Mechanisms M2, M3, M4.

### D-17 Model route
- **Options:** hosted small model; local open-weight model; hosted large model only.
- **Chosen:** adapter with hosted Claude Haiku 5.5 for routine turns and Sonnet 5.5 for ambiguous ones; a local model as the free alternative.
- **Evidence:** cost workbook (about INR 2.3 per conversation at 20% Sonnet); published tool-calling test favouring Qwen3 8B and 14B locally with latency cost.
- **Revisit if:** your answers to questions 1 and 2 change the route.

### D-18 Observability
- **Chosen:** own audit table as the record; LangSmith free tier or Phoenix optional, synthetic data only.

### D-19 What is not used
- **No RAG** (rules are structured), **no ML** (no GPS or history), **no queue** at XS. **Revisit if** rules become long documents, gate-in history exists, or load exceeds one writer.
