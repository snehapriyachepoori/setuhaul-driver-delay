# Status board

| Step | Status | Last updated | Open items | Gate passed? |
|---|---|---|---|---|
| 1 Problem framing | done | 27 Nov 2026 | Audit rewritten for the real schema (24 queries, 18 issues, 4 controls); results in audit_results_REAL.txt | Yes |
| 2 Cause and effect | needs update (light) | 27 Nov 2026 | Check mechanisms M1 to M4 against real data; M4 (UTC time) is not in the real data | Yes, with CHG-001 check |
| 3 Architecture (option B) | done, small updates | 27 Nov 2026 | Status words are UPPERCASE in the real DB; RULE005 is "no new start after 21:00", not "D5 closes 19:00"; SHP1015 ETA is 18:30 | Yes |
| 4 Build | in progress | 27 Nov 2026 | Steps 1-2 done; next step 3 (core rules, no model) | No |
| 5 Test and harden | not started | | | |
| 6 Observe | not started (bonus: measures table) | | | |
| 7 Client readout | not started | | | |

## Submission checklist (General Instructions.txt)
| # | Item | File | State |
|---|---|---|---|
| 1 | Problem sheet + data audit, each issue proved by a query | `docs/01_submission_problem_sheet.md`, `docs/01_audit_queries.sql`, `docs/audit_results_REAL.txt` | Ready (real data) |
| 2 | Decision register, 13 decisions with reason + evidence | `docs/03_decision_register.md` | Ready; entries marked **Test** get their numbers from the build |
| 3 | Working prototype, public GitHub repo, versions in README | this repo | Building |
| 4 | Scenario run ending in one escalation | `docs/scenario_run.md` + recording | Not started (SHP1015) |
| 5 | Integrity proof: no double booking | `docs/integrity_proof.txt` | Not started |
| 6 | One-page client readout (policy, limits, risks) | `docs/client_readout.md` | Not started |
| - | Filled template | `docs/05_submission_template_FILLED.md` | Last |
