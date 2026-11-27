# Submission template
Name: [your name]
Repo (or Google Drive) link: https://github.com/snehapriyachepoori/setuhaul-driver-delay
Live demo link (if deployed): not deployed (runs locally: `python run.py demo`)
Stack used: Python 3.13, SQLite (WAL), LangGraph 1.2.24, Pydantic 2.14.4, pytest 9.2.0, OpenAI-style client 3.60.0 to OpenRouter (`anthropic/claude-haiku-5.5`, fallback `openai/gpt-4o-mini`); Ollama and a no-model rules mode as alternatives. No LangSmith yet. Built with AI assistance (Claude via Claude Code); I ran, reviewed and can explain the code.

1. Problem Definition Sheet and data audit (link): https://github.com/snehapriyachepoori/setuhaul-driver-delay/blob/main/docs/01_submission_problem_sheet.md (queries: docs/01_audit_queries.sql; output: docs/audit_results_REAL.txt). Audited on the real snapshot.
Top data issue you found: SHP1015's booking is a broken promise nobody is acting on: APT1015A is CONFIRMED for 17:00 to 18:00, the truck arrives 18:30, every reefer slot after that is blocked for maintenance, and the escalation email (OM004) FAILED.

2. Decision register (link): https://github.com/snehapriyachepoori/setuhaul-driver-delay/blob/main/docs/03_decision_register.md
How you order competing requests: a confirmed promise is never taken back automatically; the first hold on a slot wins (5-minute expiry); the last compatible slot of a scarce dock type is kept for high-priority loads; any conflict or pre-emption goes to a coordinator. Priority ordering of simultaneous requests needs the pilot queue (stated honestly).

3. Prototype: how to run it (one command): `python run.py demo` (Windows has no make)

4. Scenario run video (link): https://drive.google.com/file/d/1S-sx1aLPULcVHeY2Bkw-VIneLmCg2PQr/view?usp=sharing. Transcript: https://github.com/snehapriyachepoori/setuhaul-driver-delay/blob/main/docs/scenario_run.md
Which case escalates and why: SHP1015, a 15,000 kg refrigerated load with ETA 18:30. D5 is the only reefer dock at Jaipur and is under maintenance from 18:00 to 22:00, so no feasible slot exists and code hands it to the Jaipur warehouse coordinator with a complete record.

5. Integrity test (link): https://github.com/snehapriyachepoori/setuhaul-driver-delay/blob/main/docs/integrity_proof.txt
Result (requests sent, bookings made, double bookings): 1,000 / 100 / 0 (control run with protection off: 900 double bookings)

6. Client readout (link): https://github.com/snehapriyachepoori/setuhaul-driver-delay/blob/main/docs/client_readout.md
Optional scheduling tool (link, or not attempted): not attempted
What does not work yet: no LangSmith tracing; no facility scheduler; coordinator view is a terminal page, not a web console; safety detection is a keyword list; priority ordering of simultaneous requests needs a queue (first hold wins today); demo-level authentication; policy numbers are assumptions awaiting the client; WhatsApp not built.
