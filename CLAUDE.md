# Project: SetuHaul driver-delay service (FDE challenge)

You are helping a learner BUILD this project. Teach as you go: explain each piece in plain words, let the learner write or run key parts, and review their code. Do not hide that AI assistance is used; the README must say so honestly.

## Read first, in this order
0. `00_START_HERE_HANDOFF.md` (everything in one file)
1. `03_architecture.md` (the design; sections 6 to 9 matter most)
2. `03_decision_register.md`
3. `03_build_and_test_guide.md` (the 12 build steps and test plan T-01 to T-17)
4. `01_submission_problem_sheet.md`, `01_audit_queries.sql`, `02_cause_effect.md`

## Current state
- Steps 1 to 3 (problem, cause and effect, architecture) are written. Build is next: start at build guide step 1, then steps 3 to 5 (no model needed).
- The database `dummy_setuhaul.db` is a SYNTHETIC stand-in (problems planted on purpose). The real SQLite file has not been supplied. Never present stand-in results as client findings. Rerun the audit with `python3 run_audit.py REAL.db` if the real file arrives.

## Decisions already made (do not change without asking)
- Single agent with stage-gated tools; a code-owned stage machine; plain code and database transactions own every commit. A rules-first workflow (option A) is the fallback if tool calling is unreliable.
- The model never decides capacity, feasibility, priority, commit or regulated rules.
- Slot states: shown (no reservation), held (exclusive, 5-minute expiry, partial unique index), pending approval, confirmed. Re-check inside the confirm transaction. Reply only after commit.
- SQLite WAL, `BEGIN IMMEDIATE`, foreign keys on every connection, new tables only, times as epoch numbers.
- Ranking policy P-1 to P-5 (architecture 9.6). Assumed values live in a config file, not in code or prompts.
- No RAG, no ML, no queue at this size.

## Model route
- One adapter over an OpenAI-style chat API. Two settings: Ollama (local, free) and OpenRouter (the learner has a key). No Claude API key in the project.
- Secrets only in a git-ignored `.env`. Never print or commit a key. Pick an OpenRouter model that lists tool calling and check its price on openrouter.ai/models.

## Rules for the work
- Pin library versions in `requirements.txt` and name them in the README.
- One command to run the demo (e.g. `make demo`).
- Must deliver: integrity test (10 threads, one slot, 100 repeats, 0 double bookings), a scenario run ending in one escalation (SHP1015), prototype README, one-page client readout.
- Assert conversation tests on tool calls and final state, not on wording.
- Say plainly what does not work yet.

## Added requirements (learner's request)
- Simple authentication inside the Python app (no AWS): a driver starts a session with their phone number, checked against `drivers`; a driver can only act on their own shipments. The coordinator hand-off view needs a PIN from `.env`. Be honest in the README that this is demo-level, not production security.
- Proof artifacts to produce: `docs/scenario_run.md` (saved transcript with tool calls and final database state, plus a short screen recording), and `docs/integrity_proof.txt` (test output with requests sent, bookings made, double bookings). Include a control run with the slot protection switched off that DOES double book, to show the test can fail.
- Submission is due in about one day. After the core build, do the extra-marks items in `04_bonus_marks_plan.md` in order (measures table, failure tests T-19 to T-24, competing-trucks replay, client readout from `06_client_readout_TEMPLATE.md`, LangSmith, optional scheduler). Fill `05_submission_template_FILLED.md` at the end. Skip WhatsApp and Streamlit.
