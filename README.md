# SetuHaul driver-delay service (FDE challenge prototype)

A chat service where truck drivers report delays and rebook dock slots **without double bookings or false promises**. Built on the real SetuHaul snapshot (`data/setuhaul_original.db`, 4 Aug 2026, Jaipur and Gurugram).

> **AI assistance, stated plainly:** this project was built with an AI coding assistant (Claude, via Claude Code) pairing with me. The assistant wrote most of the code and tests to my design documents. I ran every command, reviewed the code, and can explain each part. The model the *service itself* uses at run time is a separate choice (see "Model" below).

## The idea in one paragraph
The language model only **talks and calls tools**. Plain code and database transactions decide everything that matters: which slots are feasible, how they are ranked, who gets a contested slot, and whether a booking is committed. A code-owned **stage machine** decides which tools the model may even see at each moment. A slot is never "yours" until a `BEGIN IMMEDIATE` transaction has re-checked it and committed, and the reply is built only from the committed result.

```
driver message -> entry checks (dedupe, mask phone, safety, injection) -> stage machine
   -> LangGraph agent <-> typed tools (max 6 calls a turn) -> capacity module (code) -> SQLite
   -> output guard (no unbacked "confirmed", every time grounded in a tool result) -> reply
   -> hand-off record for a coordinator when needed
```

## Run it (Windows; one command per task)
```
C:\Users\<you>\venvs\setuhaul\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        (then fill OPENROUTER_API_KEY and COORDINATOR_PIN; never commit .env)
python run.py demo            tests + integrity proof + scenario run
```
| Command | What it does | Needs a model key? |
|---|---|---|
| `python run.py test` | All model-free tests: unit, tools, concurrency (100-repeat race), conversations with the rules model, failure tests | No |
| `python run.py failure` | Failure tests T-19 to T-24 only, saved to `docs/failure_tests.txt` | No |
| `python run.py integrity` | Writes `docs/integrity_proof.txt` (about 2 minutes) | No |
| `python run.py scenario` | SHP1013 rebooking + SHP1015 escalation, writes `docs/scenario_run.md` | Yes (or add `--model rules`) |
| `python run.py chat` | Talk to it as a driver; sign in with a snapshot phone such as `+91-9000010013` | Yes (or `--model rules`) |
| `python run.py coordinator` | Coordinator hand-off view; asks for `COORDINATOR_PIN` | No |
| `python run.py audit` | Rerun the data audit (`docs/audit_results_REAL.txt`) | No |
| `python scripts/competing_trucks.py` | Five trucks, two free slots: `docs/competing_trucks.md` | No |
| `python scripts/measures.py` | The nine measures: `docs/measures.md` (run the scenario first) | No |

Windows has no `make`, so `run.py` is the one-command runner. The original database is never written: every run works on a copy (`data/work_*.db`, git-ignored). If OneDrive locks a database file during the race test, pause OneDrive syncing.

## Model
- One adapter, `src/agent/llm.py`, over an OpenAI-style chat API. `MODEL_ROUTE` in `.env` picks: `openrouter` (used for the recorded run: `anthropic/claude-haiku-5.5`, fallback `openai/gpt-4o-mini`), `ollama` (local, free), or `rules` (no model: the option A fallback, deterministic rules + templates; also the free fake model in tests).
- 15-second timeout, then the fallback model, then a coordinator hand-off with a truthful "your booking is unchanged".
- Measured in the scenario run: 14 model calls, about 35,000 tokens in and 2,250 out for 6 driver messages.

## Pinned versions (full list in `requirements.txt`)
Python 3.13.5, SQLite 3.49.1, langgraph 1.2.24, langgraph-checkpoint-sqlite 3.1.3, langchain-core 1.8.5, pydantic 2.14.4, openai 3.60.0, python-dotenv 1.2.4, pytest 9.2.0.

## Results
| Deliverable | File | Result |
|---|---|---|
| Problem sheet + audit | `docs/01_submission_problem_sheet.md`, `docs/01_audit_queries.sql` | 18 issues on the real data, each proved by a query |
| Decision register | `docs/03_decision_register.md` | 19 decisions, test evidence filled in |
| Integrity proof | `docs/integrity_proof.txt` | 1,000 requests / 100 bookings / **0 double bookings**; control run without protection: 900 double bookings |
| Scenario run | `docs/scenario_run.md`, [video](https://drive.google.com/file/d/1S-sx1aLPULcVHeY2Bkw-VIneLmCg2PQr/view?usp=sharing) | SHP1013 rebooked to D1 13:00; SHP1015 ends in **one complete escalation** |
| Measures | `docs/measures.md` | All nine measures, with what cannot be measured said plainly |
| Competing trucks | `docs/competing_trucks.md` | 0 policy violations in both replays |
| Client readout | `docs/client_readout.md` | One page |

## Where things live
| Path | What it is |
|---|---|
| `config/policy.toml` | Every assumed number (margins, hold time, approval threshold, protected-slot rule, deadlines), with its owner |
| `src/db.py`, `src/migrate.py` | Safe connection (foreign keys, WAL, busy timeout); new tables only, partial unique index on live holds, append-only audit |
| `src/capacity/eta.py` | One resolved ETA with source and confidence; margin by confidence |
| `src/capacity/feasibility.py` | Ten checks + weight + dock events overriding slot status, each with a reason code |
| `src/capacity/ranking.py` | Policy P-1 to P-5 |
| `src/capacity/commit.py` | `hold_slot`, `confirm_booking`, `release_hold`: one `BEGIN IMMEDIATE` transaction each, idempotent |
| `src/capacity/handoff.py` | Complete hand-off record, owner, deadline, acknowledge |
| `src/stages.py` | Stage machine and the tool allowlist per stage |
| `src/tools/core.py` | Eight typed tools and `dispatch` (stage gate, validation, ownership, errors as data) |
| `src/agent/` | Model adapter, prompt (`prompts/system_v1.md`), rules model, LangGraph graph |
| `src/guardrails/input.py` | Phone masking, safety cues, injection screen, explicit-yes check |
| `src/auth.py` | Demo-level login (phone number, coordinator PIN) |
| `tests/` | `unit`, `tools`, `concurrency`, `scenarios`, `failure` (93 tests) |

## Tests mapped to the test plan
| Test | Where |
|---|---|
| T-01 no double booking | `tests/concurrency/test_double_book.py` (+ control that must fail) |
| T-02 no promise before commit | `test_output_guard_blocks_unbacked_confirmation` |
| T-03 stale option refused | `test_stale_option_refused_at_confirm` |
| T-04 duplicate message | `test_duplicate_message_acts_once`, `test_same_key_twice_returns_same_answer_and_books_once` |
| T-05 partial failure | `test_failure_mid_commit_leaves_no_half_state` |
| T-06 feasibility | `tests/unit/test_feasibility.py` (SHP1010, SHP1013, SHP1014, SHP1015) |
| T-07 ETA | `tests/unit/test_eta.py` (Z time, LOW confidence, override, repair time) |
| T-08 right shipment | `test_two_loads_asks_which_one`, `test_other_drivers_shipment_refused` |
| T-09 safety first | `test_safety_first_no_slot_offered` |
| T-10 no-slot hand-off | `test_shp1015_ends_in_one_complete_escalation` |
| T-11 policy | `test_p3_protected_last_slot_kept_for_high_priority`, `scripts/competing_trucks.py` |
| T-12 approval routing | `test_far_move_is_shown_but_needs_approval`, `test_far_move_goes_to_approval_not_commit` |
| T-13 privacy | `test_resume_after_restart_and_no_phone_in_checkpoint` |
| T-14 connection | `tests/unit/test_db_and_migration.py` |
| T-15 memory | `test_resume_after_restart_and_no_phone_in_checkpoint` |
| T-18 auth | `tests/tools/test_tools.py` (unknown phone, other driver, PIN) |
| T-19 duplicate message (THR009) | `tests/failure/test_t19_duplicate_message.py` |
| T-20 option blocked after it was shown | `tests/failure/test_t20_stale_option.py` |
| T-21 crash in the middle of a rebooking | `tests/failure/test_t21_crash_mid_commit.py` |
| T-22 commit forced to fail | `tests/failure/test_t22_forced_commit_failure.py` |
| T-23 expired hold | `tests/failure/test_t23_expired_hold.py` (+ control inside 5 minutes) |
| T-24 wrong driver, unknown phone | `tests/failure/test_t24_wrong_driver.py` |

Failure tests T-19 to T-24 break things on purpose (crash, failed commit, blocked slot, late reply, wrong person) through the full conversation, not just the commit function. Output: `docs/failure_tests.txt`.

## Authentication (demo-level, NOT production security)
A driver starts a session with a phone number checked against `drivers.phone`; every tool checks the shipment belongs to that driver (MISMATCH otherwise, nothing revealed). The coordinator view needs `COORDINATOR_PIN` from `.env`. A typed phone number is not proof of identity: a real channel (for example WhatsApp) supplies a verified number. No rate limiting, no lockout, no session expiry.

## What does not work yet (plain)
- **Not built:** LangSmith tracing (E5), the optional facility scheduler (E6), a Streamlit coordinator console (a terminal view exists instead), WhatsApp.
- **Safety detection is a keyword list**, not a classifier. It will miss unusual wording and may over-trigger.
- **The rules model (option A)** understands only simple English and romanised Hindi.
- **Priority at today's size is first-hold-wins.** A NORMAL truck can beat a CRITICAL truck to a slot if it holds first (shown in `docs/competing_trucks.md`). P-5 priority ordering needs the per-facility queue planned for the pilot.
- **The output guard checks times and the word "confirmed"**, not dock names.
- **Real-model runs vary.** Tool paths matched the expected path in the recorded run after one prompt fix; an earlier run asked an extra question and fell out of step with the script.
- Approval triggers "after 21:00" (RULE005) and "another day" are coded but cannot occur on this snapshot (no such slots), so only the "more than 3 hours later" trigger is exercised by tests.
- Unload longer than the slot is treated as blocking the next slot on that dock (an assumption; real unload times are unknown).
- All policy numbers in `config/policy.toml` are **assumptions** awaiting the named owner's decision.
- **A repeated message on a NEW thread is not flagged as a repeat** (the real THR009 case: new thread, new channel id). It only shows options again; nothing is booked unless the driver picks and says yes again (T-19).
- **After a failed commit the driver is told "a coordinator can help", but no hand-off row is created** and the conversation stays at CONFIRM. Nothing is booked and "confirmed" is never said (T-22), but no coordinator is actually alerted.
- The snapshot database is committed so the demo runs; it contains the challenge's sample driver phones.
