-- =====================================================================
-- SetuHaul Logistics: evidence queries for the Cause-Effect Register
-- STATUS: RUN on the SYNTHETIC stand-in database only (dummy_setuhaul.db).
-- NOT RUN on the real snapshot (never supplied). A result here shows the query
-- works and shows a MECHANISM. It is not a finding about SetuHaul.
-- Numbering: EV-C<n> proves a link in the chain for cause C<n> in 02_cause_effect.md.
-- Run:  python3 run_audit.py <db> 02_evidence_queries.sql
-- =====================================================================

-- ---------- EV-C1: is there any HOLD state or expiry column? ----------
-- Lists every status value in use and every column that could carry a hold or expiry.
SELECT 'slot_status' AS vocab, slot_status AS value, COUNT(*) AS n FROM appointment_slots GROUP BY 2
UNION ALL SELECT 'appointment_status', appointment_status, COUNT(*) FROM appointments GROUP BY 2;

SELECT m.name AS tbl, p.name AS col
FROM sqlite_master m, pragma_table_info(m.name) p
WHERE m.type='table' AND (p.name LIKE '%hold%' OR p.name LIKE '%expir%' OR p.name LIKE '%ttl%' OR p.name LIKE '%reserved%');

-- ---------- EV-C1b: pending bookings that lock a slot the truck cannot reach ----------
-- 'pending_confirmation' counts as ACTIVE in the unique index, so it locks the slot,
-- yet the truck's latest ETA is already after the slot ends. Capacity wasted by a promise nobody can keep.
SELECT a.appointment_id, a.appointment_status, a.shipment_id, sh.priority_code,
       s.slot_start_ts, s.slot_end_ts, sh.latest_eta_ts
FROM appointments a
JOIN appointment_slots s ON s.slot_id=a.slot_id
JOIN shipments sh ON sh.shipment_id=a.shipment_id
WHERE a.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND datetime(sh.latest_eta_ts) > datetime(s.slot_end_ts);

-- ---------- EV-C4: slot the availability view calls free but is not ----------
-- v_slot_availability reads slot_status only. This lists "available" slots that a dock event covers.
SELECT v.slot_id, d.dock_code, d.dock_type, v.slot_start_ts, e.event_type, e.event_start_ts, e.event_end_ts
FROM v_slot_availability v
JOIN docks d ON d.dock_id=v.dock_id
JOIN dock_status_events e ON e.dock_id=v.dock_id
 AND datetime(v.slot_start_ts) < datetime(e.event_end_ts)
 AND datetime(v.slot_end_ts)   > datetime(e.event_start_ts)
WHERE v.is_available=1;

-- ---------- EV-C4b: "available" vs "feasible" for each delayed or planned truck ----------
-- naive = view says free. feasible = free AND right dock type AND same facility AND starts at or after
-- the truck's latest ETA AND no dock event overlaps AND inside facility hours.
-- NOTE: datetime() converts to UTC, so facility hours are compared on the LOCAL clock text (substr),
-- which is only safe because every slot timestamp carries +05:30. A first draft of this query used time()
-- and silently compared UTC to local hours: the same time-zone trap described in cause C6.
WITH cand AS (
  SELECT sh.shipment_id, sh.priority_code, sh.required_dock_type, sh.latest_eta_ts,
         s.slot_id, s.slot_start_ts, s.slot_end_ts, d.dock_code, d.dock_type,
         (SELECT COUNT(*) FROM dock_status_events e WHERE e.dock_id=s.dock_id
            AND datetime(s.slot_start_ts) < datetime(e.event_end_ts)
            AND datetime(s.slot_end_ts) > datetime(e.event_start_ts)) AS blocked_by_event,
         f.open_time, f.close_time
  FROM shipments sh
  JOIN facilities f ON f.facility_id=sh.destination_facility_id
  JOIN appointment_slots s ON s.facility_id=sh.destination_facility_id
  JOIN docks d ON d.dock_id=s.dock_id
  JOIN v_slot_availability v ON v.slot_id=s.slot_id AND v.is_available=1
  WHERE sh.current_status IN ('delayed','planned','in_transit')
)
SELECT shipment_id, priority_code, required_dock_type,
       SUM(datetime(slot_start_ts) >= datetime(latest_eta_ts)) AS free_after_eta_naive,
       SUM(datetime(slot_start_ts) >= datetime(latest_eta_ts)
           AND dock_type=required_dock_type AND blocked_by_event=0
           AND substr(slot_start_ts,12,5) >= open_time AND substr(slot_end_ts,12,5) <= close_time) AS feasible_by_code
FROM cand GROUP BY shipment_id ORDER BY feasible_by_code, shipment_id;

-- ---------- EV-C5: rules that clash with the slot grid ----------
-- RULE003 asks for 15 minutes between bookings on one dock. Count booked neighbours with a gap < 15 min.
SELECT a1.shipment_id AS first_truck, a2.shipment_id AS next_truck, d.dock_code,
       s1.slot_end_ts AS first_ends, s2.slot_start_ts AS next_starts,
       CAST((julianday(s2.slot_start_ts)-julianday(s1.slot_end_ts))*1440 AS INT) AS gap_minutes
FROM appointments a1
JOIN appointment_slots s1 ON s1.slot_id=a1.slot_id
JOIN appointment_slots s2 ON s2.dock_id=s1.dock_id AND s2.slot_start_ts>=s1.slot_end_ts
JOIN appointments a2 ON a2.slot_id=s2.slot_id
JOIN docks d ON d.dock_id=s1.dock_id
WHERE a1.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND a2.appointment_status NOT IN ('cancelled','no_show','replaced')
  AND NOT EXISTS (SELECT 1 FROM appointment_slots s3 JOIN appointments a3 ON a3.slot_id=s3.slot_id
                  WHERE s3.dock_id=s1.dock_id AND s3.slot_start_ts>=s1.slot_end_ts
                    AND s3.slot_start_ts<s2.slot_start_ts AND a3.appointment_status NOT IN ('cancelled','no_show','replaced'))
  AND (julianday(s2.slot_start_ts)-julianday(s1.slot_end_ts))*1440 < 15;

-- Rules are free text, not columns a program can read:
SELECT rule_id, rule_type, length(rule_text) AS text_len FROM facility_rules;

-- ---------- EV-C6: ETA source conflict, ordering and format ----------
-- (a) text comparison vs real time: a 'Z' timestamp sorts before every '+05:30' timestamp on the same day.
SELECT e.shipment_id, e.declared_eta_ts, e.source_type,
       (e.declared_eta_ts < '2026-08-04T11:00:00+05:30') AS text_says_before_11h,
       (datetime(e.declared_eta_ts) < datetime('2026-08-04T11:00:00+05:30')) AS time_says_before_11h
FROM eta_updates e WHERE e.declared_eta_ts NOT LIKE '%+05:30';

-- (b) "latest wins" ignores confidence: the newest ETA is sometimes the weakest.
SELECT u.shipment_id, u.source_type AS newest_source, u.confidence_code AS newest_conf,
       (SELECT group_concat(x.source_type||':'||x.confidence_code, ' < ') FROM eta_updates x
         WHERE x.shipment_id=u.shipment_id ORDER BY x.reported_ts) AS history_oldest_to_newest
FROM eta_updates u
WHERE u.reported_ts=(SELECT MAX(reported_ts) FROM eta_updates y WHERE y.shipment_id=u.shipment_id)
  AND u.confidence_code IN ('low','medium')
  AND (SELECT COUNT(*) FROM eta_updates z WHERE z.shipment_id=u.shipment_id)>1;

-- (c) does the view ever return two rows for one shipment (ties on reported_ts)?
SELECT shipment_id, COUNT(*) AS rows_in_view FROM v_latest_eta GROUP BY 1 HAVING COUNT(*)>1;

-- (d) is there a field that says whether "90 minutes" is repair time or total delay?
SELECT m.name AS tbl, p.name AS col FROM sqlite_master m, pragma_table_info(m.name) p
WHERE m.type='table' AND (p.name LIKE '%repair%' OR p.name LIKE '%delay%' OR p.name LIKE '%minutes%');

-- ---------- EV-C7: which shipment does this driver mean? ----------
SELECT d.driver_id, group_concat(DISTINCT sh.shipment_id) AS active_shipments,
       (SELECT group_concat(t.thread_id||'('||COALESCE(t.shipment_id,'NONE')||')') FROM chat_threads t
         WHERE t.driver_id=d.driver_id AND t.thread_status='open') AS open_threads
FROM drivers d JOIN shipments sh ON sh.driver_id=d.driver_id
WHERE sh.current_status NOT IN ('completed','cancelled')
GROUP BY d.driver_id HAVING COUNT(DISTINCT sh.shipment_id)>1;

-- ---------- EV-C8: duplicates and the missing external message key ----------
SELECT thread_id, message_text, message_ts, COUNT(*) AS copies, SUM(is_duplicate) AS flagged_duplicate
FROM chat_messages GROUP BY thread_id, message_text, message_ts HAVING COUNT(*)>1;

SELECT p.name AS chat_messages_column FROM pragma_table_info('chat_messages') p;

-- ---------- EV-C9: demand vs supply, and what ranks trucks ----------
-- Delayed standard trucks at the Jaipur DC and the open standard slots after the earliest of their ETAs.
SELECT 'delayed standard trucks' AS what, COUNT(*) AS n FROM shipments
 WHERE current_status='delayed' AND required_dock_type='standard' AND destination_facility_id='F1'
UNION ALL
SELECT 'open standard slots 11:00-14:00', COUNT(*) FROM appointment_slots s JOIN docks d ON d.dock_id=s.dock_id
 WHERE s.facility_id='F1' AND d.dock_type='standard' AND s.slot_status='open'
   AND substr(s.slot_start_ts,12,5)>='11:00' AND substr(s.slot_end_ts,12,5)<='14:00';

SELECT priority_code, COUNT(*) AS trucks FROM shipments GROUP BY 1 ORDER BY 1;
SELECT rule_id, rule_text FROM facility_rules WHERE rule_type='priority';

-- ---------- EV-C10/C17/C18: columns that SHOULD exist if the rule were modelled ----------
-- Empty result = the data cannot answer the question.
SELECT 'eway_bill' AS topic, m.name AS tbl, p.name AS col FROM sqlite_master m, pragma_table_info(m.name) p
 WHERE m.type='table' AND (p.name LIKE '%eway%' OR p.name LIKE '%e_way%' OR p.name LIKE '%valid%' OR p.name LIKE '%document%')
UNION ALL
SELECT 'driver_hours', m.name, p.name FROM sqlite_master m, pragma_table_info(m.name) p
 WHERE m.type='table' AND (p.name LIKE '%duty%' OR p.name LIKE '%rest%' OR p.name LIKE '%shift%' OR p.name LIKE '%hours%')
UNION ALL
SELECT 'unload_duration', m.name, p.name FROM sqlite_master m, pragma_table_info(m.name) p
 WHERE m.type='table' AND (p.name LIKE '%duration%' OR p.name LIKE '%unload%')
UNION ALL
SELECT 'money_terms', m.name, p.name FROM sqlite_master m, pragma_table_info(m.name) p
 WHERE m.type='table' AND (p.name LIKE '%rate%' OR p.name LIKE '%penalt%' OR p.name LIKE '%detention%' OR p.name LIKE '%sla%' OR p.name LIKE '%tier%' OR p.name LIKE '%contract%');

SELECT DISTINCT CAST(ROUND((julianday(slot_end_ts)-julianday(slot_start_ts))*1440) AS INT) AS slot_minutes FROM appointment_slots;

-- ---------- EV-C11: what a hand-off record looks like today ----------
SELECT p.name AS operational_messages_column FROM pragma_table_info('operational_messages') p;
SELECT message_type, COUNT(*) AS n FROM operational_messages GROUP BY 1;
SELECT om_id, shipment_id, message_text FROM operational_messages WHERE message_type='escalation';
SELECT name AS table_with_handoff_like_name FROM sqlite_master
 WHERE type='table' AND (name LIKE '%handoff%' OR name LIKE '%hand_off%' OR name LIKE '%escalat%' OR name LIKE '%task%');

-- ---------- EV-C12: safety words in driver text and exception types ----------
SELECT exception_type, exception_status, COUNT(*) AS n FROM driver_exceptions GROUP BY 1,2;
SELECT chat_message_id, thread_id, message_text FROM chat_messages
WHERE sender_type='driver' AND (lower(message_text) LIKE '%accident%' OR lower(message_text) LIKE '%injur%'
   OR lower(message_text) LIKE '%hospital%' OR lower(message_text) LIKE '%fire%' OR lower(message_text) LIKE '%tyre%'
   OR lower(message_text) LIKE '%tire%' OR lower(message_text) LIKE '%unsafe%' OR lower(message_text) LIKE '%sleep%');

-- ---------- EV-C13: personal data where it should not be ----------
SELECT chat_message_id, thread_id, message_text FROM chat_messages
WHERE message_text GLOB '*[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*';
SELECT 'drivers.phone' AS place, COUNT(*) AS n FROM drivers WHERE phone IS NOT NULL
UNION ALL SELECT 'facility_contacts.phone', COUNT(*) FROM facility_contacts WHERE phone IS NOT NULL;
SELECT m.name AS tbl, p.name AS col FROM sqlite_master m, pragma_table_info(m.name) p
 WHERE m.type='table' AND (p.name LIKE '%consent%' OR p.name LIKE '%purpose%' OR p.name LIKE '%retention%' OR p.name LIKE '%delete%');

-- ---------- EV-C14: systems disagree about the same truck ----------
-- plan/status vs gate check-in vs booked dock
SELECT sh.shipment_id, sh.current_status AS shipment_status, c.queue_state AS gate_state,
       a.appointment_status, bd.dock_code AS booked_dock, cd.dock_code AS checked_in_dock
FROM shipments sh
LEFT JOIN facility_checkins c ON c.shipment_id=sh.shipment_id
LEFT JOIN appointments a ON a.shipment_id=sh.shipment_id AND a.is_current=1
LEFT JOIN appointment_slots s ON s.slot_id=a.slot_id
LEFT JOIN docks bd ON bd.dock_id=s.dock_id
LEFT JOIN docks cd ON cd.dock_id=c.actual_dock_id
WHERE c.checkin_id IS NOT NULL
  AND ( (sh.current_status IN ('in_transit','planned','delayed'))
     OR (bd.dock_id IS NOT NULL AND cd.dock_id IS NOT NULL AND bd.dock_id<>cd.dock_id) );

-- ---------- EV-C16: bunching of driver messages ----------
SELECT substr(message_ts,1,13) || ':' || CASE WHEN substr(message_ts,15,2)<'30' THEN '00' ELSE '30' END AS half_hour,
       COUNT(*) AS driver_msgs, COUNT(DISTINCT thread_id) AS threads
FROM chat_messages WHERE sender_type='driver' GROUP BY 1 ORDER BY 1;

-- ---------- EV-C19: partial index details that leave ghost bookings ----------
-- Old appointment replaced by a new one: is its status 'replaced' (frees the slot) or something else?
SELECT o.appointment_id AS old_appt, o.appointment_status AS old_status, o.is_current AS old_is_current,
       n.appointment_id AS new_appt, n.appointment_status AS new_status
FROM appointments n JOIN appointments o ON o.appointment_id=n.replaced_appointment_id;
-- Active appointments that are not the shipment's current one (they still block their slot):
SELECT appointment_id, shipment_id, slot_id, appointment_status FROM appointments
WHERE is_current=0 AND appointment_status NOT IN ('cancelled','no_show','replaced');

-- ---------- EV-C21: does an "offer" exist as a thing the system can check later? ----------
-- Empty = nothing records WHICH option was shown to WHICH driver at WHAT state.
SELECT name AS offer_like_table FROM sqlite_master
 WHERE type='table' AND (name LIKE '%offer%' OR name LIKE '%option%' OR name LIKE '%proposal%');
SELECT m.name AS tbl, p.name AS col FROM sqlite_master m, pragma_table_info(m.name) p
 WHERE m.type='table' AND m.name IN ('chat_messages','chat_threads','appointments')
   AND (p.name LIKE '%offer%' OR p.name LIKE '%option%' OR p.name LIKE '%version%' OR p.name LIKE '%slot_id%');

-- ---------- EV-C22: short or mixed-language driver messages ----------
SELECT chat_message_id, thread_id, length(message_text) AS len, message_text FROM chat_messages
WHERE sender_type='driver'
  AND (length(message_text)<25 OR lower(message_text) LIKE '%hoon%' OR lower(message_text) LIKE '%ghante%'
       OR lower(message_text) LIKE '% pe %' OR lower(message_text) LIKE '%hai%' OR lower(message_text) LIKE '%nahi%');
