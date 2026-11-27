# Status board

| Step | Status | Last updated | Open items | Gate passed? |
|---|---|---|---|---|
| 1 Problem framing | done | 27 Nov 2026 | Audit rewritten for the real schema (24 queries, 18 issues, 4 controls); results in audit_results_REAL.txt | Yes |
| 2 Cause and effect | needs update (light) | 27 Nov 2026 | Check mechanisms M1 to M4 against real data; M4 (UTC time) is not in the real data | Yes, with CHG-001 check |
| 3 Architecture (option B) | done, small updates | 27 Nov 2026 | Status words are UPPERCASE in the real DB; RULE005 is "no new start after 21:00", not "D5 closes 19:00"; SHP1015 ETA is 18:30 | Yes |
| 4 Build | core done | 27 Nov 2026 | Steps 1-5, 7-9 done; 74 tests pass; real-model scenario passes. Open: screen recording, LangSmith (E5), scheduler (E6), cost workbook update, GitHub push | Yes, core |
| 5 Test and harden | partly | 27 Nov 2026 | T-01 to T-15 and T-18 automated; failure cases T-19 to T-24 covered inside tests/concurrency and tests/scenarios (no separate tests/failure folder) | No |
| 6 Observe | partly | 27 Nov 2026 | Audit row per turn; `docs/measures.md` (all nine); no LangSmith yet | No |
| 7 Client readout | draft | 27 Nov 2026 | `docs/client_readout.md` (one page, real numbers) | Learner to review |

## Submission checklist (General Instructions.txt)
| # | Item | File | State |
|---|---|---|---|
| 1 | Problem sheet + data audit, each issue proved by a query | `docs/01_submission_problem_sheet.md`, `docs/01_audit_queries.sql`, `docs/audit_results_REAL.txt` | Ready (real data) |
| 2 | Decision register, 13 decisions with reason + evidence | `docs/03_decision_register.md` | Ready; entries marked **Test** get their numbers from the build |
| 3 | Working prototype, public GitHub repo, versions in README | this repo, `README.md` | Built and tested; not yet pushed to GitHub |
| 4 | Scenario run ending in one escalation | `docs/scenario_run.md` + recording | Transcript ready (real model, SHP1015 escalates); recording still to make |
| 5 | Integrity proof: no double booking | `docs/integrity_proof.txt` | Ready: 1,000 / 100 / 0; control double-books |
| 6 | One-page client readout (policy, limits, risks) | `docs/client_readout.md` | Draft ready |
| - | Filled template | `docs/05_submission_template_FILLED.md` | Filled except repo and video links |
