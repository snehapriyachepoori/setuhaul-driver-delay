# START HERE: SetuHaul project hand-off (everything in one file)

Written 26 Nov 2026. Use this file to start the build in Claude Code. Open the project folder, put this file and `CLAUDE.md` in the root, and tell Claude Code to read both.

## 1. Complete problem statement
**Client:** SetuHaul Logistics Pvt. Ltd., a third-party logistics company moving full-truckload freight across North and West India. 280 to 360 loads a day, 6 destination facilities, 32 dock doors, 190 to 240 receiving appointments a day. 15 to 25 driver exception messages on a normal day, and 20 to 35 in 30 minutes in a disruption spike. 5 coordinators per shift. 0 live GPS feeds (every ETA comes from the plan or from the driver).

**The task (from the brief):** build a service that answers drivers when they run late, and prove it stays correct when ten drivers want the same dock slot.

**Problem statement:** how might SetuHaul give drivers a conversational way to report delays, ask questions and consider revised appointments, while many simultaneous requests meet limited warehouse capacity, without infeasible or conflicting promises?

**Why it is hard:** a dock slot holds one active booking. Two conversations can read the same slot as free, both drivers say yes, and both get a promise. Only one can be true. Drivers also write messy text ("around two hours late", "anything after 7", "the second one works, but I need to leave by 9").

**Rules the system must never break:**
1. Never two active bookings on one slot.
2. Never tell a driver a slot is theirs before it is committed.
3. Re-check a slot when committing; never book a stale option.
4. A safety report always goes to a person first.
5. Confirm the right shipment, and only for the right driver.
6. A repeated message never causes a second action.
7. No feasible slot: escalate, never invent an answer.
8. The model never decides capacity, ranking or commit. Code and the database do.

**Boundaries (from the brief):** a person approves or takes over safety decisions, penalties, no-slot cases, contradictory data and regulated loads. Out of scope: national network optimisation, freight-rate talks, driver-safety automation, customs and hazmat workflows, commercial penalty approval.

**Data:** the brief's SQLite package (18 tables, 2 facilities, 9 docks, 21 shipments, snapshot 4 Aug 2026, +05:30). **You do not have the real file. You use `dummy_setuhaul.db`, a synthetic stand-in** with the same table names and planted problems. Say so in your submission. If the real file arrives, rerun `python3 run_audit.py REAL.db` and replace the audit results.

## 2. What you already have (in `fde-work/`)
| File | What it is | Submission item |
|---|---|---|
| `01_submission_problem_sheet.md` | Short problem sheet and audit table | 1 |
| `01_problem_definition.md`, `01_audit_queries.sql`, `run_audit.py`, `audit_results_DUMMY.txt` | Full sheet, the audit queries, the runner and its output | 1 |
| `02_cause_effect.md`, `02_evidence_queries.sql` | Why the problem happens (22 causes), proven mechanisms M1 to M4 | Supports 2 |
| `03_decision_register.md` | The 13 brief decisions plus architecture choices | 2 |
| `03_architecture.md` | The full design (sections 6 to 9 are the core) | Supports 2 and 3 |
| `03_build_and_test_guide.md` | 12 build steps and test plan T-01 to T-17 | 3, 4, 5 |
| `03_cost_estimate.xlsx`, `03_option_scoring.py` | Cost model and option scoring | Supports 2 and 6 |
| `CLAUDE.md` | Instructions for Claude Code | |
| `dummy_setuhaul.db`, `README.md` (stand-in notes) | In your original `files_1.zip` | Input data |

Also included: `04_bonus_marks_plan.md` (extra-marks items E1 to E6 with tests T-19 to T-24), `05_submission_template_FILLED.md`, `06_client_readout_TEMPLATE.md`.

Still to create: the prototype, the scenario run, the integrity proof and the one-page client readout.

## 3. Architecture in short
**Chosen design (option B):** one LangGraph agent with stage-gated tools. Code owns the stage and every commit. If your model's tool calling is unreliable, run option A (a fixed workflow where the model only extracts fields and phrases replies) on the same tools.

```
Driver (terminal chat)
  -> Authentication: phone number checked against drivers; driver_id stored in the session
  -> Entry checks: duplicate message key, mask phone numbers, safety-cue screen
  -> Stage machine (code): SAFETY > IDENTIFY > CLARIFY > OFFER > HOLD > CONFIRM > DONE  (ESCALATE from any stage)
  -> LangGraph agent (model via one adapter: OpenRouter or Ollama) picks only the tools allowed at that stage
  -> 8 typed tools -> Capacity module (feasibility checks, ranking, ONE transaction) -> SQLite
  -> Output check: any time, dock or "confirmed" must match a tool result from this turn
  -> Hand-off table -> coordinator view (PIN from .env)
```
**The 8 tools:** `resolve_shipment`, `get_shipment_context`, `record_eta_declaration`, `get_feasible_slots`, `hold_slot`, `confirm_booking`, `release_hold`, `escalate_to_coordinator`. Every write tool takes an idempotency key.

**Slot states:** shown (nothing reserved) > held (one owner, 5 minutes, unique index) > confirmed. Pending approval if a rule needs a person. Confirm re-runs the full feasibility check inside the same transaction, and the driver hears "confirmed" only after the commit succeeds.

**Memory and data:** SQLite database (the record). New tables: `slot_holds`, `offers`, `idempotency_log`, `inbound_messages`, `slot_times`, `handoffs`, `audit_events`, `priority_policy`. Short-term memory is the LangGraph checkpointer on SQLite, keyed by thread id. No long-term memory. No RAG, no ML.

**Feasibility, ten ordered checks** (architecture 9.5): shipment valid and owned; slot open and not held; dock up; dock type matches; inside hours; slot start at or after ETA plus margin; slot end within the driver's latest finish; buffer and no overlap; priority policy; approval threshold.

**Ordering competing requests (P-1 to P-5):** a confirmed promise is never taken back; first hold wins; the last compatible slot of a scarce type is kept for P1 loads; conflicts go to a coordinator; a queue (later) orders by priority, then latest finish, then arrival.

**Authentication (demo level):** the driver starts with a phone number checked against `drivers.phone`; every tool checks the shipment belongs to that driver. The coordinator view needs a PIN from `.env`. Keys live only in `.env`. No AWS. Be honest in the README that this is not production security.

**Model route:** one adapter, two settings: Ollama (local, free) and OpenRouter (your key). Choose a model that lists tool calling.

## 4. Build order for one day (about 9 hours)
1. **Set up (30 min):** virtual environment, `pip install pytest pydantic langgraph`, git, `.gitignore` (`.env`, `.venv/`), pin versions in `requirements.txt`.
2. **Open the data (30 min):** run the audit queries.
3. **Core logic, no model (2 h):** feasibility checks, ETA rule, policy, migration for new tables, unit tests.
4. **Commit layer and integrity test (2 h):** hold, confirm, release as `BEGIN IMMEDIATE` transactions; the 10-thread test.
5. **Tools and authentication (1 h).**
6. **Agent (2 h):** LangGraph, stage machine, memory, model adapter; fall back to option A if needed.
7. **Escalation and scenario script (1 h).**
8. **README, client readout, template (1.5 h).**
Then, in order, the extra-marks items in `04_bonus_marks_plan.md`: measures table, failure tests, competing-trucks replay, client readout from `06_client_readout_TEMPLATE.md`, LangSmith trace, optional scheduler. Skip WhatsApp and Streamlit.

## 5. Model setup
- **Ollama (installed):** `ollama pull <model>` for a model with the "tools" tag (a Qwen3 8B class model was the best local result in one test; check the model page). Test with `ollama run <model>`. Needs roughly 8 to 16 GB of free memory (unverified; check your laptop).
- **OpenRouter:** put the key in `.env`. Pick a model that lists tool calling and check its price on openrouter.ai/models.
- Use Ollama for development and OpenRouter for the final recording if the local model is unreliable.

## 6. GitHub
1. Create a public repository on github.com (no README or `.gitignore` added there).
2. In the project folder: `git add .`, `git commit -m "first commit"`.
3. `git remote add origin <repo-url>`, `git branch -M main`, `git push -u origin main`.
4. Log in with `gh auth login` or a personal access token (a password won't work).
5. Never commit `.env`. If a key is ever committed, revoke it and make a new one.
6. Put the `fde-work` documents in `docs/`.

## 7. How to produce the two proofs
**Integrity proof (item 5):**
- `pytest tests/concurrency -q`: ten threads, each with its own connection, try to confirm the same slot at once. One succeeds. Repeat 100 times.
- Report: **1,000 requests sent, 100 bookings made, 0 double bookings.**
- Add an SQL check that lists slots with more than one active booking (expect no rows).
- Add a control run with the slot protection switched off that double-books, to show the test can fail.
- Save the output as `docs/integrity_proof.txt`, and record the run if you can.

**Scenario run (item 4):**
- `python run_scenarios.py` runs the cases through the real agent and saves `docs/scenario_run.md` (each turn, the tool calls, the final database state).
- Cases: a delay with clarification questions; later options compared; several requests on one facility; two requests for the same slot; an option that disappears; **one escalation: SHP1015 (refrigerated, the only reefer dock is closed from 19:00), ending with the printed hand-off record.**
- Record your terminal for 3 to 5 minutes while it runs and explain what happens. Any screen recorder works (OBS, Loom).

## 8. Submission checklist and template
1. Problem Definition Sheet and data audit: `01_submission_problem_sheet.md` (label "stand-in" unless you get the real file).
2. Decision register: `03_decision_register.md`.
3. Prototype: public GitHub repo, one command to run (e.g. `make demo`), pinned library versions in the README, and an honest line that AI assistance was used.
4. Scenario run: transcript plus recording; escalation case SHP1015, because no feasible slot exists and a person must decide.
5. Integrity proof: test output with requests sent, bookings made, double bookings.
6. One-page client readout (policy, limits, open risks) for the head of operations and a warehouse planner, in plain words. Optional: the scheduling tool. Say plainly what does not work yet.

**Template answers ready now:**
- **Top data issue (stand-in):** the booked slot ends before the truck's latest ETA, so a promise is already broken (audit Q-11). Replace after any real run.
- **How you order competing requests:** a confirmed promise is never taken back; first hold wins; the last compatible slot is kept for top-priority loads; any conflict goes to a coordinator.
- **Stack:** Python, SQLite, LangGraph, Pydantic, pytest, Ollama and OpenRouter (state the model you used).

## 9. Honest limits to state in the submission
Audit ran on a synthetic database. Hold time, ETA margins, the approval threshold, the priority rule and response times are assumptions with named owners. Authentication is demo level. Cost figures use placeholders. Anything not built is listed under "what does not work yet".

## 10. First message to paste in Claude Code
"Read CLAUDE.md and 00_START_HERE_HANDOFF.md, then the files they list. I have one day. Start with build guide step 1 and teach me as we go: explain each piece, let me run the commands, and review my code. Build the model-free core first (feasibility, commit layer, integrity test), then tools, authentication, the agent, and the scenario script. I use dummy_setuhaul.db (synthetic). My model options are Ollama (installed) and an OpenRouter key in .env."
