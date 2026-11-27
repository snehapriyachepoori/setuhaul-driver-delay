# Submission template (fill the brackets after the build)
Name: [your name]
Repo (or Google Drive) link: [link]
Live demo link (if deployed): not deployed
Stack used: Python, SQLite, LangGraph, Pydantic, pytest, [Ollama model and/or OpenRouter model], [LangSmith if used]. Built with AI assistance (Claude); I wrote, ran and understand the code.

1. Problem Definition Sheet and data audit (link): [repo]/docs/01_submission_problem_sheet.md (audit queries: 01_audit_queries.sql). Audited on a synthetic stand-in database.
Top data issue you found: the booked slot ends before the truck's latest ETA (3 of 20 appointments in the stand-in), so a promise is already broken. [Replace if you rerun on real data.]

2. Decision register (link): [repo]/docs/03_decision_register.md
How you order competing requests: confirmed promises are never taken back; first hold wins; the last compatible slot of a scarce type is kept for top-priority loads; conflicts go to a coordinator.

3. Prototype: how to run it (one command): [make demo]

4. Scenario run video (link): [link]
Which case escalates and why: SHP1015, a refrigerated load. The only reefer dock is closed from 19:00, so no feasible slot exists and a person must decide.

5. Integrity test (link): [repo]/docs/integrity_proof.txt
Result (requests sent, bookings made, double bookings): [1,000 / 100 / 0]

6. Client readout (link): [repo]/docs/client_readout.md
Optional scheduling tool (link, or not attempted): [link or not attempted]
What does not work yet: [list honestly: e.g. real data not used, demo-level authentication, assumptions not confirmed by the client, WhatsApp not built]
