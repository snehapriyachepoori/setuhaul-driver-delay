# Build and test guide: SetuHaul driver-delay service

Follow the steps in order. **Do not move on until the "Check it" line passes.** Steps 3 to 5 use no model at all, so they cost nothing and run in seconds. Package versions are not pinned here; step 1 pins them on your machine. Commands are for macOS or Linux; on Windows use `py` and `.venv\Scripts\activate`.

## Step 1: Set up the machine
- **What we do:** install tools, create a project folder and a virtual environment (an isolated folder of Python packages).
- **Why:** repeatable runs (R15).
- **You do:**
```
mkdir setuhaul && cd setuhaul
python3 -m venv .venv && source .venv/bin/activate
pip install pytest pydantic langgraph streamlit
pip freeze > requirements.txt
git init && printf ".venv/\n.env\n*.db\n" > .gitignore
mkdir -p src tests/unit tests/tools tests/concurrency tests/guardrails tests/scenarios data
```
Copy `dummy_setuhaul.db` into `data/`. Copy the `fde-work` files into a `docs/` folder.
- **You should see:** `requirements.txt` listing exact versions.
- **Check it:** `python -c "import langgraph, pydantic"` prints nothing.
- **If it fails:** use Python 3.11 or newer; upgrade pip; install one package at a time.
- **Next:** open the data.

## Step 2: Open the data
- **You do:** `sqlite3 data/dummy_setuhaul.db ".tables"` then run `01_audit_queries.sql` Q-00 and Q-01.
- **You should see:** 18 tables, and `foreign_keys 0`.
- **Check it:** row counts match the brief (21 shipments, 106 slots, 20 appointments).
- **Remember:** this is a stand-in. If you get the real file, rerun here first.

## Step 3: Core logic without any model
- **What:** write plain functions: `resolve_eta()`, `check_slot()` (the ten checks, returning reason codes), `rank_options()`, the policy file, the stage machine.
- **Why:** R4, R5, R8.
- **You do:** write `src/capacity/feasibility.py` etc. and a migration `src/migrate.py` that adds `slot_times` (epoch columns) and the new tables from section 7B.
- **Check it:** `pytest tests/unit` passes these: reefer never gets a standard dock; SHP1015 returns 0 feasible with reason codes; `06:15:00Z` for SHP1012 resolves to 11:45 India time; SHP1013 does not pick the warehouse's low-confidence ETA by default.
- **If it fails:** print the reason codes; compare to section 9.5.

## Step 4: The commit layer, then the integrity proof
- **What:** `hold_slot`, `confirm_booking`, `release_hold` as `BEGIN IMMEDIATE` transactions with idempotency keys, re-check inside, rebooking in one transaction, audit and outbox rows.
- **Why:** R1, R2, R3, R7, R14.
- **You do:** one connection helper that sets `foreign_keys=ON`, WAL, busy timeout. Then `tests/concurrency/test_double_book.py`: start 10 threads (each with its own connection) that all confirm slot D2 18:00.
- **You should see:** exactly 1 CONFIRMED, 9 REFUSED, one live booking in the table. **Repeat 100 times.**
- **Check it:** `pytest tests/concurrency -q` passes; save the output as `docs/integrity_proof.txt` (a deliverable).
- **Also test:** same key twice returns the same answer; kill the process between steps and check no half state; a held slot is refused to a second thread; an expired hold is not trusted.
- **If it fails:** a "database is locked" error means missing busy timeout or a connection reading before taking the lock.

## Step 5: Tools
- **What:** wrap the eight tools (section 9.3) with Pydantic input and output types.
- **Check it:** `pytest tests/tools`: bad IDs return typed errors; another driver's shipment returns MISMATCH; every write tool repeats safely.

## Step 6: Knowledge and ML
- **Skipped on purpose** (no RAG, no ML). Record the decision (D-19).

## Step 7: Conversation layer
- **What:** the LangGraph graph with the stage machine (code), the allowlist per stage, max 6 tool calls a turn, the checkpointer keyed by `thread_id`, and a model adapter.
- **Set the key yourself:** put `ANTHROPIC_API_KEY=...` in `.env` (never in chat or code). No budget? install Ollama and use a local model through the adapter.
- **Check it:** run ladder level 1 (THR011: options only, nothing booked). Assert on **tool calls and final state**, not on wording.
- **If tool calling is unreliable on your model:** switch the adapter to option A mode (one extraction call, templates) on the same tools.

## Step 8: Memory
- **Check it:** stop mid-conversation, restart, reuse the `thread_id`: stage and facts are intact; no phone number appears in the checkpoint.

## Step 9: Escalation and the coordinator view
- **What:** `escalate_to_coordinator`, the `handoffs` table, a small Streamlit page listing open hand-offs with an acknowledge button.
- **Check it:** seed SHP1015 (ladder 6): exactly one hand-off with every field filled; the driver gets the no-slot message.
- **Also:** "Tyre damaged near Neemrana" asks the safety question first and offers no slot.

## Step 10: Observability
- **What:** log every turn to `audit_events`; optionally turn on LangSmith (synthetic data only).
- **Check it:** view one full conversation: stage changes, tool calls, tokens.

## Step 11: Scenario and load run
- **What:** script the seven cases (delay with clarification; later options compared; several requests on one facility; two competing for the same capacity; an option disappears; one no-slot escalation; optional scheduler). Then a load script: 35 messages in 30 minutes against the stand-in.
- **Check it:** transcripts saved; measures M-1 to M-12 tabulated; tokens per call measured and copied into the cost workbook, replacing the estimates.

## Optional step 12: Facility scheduler
Dispatch rule tool (`propose_facility_plan`), then the early, late and in-progress replay.

## Test plan (every requirement and invariant has a test)
| T-ID | Proves | Level | Attaches to | Pass rule |
|---|---|---|---|---|
| T-01 | I-1, R3 no double booking | Concurrency | Commit layer | 1 success of 10, 100 repeats |
| T-02 | I-2, R1 no promise before commit | Failure | Reply builder | Forced commit failure: driver never hears "confirmed" |
| T-03 | I-3, I-12, R14 stale option refused | Failure | Confirm | Block slot between offer and accept: refused with new options |
| T-04 | I-11, R7 duplicate | Tool contract | Entry, tools | THR009 replay: one action |
| T-05 | C19 partial failure | Failure | Confirm | Fail between cancel and create: nothing changes |
| T-06 | R4 feasibility | Unit | Checks | Reason codes correct on SHP1010, SHP1013, SHP1015 |
| T-07 | R5 ETA | Unit | ETA rule | Z time and low-confidence cases correct |
| T-08 | I-6, R6 right shipment | Conversation | Identify | THR010 asks which load; THR011 refused |
| T-09 | I-5, R9 safety first | Guardrail | Safety stage | No slot offered before a person is told |
| T-10 | I-13, R10 no-slot | Scenario | Escalation | Complete hand-off |
| T-11 | I-4, R8 policy | Scenario | Policy | Competing trucks follow P-1 to P-5 |
| T-12 | I-8, I-7 legal routing | Unit | Check 10 | Next-day move gives NEEDS_APPROVAL |
| T-13 | I-10, R11 privacy | Guardrail | Logs | No 10-digit number in logs or prompts |
| T-14 | R15 | Unit | Connection helper | Foreign keys on; orphan insert rejected |
| T-15 | Memory | Conversation | Checkpointer | Resume after restart |
| T-16 | R13 | Load | Entry | 35 in 30 minutes: no double booking, latency and cost recorded |
| T-17 | I-14 | Review | Code | Capacity, feasibility and ranking are code, not prompt |

Run cheap tests first (unit, tools, concurrency need no model). Use a fresh copy of the database for each run. Save every result.
