-- =====================================================================
-- SetuHaul Logistics: audit queries for the Problem Definition Sheet
-- STATUS: RUN on the SYNTHETIC database dummy/dummy_setuhaul.db only.
-- NOT RUN on the real SetuHaul snapshot (not supplied). Results on dummy
-- data show the queries work; they are NOT findings about the client.
-- Column names are INFERRED from the brief's ER diagram (page 7) and match
-- the dummy schema. On the real DB, check names with .schema first and
-- fix anything marked [GUESS] (status values especially).
-- Run with:  python3 dummy/run_audit.py <db> 01_audit_queries.sql
--        or: sqlite3 setuhaul.db < 01_audit_queries.sql
-- Rule: an issue in the sheet is "Confirmed" only after its query
-- has run and the result is pasted into section 6.
-- =====================================================================

.headers on
.mode column

-- ---------- Q-00: schema and enforced constraints ----------
-- Proves which rules the DB really enforces (brief says 2 partial unique indexes).
SELECT type, name, tbl_name, sql FROM sqlite_master
WHERE type IN ('index','trigger','view') AND name NOT LIKE 'sqlite_%';

PRAGMA foreign_keys;          -- 0 means FKs are declared but NOT enforced

-- ---------- Q-01: inventory (row counts) ----------
SELECT 'carriers' t, COUNT(*) n FROM carriers UNION ALL
SELECT 'drivers', COUNT(*) FROM drivers UNION ALL
SELECT 'vehicle_types', COUNT(*) FROM vehicle_types UNION ALL
SELECT 'vehicles', COUNT(*) FROM vehicles UNION ALL
SELECT 'shipments', COUNT(*) FROM shipments UNION ALL
SELECT 'eta_updates', COUNT(*) FROM eta_updates UNION ALL
SELECT 'facilities', COUNT(*) FROM facilities UNION ALL
SELECT 'docks', COUNT(*) FROM docks UNION ALL
SELECT 'facility_rules', COUNT(*) FROM facility_rules UNION ALL
SELECT 'appointment_slots', COUNT(*) FROM appointment_slots UNION ALL
SELECT 'appointments', COUNT(*) FROM appointments UNION ALL
SELECT 'dock_status_events', COUNT(*) FROM dock_status_events UNION ALL
SELECT 'facility_checkins', COUNT(*) FROM facility_checkins UNION ALL
SELECT 'chat_threads', COUNT(*) FROM chat_threads UNION ALL
SELECT 'chat_messages', COUNT(*) FROM chat_messages UNION ALL
SELECT 'driver_exceptions', COUNT(*) FROM driver_exceptions UNION ALL
SELECT 'operational_messages', COUNT(*) FROM operational_messages UNION ALL
SELECT 'facility_contacts', COUNT(*) FROM facility_contacts;
-- Brief claims: 4,15,5,15,21,12 | 2,9,6,106,20,3 | 5,12,20,10,5,5 (total 275)

-- ---------- Q-02: time zone and format consistency ----------
-- I-01: mixed offsets or formats across timestamp columns
SELECT 'shipments.original_eta_ts' col, substr(original_eta_ts, 20) tail, COUNT(*) n
  FROM shipments GROUP BY 2
UNION ALL SELECT 'shipments.latest_eta_ts', substr(latest_eta_ts, 20), COUNT(*) FROM shipments GROUP BY 2
UNION ALL SELECT 'eta_updates.declared_eta_ts', substr(declared_eta_ts, 20), COUNT(*) FROM eta_updates GROUP BY 2
UNION ALL SELECT 'appointment_slots.slot_start_ts', substr(slot_start_ts, 20), COUNT(*) FROM appointment_slots GROUP BY 2
UNION ALL SELECT 'facility_checkins.gate_in_ts', substr(gate_in_ts, 20), COUNT(*) FROM facility_checkins GROUP BY 2
UNION ALL SELECT 'chat_messages.message_ts', substr(message_ts, 20), COUNT(*) FROM chat_messages GROUP BY 2;
-- Expect '+05:30' everywhere. Anything else is an issue.

-- Snapshot bounds: what is the newest timestamp anywhere?
SELECT MIN(message_ts) first_msg, MAX(message_ts) last_msg FROM chat_messages;

-- ---------- Q-03: NULLs in required values ----------
-- I-02
SELECT shipment_id,
       (carrier_id IS NULL) no_carrier, (driver_id IS NULL) no_driver,
       (vehicle_id IS NULL) no_vehicle, (destination_facility_id IS NULL) no_dest,
       (original_eta_ts IS NULL) no_orig_eta, (latest_eta_ts IS NULL) no_latest_eta,
       (required_dock_type IS NULL) no_dock_type, (priority_code IS NULL) no_priority,
       (current_status IS NULL) no_status
FROM shipments
WHERE carrier_id IS NULL OR driver_id IS NULL OR vehicle_id IS NULL
   OR destination_facility_id IS NULL OR original_eta_ts IS NULL OR latest_eta_ts IS NULL
   OR required_dock_type IS NULL OR priority_code IS NULL OR current_status IS NULL;

-- ---------- Q-04: orphans ----------
-- I-03
SELECT 'appointments->slots' rel, a.appointment_id id FROM appointments a
  LEFT JOIN appointment_slots s ON s.slot_id = a.slot_id WHERE s.slot_id IS NULL
UNION ALL SELECT 'appointments->shipments', a.appointment_id FROM appointments a
  LEFT JOIN shipments sh ON sh.shipment_id = a.shipment_id WHERE sh.shipment_id IS NULL
UNION ALL SELECT 'shipments->drivers', sh.shipment_id FROM shipments sh
  LEFT JOIN drivers d ON d.driver_id = sh.driver_id WHERE sh.driver_id IS NOT NULL AND d.driver_id IS NULL
UNION ALL SELECT 'shipments->vehicles', sh.shipment_id FROM shipments sh
  LEFT JOIN vehicles v ON v.vehicle_id = sh.vehicle_id WHERE sh.vehicle_id IS NOT NULL AND v.vehicle_id IS NULL
UNION ALL SELECT 'chat_threads->shipments', t.thread_id FROM chat_threads t
  LEFT JOIN shipments sh ON sh.shipment_id = t.shipment_id WHERE t.shipment_id IS NOT NULL AND sh.shipment_id IS NULL
UNION ALL SELECT 'chat_messages->threads', m.chat_message_id FROM chat_messages m
  LEFT JOIN chat_threads t ON t.thread_id = m.thread_id WHERE t.thread_id IS NULL
UNION ALL SELECT 'checkins->shipments', c.checkin_id FROM facility_checkins c
  LEFT JOIN shipments sh ON sh.shipment_id = c.shipment_id WHERE sh.shipment_id IS NULL;

-- ---------- Q-05: do the two enforced rules hold? ----------
-- I-04 (control check, expected 0 rows)
SELECT slot_id, COUNT(*) active_n FROM appointments
WHERE appointment_status NOT IN ('cancelled','no_show','replaced')  -- 'active' = anything else; see Q-18
GROUP BY slot_id HAVING COUNT(*) > 1;
SELECT shipment_id, COUNT(*) current_n FROM appointments
WHERE is_current = 1 AND appointment_status NOT IN ('cancelled','no_show','replaced')
GROUP BY shipment_id HAVING COUNT(*) > 1;

-- ---------- Q-06: booked slot on a dock that is broken or in maintenance ----------
-- I-05: appointment active while dock_status_events says the dock is unusable
SELECT a.appointment_id, a.shipment_id, d.dock_code, a.appointment_status,
       s.slot_start_ts, s.slot_end_ts, e.event_type, e.event_start_ts, e.event_end_ts
FROM appointments a
JOIN appointment_slots s ON s.slot_id = a.slot_id
JOIN docks d ON d.dock_id = s.dock_id
JOIN dock_status_events e ON e.dock_id = d.dock_id
WHERE a.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND julianday(s.slot_start_ts) < julianday(e.event_end_ts)
  AND julianday(e.event_start_ts) < julianday(s.slot_end_ts);   -- time overlap

-- ---------- Q-07: appointment on a slot that is not open/booked ----------
-- I-06
SELECT a.appointment_id, a.appointment_status, s.slot_id, s.slot_status
FROM appointments a JOIN appointment_slots s ON s.slot_id = a.slot_id
WHERE a.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND s.slot_status IN ('blocked','maintenance','breakdown');

-- ---------- Q-08: dock type incompatible with load ----------
-- I-07: reefer/heavy shipment booked on the wrong dock type
SELECT a.appointment_id, sh.shipment_id, sh.required_dock_type, d.dock_code, d.dock_type
FROM appointments a
JOIN shipments sh ON sh.shipment_id = a.shipment_id
JOIN appointment_slots s ON s.slot_id = a.slot_id
JOIN docks d ON d.dock_id = s.dock_id
WHERE a.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND sh.required_dock_type <> d.dock_type;

-- ---------- Q-09: slot outside facility opening hours ----------
-- I-08 (also check facility_rules for clashes, Q-17)
SELECT s.slot_id, f.facility_name, f.open_time, f.close_time, s.slot_start_ts, s.slot_end_ts
FROM appointment_slots s JOIN facilities f ON f.facility_id = s.facility_id
WHERE substr(s.slot_start_ts,12,5) < f.open_time
   OR substr(s.slot_end_ts,12,5)   > f.close_time;
-- Compares LOCAL clock text (HH:MM). Do not use time() here: it converts +05:30 to UTC.

-- ---------- Q-10: overlapping slots on the same dock ----------
-- I-09: unique index protects slot_id, not time overlap between different slots
SELECT s1.slot_id a, s2.slot_id b, s1.dock_id, s1.slot_start_ts, s1.slot_end_ts, s2.slot_start_ts, s2.slot_end_ts
FROM appointment_slots s1 JOIN appointment_slots s2
  ON s1.dock_id = s2.dock_id AND s1.slot_id < s2.slot_id
 AND s1.slot_start_ts < s2.slot_end_ts AND s2.slot_start_ts < s1.slot_end_ts;

-- ---------- Q-11: appointment earlier than the truck's latest ETA ----------
-- I-10: promise already unreachable
SELECT a.appointment_id, sh.shipment_id, sh.latest_eta_ts, s.slot_start_ts, s.slot_end_ts
FROM appointments a
JOIN shipments sh ON sh.shipment_id = a.shipment_id
JOIN appointment_slots s ON s.slot_id = a.slot_id
WHERE a.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND julianday(sh.latest_eta_ts) > julianday(s.slot_end_ts);

-- ---------- Q-12: conflicting ETA sources ----------
-- I-11: more than one ETA per shipment, and shipments.latest_eta_ts vs v_latest_eta
SELECT shipment_id, COUNT(*) n_updates, COUNT(DISTINCT declared_eta_ts) distinct_etas,
       GROUP_CONCAT(DISTINCT source_type) sources
FROM eta_updates GROUP BY shipment_id HAVING COUNT(*) > 1;

SELECT sh.shipment_id, sh.latest_eta_ts AS shipments_latest, v.latest_eta_ts AS view_latest, v.source_type
FROM shipments sh JOIN v_latest_eta v ON v.shipment_id = sh.shipment_id
WHERE datetime(sh.latest_eta_ts) <> datetime(v.latest_eta_ts);   -- datetime() normalises +05:30 and Z to UTC
-- Rows here = shipments.latest_eta_ts disagrees with the newest declared ETA.

SELECT source_type, confidence_code, COUNT(*) FROM eta_updates GROUP BY 1,2;  -- what confidence labels exist?

-- ---------- Q-13: status contradictions ----------
-- I-12
-- (a) cancelled/no-show appointment but a gate check-in exists
SELECT a.appointment_id, a.appointment_status, c.checkin_id, c.gate_in_ts
FROM appointments a JOIN facility_checkins c ON c.shipment_id = a.shipment_id
WHERE a.appointment_status IN ('cancelled','no_show');
-- (b) shipment completed/unloading with no check-in
SELECT sh.shipment_id, sh.current_status FROM shipments sh
LEFT JOIN facility_checkins c ON c.shipment_id = sh.shipment_id
WHERE sh.current_status IN ('completed','unloading') AND c.checkin_id IS NULL;
-- (c) check-in at a dock different from the booked dock
SELECT c.shipment_id, c.actual_dock_id, s.dock_id AS booked_dock
FROM facility_checkins c
JOIN appointments a ON a.shipment_id = c.shipment_id AND a.is_current = 1
JOIN appointment_slots s ON s.slot_id = a.slot_id
WHERE c.actual_dock_id <> s.dock_id;

-- ---------- Q-14: duplicate chat messages ----------
-- I-13
SELECT thread_id, sender_type, message_text, COUNT(*) n, MIN(message_ts) first_ts, MAX(message_ts) last_ts
FROM chat_messages GROUP BY thread_id, sender_type, message_text HAVING COUNT(*) > 1;
SELECT is_duplicate, COUNT(*) FROM chat_messages GROUP BY is_duplicate;

-- ---------- Q-15: conversation-to-shipment ambiguity ----------
-- I-14: drivers with several shipments / several open threads; threads with no shipment
SELECT driver_id, COUNT(*) active_shipments FROM shipments
WHERE current_status NOT IN ('completed','cancelled') GROUP BY driver_id HAVING COUNT(*) > 1;
SELECT driver_id, COUNT(*) open_threads FROM chat_threads
WHERE thread_status = 'open' GROUP BY driver_id HAVING COUNT(*) > 1;
SELECT thread_id, driver_id FROM chat_threads WHERE shipment_id IS NULL;

-- ---------- Q-16: exceptions without a usable link ----------
-- I-15
SELECT exception_id, shipment_id, thread_id, declared_eta_ts, exception_status
FROM driver_exceptions
WHERE thread_id IS NULL OR declared_eta_ts IS NULL OR shipment_id IS NULL;

-- ---------- Q-17: facility rules (read by a human) ----------
-- I-16: rule clashes (the brief names RULE005 in the ladder)
SELECT * FROM facility_rules;
SELECT * FROM docks;

-- ---------- Q-18: the status vocabulary (gaps the constraints do NOT cover) ----------
-- I-17: is there a state for "held while the driver decides"?
SELECT 'slot_status' k, slot_status v, COUNT(*) n FROM appointment_slots GROUP BY 2
UNION ALL SELECT 'appointment_status', appointment_status, COUNT(*) FROM appointments GROUP BY 2
UNION ALL SELECT 'shipment_status', current_status, COUNT(*) FROM shipments GROUP BY 2
UNION ALL SELECT 'priority_code', priority_code, COUNT(*) FROM shipments GROUP BY 2
UNION ALL SELECT 'queue_state', queue_state, COUNT(*) FROM facility_checkins GROUP BY 2
UNION ALL SELECT 'thread_status', thread_status, COUNT(*) FROM chat_threads GROUP BY 2
UNION ALL SELECT 'thread_intent', thread_intent, COUNT(*) FROM chat_threads GROUP BY 2
UNION ALL SELECT 'dock_status', dock_status, COUNT(*) FROM docks GROUP BY 2;

-- ---------- Q-19: do the views agree with the base tables? ----------
-- I-18: a slot shown as available that already has an active appointment
-- (a) shown available but an active appointment exists
SELECT v.slot_id, a.appointment_id, a.appointment_status
FROM v_slot_availability v JOIN appointments a ON a.slot_id = v.slot_id
WHERE v.is_available = 1 AND a.appointment_status NOT IN ('cancelled','no_show','replaced');
-- (b) shown available while a dock event (breakdown/maintenance/block) overlaps the slot
SELECT v.slot_id, e.event_type, e.event_start_ts, e.event_end_ts
FROM v_slot_availability v JOIN dock_status_events e ON e.dock_id = v.dock_id
WHERE v.is_available = 1
  AND julianday(v.slot_start_ts) < julianday(e.event_end_ts)
  AND julianday(e.event_start_ts) < julianday(v.slot_end_ts);

-- ---------- Q-20: personal data exposure (privacy lens) ----------
-- I-19: phone numbers or locations stored/duplicated in free text
SELECT COUNT(*) phones_in_drivers FROM drivers WHERE phone IS NOT NULL;
SELECT chat_message_id FROM chat_messages
WHERE message_text GLOB '*[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*';             -- 10+ digits in a row
SELECT * FROM facility_contacts;
SELECT * FROM operational_messages;

-- ---------- Q-21: sample driver messages for the "ask vs look up" read ----------
-- Used in sheet section 4 for THR003, THR010, THR011.
SELECT t.thread_id, t.shipment_id, t.thread_intent, m.sender_type, m.message_ts, m.message_text
FROM chat_threads t JOIN chat_messages m ON m.thread_id = t.thread_id
WHERE t.thread_id IN ('THR003','THR010','THR011')
ORDER BY t.thread_id, m.message_ts;
