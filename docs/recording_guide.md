# How to record the scenario run video (submission item 4)

**Length:** 4 to 6 minutes. **Time to make it:** about 15 minutes, including one practice run.

## What the video must prove (and why)
The brief asks for a scenario run that **ends in one escalation**. The video shows a reviewer three things the text files cannot:
1. **It really runs** on your laptop, live, against the real SetuHaul data, with a real model.
2. **The model talks, code decides.** On screen you see every tool call (`[tool ... -> STATUS]`) and the stage (`[stage OFFER]`). The model never books anything itself.
3. **The hard case goes to a person.** SHP1015 cannot be served safely, so code hands it to a coordinator instead of inventing a slot. The coordinator view shows the complete record.

The written transcript (`docs/scenario_run.md`) is the backup proof; the video is the live proof.

## Before you press record (do this once, about 3 minutes)
1. Open **PowerShell** (or the VS Code terminal) and go to the project:
   ```
   cd C:\Users\91798\OneDrive\Desktop\FDE\setuhaul-project
   C:\Users\91798\venvs\setuhaul\Scripts\activate
   ```
   You should see `(setuhaul)` at the start of the line.
2. Make the text big enough to read in a video: **Ctrl + Plus** a few times in the terminal.
3. Close anything private on screen (email, chat, browser tabs). **Never open `.env` on camera**: it holds your API key.
4. Do one practice run of scenes 2 to 4 below without recording, so nothing surprises you.

## Start the recorder
- **Easiest:** press **Win + Alt + R** (Xbox Game Bar) to start and stop. The file goes to `Videos\Captures`.
- **Or:** Snipping Tool, then the video camera icon, then select the terminal window.
- Turn the microphone on if you want to speak the lines below (recommended; it shows you understand it).

## Scene 1: the safety net (30 seconds)
**Type:**
```
type docs\integrity_proof.txt
```
**Say:** "Before any chat, this is the proof that two drivers can never get the same slot. Ten trucks raced for one slot a hundred times: a thousand requests, a hundred bookings, zero double bookings. With the protection switched off, the same test double-booked nine hundred times, so the test really can fail."

## Scene 2: a normal delay, rebooked (90 seconds)
**Type:**
```
python run.py chat --fresh
```
- `--fresh` starts from a clean copy of the SetuHaul database (the original file is never touched). The scenario clock starts at **10:00 on 4 Aug 2026**, the day of the snapshot.

| You type | What you should see | What to say |
|---|---|---|
| `+91-9000010013` | `Signed in as Kailash Gurjar (******0013)` | "The driver signs in with their phone. It is checked against the drivers table, and the number is masked everywhere after this." |
| `Late` | `[tool resolve_shipment -> UNIQUE]`, then a question about when they reach the gate. `[stage CLARIFY]` | "The message is vague, so it finds the driver's shipment and asks only for the one thing it does not know: the arrival time." |
| `I will reach the gate at 11:40` | `record_eta_declaration -> RECORDED`, `get_feasible_slots -> OPTIONS`, three slots, "nothing is reserved yet" | "Code, not the model, ran every check: dock type, weight, dock breakdowns, opening hours, 30 minutes of safety margin. These are the only slots that pass." |
| `1` | `hold_slot -> HELD`, held until about 5 minutes later, "not booked yet" | "Choosing an option only holds it for five minutes. It is not a booking yet." |
| `yes` | `confirm_booking -> CONFIRMED`, `[stage DONE]` | "Only after a clear yes does code re-check the slot inside one database transaction and commit. The old booking is cancelled in the same transaction." |
| `quit` | back to the prompt | |

## Scene 3: the escalation, SHP1015 (90 seconds)
**Type** (no `--fresh` this time, so scene 2's booking stays; the clock moves to 16:30):
```
python run.py chat --now 2026-08-04T16:30:00+05:30
```

| You type | What you should see | What to say |
|---|---|---|
| `+91-9000010015` | `Signed in as ... (******0015)` | "Now the hard case: a refrigerated load." |
| `SHP1015 reefer is delayed, I will reach Jaipur at 18:30. Any slot?` | `resolve_shipment -> UNIQUE`, `record_eta_declaration -> RECORDED`, `get_feasible_slots -> NO_FEASIBLE_SLOT`, `[stage ESCALATE]`, and a reply that a coordinator will contact them, with the booking unchanged | "This load needs a refrigerated dock. D5 is the only one at Jaipur, and it is under maintenance from 18:00 to 22:00. The truck arrives at 18:30, so there is no safe slot. Instead of inventing one, code created a hand-off for the Jaipur coordinator with a 15-minute deadline." |
| `Is there anything at all tonight?` | No tool calls; "A coordinator has your case..." | "Once a person owns the case, the assistant stops changing anything. It cannot be talked into a booking." |
| `quit` | | |

## Scene 4: what the coordinator sees (60 seconds)
**Type:**
```
python run.py coordinator --db data/work_chat.db
```
- It asks for the **PIN** from your `.env`. Typing is hidden, which is normal. A wrong PIN is refused.
- You should see the hand-off: reason `NO_FEASIBLE_SLOT`, shipment SHP1015, owner `CON001 (WAREHOUSE_COORDINATOR)`, the deadline, `missing fields: none`, the reason counts, and what was **not** done.

**Say:** "The coordinator gets the full picture: what the driver said, the arrival time and how sure we are, why every slot failed, and what the system did not do. Nobody has to call the driver back to ask again. Today, the real email about this exact load failed to send."

Type the hand-off id to acknowledge it (optional), then stop the recorder (**Win + Alt + R** again).

## Closing line (10 seconds)
"So: the model talks, code decides, the database guarantees one booking per slot, and anything unsafe goes to a person with a complete record."

## If something goes wrong
| Problem | What it means | Fix |
|---|---|---|
| `(setuhaul)` not shown, or `No module named ...` | Environment not active | Run the `activate` line again |
| `Sorry, that number is not registered` | Phone typed wrong | Retype it; any format works, such as `9000010013` |
| The agent asks an extra question instead of showing slots | The model wording varies a little between runs | Answer it naturally (for example `yes, show options`); the tool calls are what matter |
| `A coordinator has been asked to contact you` straight away | The model could not be reached (internet or key) | Check the internet and rerun. To record without a model: add `--model rules` to the chat command (same tools and checks, template replies) |
| `database is locked` | OneDrive is syncing the database file | Pause OneDrive syncing, then rerun |
| Coordinator view says `No open hand-offs` | Scene 3 not run on the same database, or already acknowledged | Rerun scene 3 without `--fresh`, then scene 4 |

## After recording
1. Watch it once: is the text readable, and is no key or `.env` visible?
2. Upload it to **Google Drive** (sharing: "Anyone with the link can view") or **YouTube as Unlisted**.
3. Send the link to the assistant. It goes into `docs/snehapriya_submission.md` (item 4), and the repo is pushed.
