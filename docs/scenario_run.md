# Scenario run: driver delays on the real SetuHaul snapshot

- Generated: 2026-11-27T17:40:42
- Model route: `openrouter`; model: `anthropic/claude-haiku-5.5`
- Database: fresh copy of `data/setuhaul_original.db` (`work_scenario.db`), scenario clock in India time
- Phones are masked before any log, checkpoint or model call. Tool calls and final state are what the tests assert on; wording may differ between runs.

## Case 1: SHP1013, vague delay, clarify, rebook

Driver signs in with phone `******0013` -> session for `DRV013`.

**10:00 Driver:** Late

- tool `resolve_shipment` {} -> **UNIQUE** (stage CLARIFY)

**Agent** (stage CLARIFY): Thanks. Your shipment is SHP1013, with a planned arrival of 10:00. When do you expect to reach the gate? If it's a number of minutes, tell me whether that means minutes later than planned or repair time.

**10:01 Driver:** I will reach the gate at 11:40

- tool `record_eta_declaration` {"shipment_id": "SHP1013", "kind": "CLOCK_TIME", "clock_time": "11:40"} -> **RECORDED** (stage OFFER)
- tool `get_feasible_slots` {"shipment_id": "SHP1013"} -> **OPTIONS** (stage OFFER)

**Agent** (stage OFFER): I've noted your arrival at the gate as 11:40. Nothing is reserved yet. These slots are available:

1. D1, 13:00 to 14:00
2. D2, 13:00 to 14:00
3. D3, 13:00 to 14:00

Which one would you like to hold?

**10:02 Driver:** 1

- tool `hold_slot` {"offer_id": "OFF-bc6f8efe08"} -> **HELD** (stage HOLD)

**Agent** (stage HOLD): Dock D1, 13:00 to 14:00, is HELD for you, but not booked yet. The hold lasts until 10:07. Please reply YES to confirm this slot.

**10:03 Driver:** yes

- tool `confirm_booking` {"hold_id": "HOLD-6627f5956b"} -> **CONFIRMED** (stage DONE)

**Agent** (stage DONE): Your booking is confirmed for dock D1, 13:00 to 14:00. Your previous appointment has been replaced.

## Case 2: SHP1015, reefer with no feasible slot, escalation

Driver signs in with phone `******0015` -> session for `DRV015`.

**16:30 Driver:** SHP1015 reefer is delayed, I will reach Jaipur at 18:30. Any slot?

- tool `resolve_shipment` {"hint": "SHP1015"} -> **UNIQUE** (stage CLARIFY)
- tool `get_shipment_context` {"shipment_id": "SHP1015"} -> **OK** (stage CLARIFY)
- tool `record_eta_declaration` {"shipment_id": "SHP1015", "kind": "CLOCK_TIME", "clock_time": "18:30"} -> **RECORDED** (stage OFFER)
- tool `get_feasible_slots` {"shipment_id": "SHP1015", "limit": 3} -> **NO_FEASIBLE_SLOT** (stage ESCALATE)

**Agent** (stage ESCALATE): Thanks, I've recorded your ETA as 18:30 for SHP1015. Unfortunately, no safe automatic reschedule slot is available right now, so I've alerted a warehouse coordinator. They will contact you by 16:45, and your current appointment (dock D5, 17:00–18:00) is unchanged for now.

**16:31 Driver:** Is there anything at all tonight?


**Agent** (stage ESCALATE): A coordinator has your case and will contact you by 16:45. I will not change anything in the meantime.

## Final database state

### Appointments for the two shipments

| appointment | shipment | slot | dock | start | status | current | replaces |
|---|---|---|---|---|---|---|---|
| APT1013A | SHP1013 | SLOT-JAI-018 | D2 | 11:00 | CANCELLED | 0 |  |
| APT-5b1861a476 | SHP1013 | SLOT-JAI-006 | D1 | 13:00 | CONFIRMED | 1 | APT1013A |
| APT1015A | SHP1015 | SLOT-JAI-066 | D5 | 17:00 | CONFIRMED | 1 |  |

### Holds

| hold | slot | shipment | state |
|---|---|---|---|
| HOLD-6627f5956b | SLOT-JAI-006 | SHP1013 | CONFIRMED |

### Hand-offs (the escalation)

- **HO-7a411d8b** reason `NO_FEASIBLE_SLOT`, shipment SHP1015, driver `DRV015`, owner CON001 (WAREHOUSE_COORDINATOR), created 16:30, deadline 16:45, missing fields: none
  - summary: `{"what_driver_said": "SHP1015 reefer is delayed, I will reach Jaipur at 18:30. Any slot?", "why": "No slot passes every check", "reason_counts": {"DOCK_TYPE": 65, "TOO_EARLY": 63, "TAKEN": 13, "DOCK_DOWN": 10, "SLOT_BLOCKED": 7, "CURRENT_BOOKING": 1}}`
  - state read: `{"eta": "18:30", "eta_source": "DRIVER_CONFIRMED_IN_CHAT", "eta_confidence": "MEDIUM", "margin_min": 30, "current_appointment": {"appointment_id": "APT1015A", "appointment_status": "CONFIRMED", "dock_code": "D5", "slot_start_ts": "2026-08-04T17:00:00+05:30", "slot_end_ts": "2026-08-04T18:00:00+05:30"}, "reason_counts": {"DOCK_TYPE": 65, "TOO_EARLY": 63, "TAKEN": 13, "DOCK_DOWN": 10, "SLOT_BLOCKED": 7, "CURRENT_BOOKING": 1}}`
  - options shown: `[]`; not done: `["No slot offered", "Existing booking not changed", "No priority override attempted"]`

### Checks

- Escalations: **1** (NO_FEASIBLE_SLOT)
- Slots with more than one live booking: **0**
- Audit events: TURN 6, ETA_DECLARED 2, HOLD_PLACED 1, HANDOFF_CREATED 1, CONFIRMED 1
- Turns: 6; model calls: 14; tokens in/out: 35166/2246
