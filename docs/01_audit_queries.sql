-- =====================================================================
-- SetuHaul Logistics: data audit queries (REAL client snapshot)
-- Database: setuhaul_freight_operations.db (snapshot 4 Aug 2026, +05:30)
-- Run:      python run_audit.py            (writes docs/audit_results_REAL.txt)
-- Each query starts with "-- ---------- Q-xx: title ----------".
-- "ACTIVE" appointment = PENDING_CONFIRMATION, CONFIRMED or IN_PROGRESS
-- (the same list the database's own unique index uses).
-- Expected result is written under each query. Rows where 0 is expected
-- are a data issue; 0 rows where 0 is expected is a control that held.
-- =====================================================================

-- ---------- Q-00: which rules does the database really enforce? ----------
-- Lists the indexes and views. Expect the two partial unique indexes.
SELECT type, name, tbl_name FROM sqlite_master
WHERE type IN ('index','trigger','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name;

-- ---------- Q-00b: are foreign keys switched on for this connection? ----------
-- 0 = foreign keys are declared but NOT checked on this connection.
-- SQLite turns them off by default on every new connection; each app must switch them on.
PRAGMA foreign_keys;

-- ---------- Q-00c: do the stored rows already break a foreign key? ----------
-- Expect 0 rows.
PRAGMA foreign_key_check;

-- ---------- Q-01: row counts match the brief ----------
-- Brief: 4,15,5,15,2,9,5,6,21,12,106,20,3,5,12,20,10,5 (total 275)
SELECT 'carriers' t, COUNT(*) n FROM carriers UNION ALL
SELECT 'drivers', COUNT(*) FROM drivers UNION ALL
SELECT 'vehicle_types', COUNT(*) FROM vehicle_types UNION ALL
SELECT 'vehicles', COUNT(*) FROM vehicles UNION ALL
SELECT 'facilities', COUNT(*) FROM facilities UNION ALL
SELECT 'docks', COUNT(*) FROM docks UNION ALL
SELECT 'facility_contacts', COUNT(*) FROM facility_contacts UNION ALL
SELECT 'facility_rules', COUNT(*) FROM facility_rules UNION ALL
SELECT 'shipments', COUNT(*) FROM shipments UNION ALL
SELECT 'eta_updates', COUNT(*) FROM eta_updates UNION ALL
SELECT 'appointment_slots', COUNT(*) FROM appointment_slots UNION ALL
SELECT 'appointments', COUNT(*) FROM appointments UNION ALL
SELECT 'dock_status_events', COUNT(*) FROM dock_status_events UNION ALL
SELECT 'facility_checkins', COUNT(*) FROM facility_checkins UNION ALL
SELECT 'chat_threads', COUNT(*) FROM chat_threads UNION ALL
SELECT 'chat_messages', COUNT(*) FROM chat_messages UNION ALL
SELECT 'driver_exceptions', COUNT(*) FROM driver_exceptions UNION ALL
SELECT 'operational_messages', COUNT(*) FROM operational_messages;

-- ---------- Q-02: every timestamp uses the same +05:30 offset ----------
-- Expect only '+05:30'. Times are TEXT, so a mixed offset would break comparisons.
SELECT 'shipments.latest_eta_ts' col, substr(latest_eta_ts, 20) tail, COUNT(*) n FROM shipments GROUP BY 2
UNION ALL SELECT 'eta_updates.declared_eta_ts', substr(declared_eta_ts, 20), COUNT(*) FROM eta_updates GROUP BY 2
UNION ALL SELECT 'appointment_slots.slot_start_ts', substr(slot_start_ts, 20), COUNT(*) FROM appointment_slots GROUP BY 2
UNION ALL SELECT 'dock_status_events.event_start_ts', substr(event_start_ts, 20), COUNT(*) FROM dock_status_events GROUP BY 2
UNION ALL SELECT 'facility_checkins.gate_in_ts', substr(gate_in_ts, 20), COUNT(*) FROM facility_checkins GROUP BY 2
UNION ALL SELECT 'chat_messages.message_ts', substr(message_ts, 20), COUNT(*) FROM chat_messages GROUP BY 2;

-- ---------- Q-03: control: the one-active-booking-per-slot rule holds ----------
-- Expect 0 rows (the unique index ux_active_appointment_per_slot guarantees it).
SELECT slot_id, COUNT(*) active_n FROM appointments
WHERE appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
GROUP BY slot_id HAVING COUNT(*) > 1;

-- ---------- Q-04: active booking on a dock that is broken, in maintenance or slowed ----------
-- I-01. Expect 0 rows. A row = a promise on a dock that cannot deliver it.
SELECT a.appointment_id, a.shipment_id, d.dock_code, a.appointment_status,
       sl.slot_start_ts, sl.slot_end_ts, e.event_type, e.event_start_ts, e.event_end_ts
FROM appointments a
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
JOIN docks d ON d.dock_id = sl.dock_id
JOIN dock_status_events e ON e.dock_id = d.dock_id
WHERE a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
  AND julianday(sl.slot_start_ts) < julianday(COALESCE(e.event_end_ts, '9999-12-31'))
  AND julianday(e.event_start_ts) < julianday(sl.slot_end_ts);

-- ---------- Q-05: the availability view ignores dock events ----------
-- I-02. Expect 0 rows. v_slot_availability checks slot_status and bookings only,
-- so a slot during a breakdown can show as OCCUPIED (or AVAILABLE) instead of unusable.
SELECT v.slot_id, v.dock_code, v.slot_start_ts, v.availability_status, e.event_type, e.reason
FROM v_slot_availability v
JOIN appointment_slots sl ON sl.slot_id = v.slot_id
JOIN dock_status_events e ON e.dock_id = sl.dock_id
WHERE v.availability_status IN ('AVAILABLE','OCCUPIED')
  AND julianday(v.slot_start_ts) < julianday(COALESCE(e.event_end_ts, '9999-12-31'))
  AND julianday(e.event_start_ts) < julianday(v.slot_end_ts);

-- ---------- Q-06: load heavier than the dock allows ----------
-- I-03. Expect 0 rows. The dock type matches, but the weight limit does not.
SELECT a.appointment_id, s.shipment_id, a.appointment_status, s.load_weight_kg,
       d.dock_code, d.dock_type, d.max_vehicle_weight_kg
FROM appointments a
JOIN shipments s ON s.shipment_id = a.shipment_id
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
JOIN docks d ON d.dock_id = sl.dock_id
WHERE a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
  AND s.load_weight_kg > d.max_vehicle_weight_kg;

-- ---------- Q-07: control: dock type matches the load ----------
-- Expect 0 rows.
SELECT a.appointment_id, s.shipment_id, s.required_dock_type, d.dock_code, d.dock_type
FROM appointments a
JOIN shipments s ON s.shipment_id = a.shipment_id
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
JOIN docks d ON d.dock_id = sl.dock_id
WHERE a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
  AND s.required_dock_type NOT IN ('ANY', d.dock_type);

-- ---------- Q-08: active booking that ends before the truck can arrive ----------
-- I-04. Expect 0 rows. A row = a promise that is already broken.
SELECT a.appointment_id, s.shipment_id, a.appointment_status, v.effective_eta_ts,
       sl.slot_start_ts, sl.slot_end_ts
FROM appointments a
JOIN shipments s ON s.shipment_id = a.shipment_id
JOIN v_latest_eta v ON v.shipment_id = s.shipment_id
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
WHERE a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
  AND s.current_status IN ('PLANNED','ASSIGNED','IN_TRANSIT')
  AND julianday(v.effective_eta_ts) >= julianday(sl.slot_end_ts);

-- ---------- Q-09: unload takes longer than the booked slot ----------
-- I-05. Expect 0 rows. A row = the next truck on that dock will be delayed.
SELECT a.appointment_id, s.shipment_id, s.expected_unload_min,
       CAST(ROUND((julianday(sl.slot_end_ts) - julianday(sl.slot_start_ts)) * 1440) AS INTEGER) slot_min
FROM appointments a
JOIN shipments s ON s.shipment_id = a.shipment_id
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
WHERE a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
  AND s.expected_unload_min > ROUND((julianday(sl.slot_end_ts) - julianday(sl.slot_start_ts)) * 1440);
-- ROUND is needed: julianday() keeps tiny fractions, so 60 min can compute as 59.99999.

-- ---------- Q-10: the "latest ETA" view picks the newest update, not the most reliable ----------
-- I-06. Rows = shipments whose effective ETA is LOW confidence (a guess, not a time).
SELECT shipment_id, effective_eta_ts, eta_source, eta_confidence, eta_note
FROM v_latest_eta WHERE eta_confidence = 'LOW';

-- ---------- Q-11: one shipment, several different ETAs ----------
-- I-07. Rows = which ETA is true? The view keeps only the newest.
SELECT shipment_id, COUNT(*) n_updates, GROUP_CONCAT(substr(declared_eta_ts,12,5) || ' ' || confidence_code, ' -> ') etas
FROM (SELECT * FROM eta_updates ORDER BY created_at)
GROUP BY shipment_id HAVING COUNT(DISTINCT declared_eta_ts) > 1;

-- ---------- Q-12: duplicate driver message created a second exception ----------
-- I-08. Rows = the same report arrived twice. Without a key check, a repeated
-- "yes, take it" could book twice.
SELECT m.chat_message_id, m.thread_id, m.external_message_id, m.is_duplicate, m.message_ts, m.message_text
FROM chat_messages m WHERE m.is_duplicate = 1;
SELECT dedupe_key, COUNT(*) n, GROUP_CONCAT(exception_id || ':' || exception_status) rows_
FROM driver_exceptions WHERE dedupe_key IS NOT NULL
GROUP BY dedupe_key HAVING COUNT(*) > 1;

-- ---------- Q-13: which shipment is the driver talking about? ----------
-- I-09. (a) drivers with more than one live shipment; (b) threads with no shipment.
SELECT driver_id, COUNT(*) live_shipments, GROUP_CONCAT(shipment_id) shipments
FROM shipments WHERE current_status NOT IN ('COMPLETED','CANCELLED')
GROUP BY driver_id HAVING COUNT(*) > 1;
SELECT thread_id, driver_id, thread_status, thread_intent FROM chat_threads WHERE shipment_id IS NULL;

-- ---------- Q-14: control: thread driver = shipment driver ----------
-- Expect 0 rows. (The stand-in flagged THR011 here; the real data is clean.)
SELECT t.thread_id, t.driver_id thread_driver, s.shipment_id, s.driver_id shipment_driver
FROM chat_threads t JOIN shipments s ON s.shipment_id = t.shipment_id
WHERE t.driver_id <> s.driver_id;

-- ---------- Q-15: driver asks about a cancelled shipment ----------
-- I-10. Rows = the agent must not offer slots for these.
SELECT t.thread_id, t.driver_id, s.shipment_id, s.current_status, t.thread_intent
FROM chat_threads t JOIN shipments s ON s.shipment_id = t.shipment_id
WHERE s.current_status = 'CANCELLED';

-- ---------- Q-16: warehouse confirmation pending with no expiry ----------
-- I-11. Rows = slots tied up as PENDING with no deadline; the schema has no
-- "expires_at" and no "held" state for a driver who is still deciding.
SELECT a.appointment_id, a.shipment_id, d.dock_code, sl.slot_start_ts, a.booked_at,
       o.operational_message_id, o.delivery_status
FROM appointments a
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
JOIN docks d ON d.dock_id = sl.dock_id
LEFT JOIN operational_messages o ON o.appointment_id = a.appointment_id
WHERE a.appointment_status = 'PENDING_CONFIRMATION';

-- ---------- Q-17: an escalation message that never arrived ----------
-- I-12. Rows = operational messages that FAILED or are still QUEUED.
SELECT operational_message_id, shipment_id, channel, recipient_address, subject, sent_at, delivery_status
FROM operational_messages WHERE delivery_status IN ('FAILED','QUEUED');

-- ---------- Q-18: contacts with missing details or vacant roles ----------
-- I-13. Rows = a hand-off could go to nobody.
SELECT contact_id, facility_id, contact_role, contact_name, email, phone
FROM facility_contacts
WHERE email IS NULL OR phone IS NULL OR contact_name LIKE '%Vacant%';

-- ---------- Q-19: SHP1015 (reefer): is any compatible slot left after its ETA? ----------
-- I-14. Expect 0 rows = no feasible slot, so a person must decide (the escalation case).
SELECT v.slot_id, v.dock_code, v.slot_start_ts, v.availability_status
FROM v_slot_availability v, shipments s, v_latest_eta e
WHERE s.shipment_id = 'SHP1015' AND e.shipment_id = s.shipment_id
  AND v.facility_id = s.destination_facility_id
  AND v.supports_refrigerated = 1
  AND v.availability_status = 'AVAILABLE'
  AND julianday(v.slot_start_ts) >= julianday(e.effective_eta_ts)
  AND v.max_vehicle_weight_kg >= s.load_weight_kg;
-- Context for the reader: every reefer slot at Jaipur from 17:00
SELECT v.slot_id, v.dock_code, v.slot_start_ts, v.slot_end_ts, v.availability_status, sl.block_reason
FROM v_slot_availability v JOIN appointment_slots sl ON sl.slot_id = v.slot_id
WHERE v.facility_id = 'FAC-JAI-01' AND v.supports_refrigerated = 1 AND v.slot_start_ts >= '2026-08-04T17:00'
ORDER BY v.slot_start_ts;

-- ---------- Q-20: rules stored as free text, not enforced ----------
-- I-15. The facility_rules table is read by people; nothing in the schema enforces
-- RULE004 (heavy > 25,000 kg) or RULE005 (no new start after 21:00 without approval).
SELECT rule_id, facility_id, rule_type, rule_value, description FROM facility_rules ORDER BY rule_id;

-- ---------- Q-21: status words: is there a "held while the driver decides" state? ----------
-- I-16. The lists come from the CHECK constraints. No HELD state exists.
SELECT 'slot_status' k, slot_status v, COUNT(*) n FROM appointment_slots GROUP BY 2
UNION ALL SELECT 'appointment_status', appointment_status, COUNT(*) FROM appointments GROUP BY 2
UNION ALL SELECT 'shipment_status', current_status, COUNT(*) FROM shipments GROUP BY 2
UNION ALL SELECT 'priority_code', priority_code, COUNT(*) FROM shipments GROUP BY 2;

-- ---------- Q-22: personal data in the database (privacy) ----------
-- I-17. Phone numbers sit in drivers, carriers, contacts and an SMS recipient.
-- They must never reach a prompt or a log.
SELECT 'drivers.phone' src, COUNT(*) n FROM drivers WHERE phone IS NOT NULL
UNION ALL SELECT 'facility_contacts.phone', COUNT(*) FROM facility_contacts WHERE phone IS NOT NULL
UNION ALL SELECT 'operational_messages SMS recipient', COUNT(*) FROM operational_messages WHERE channel = 'SMS'
UNION ALL SELECT 'chat text with 10+ digits', COUNT(*) FROM chat_messages
  WHERE message_text GLOB '*[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*';

-- ---------- Q-23: messages that need a person to read them ----------
-- I-18. Vague delays ("late by one hour") flagged for human review.
SELECT chat_message_id, thread_id, message_ts, message_text
FROM chat_messages WHERE requires_human_review = 1;
