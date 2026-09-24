# Gmail → Google Sheet plugin

This lives **inside** the internship tracker spreadsheet (or a copy of it). It is not a separate website.

It searches Gmail for application confirmations and later recruiter mail, then fills:

| Tab | Columns |
| --- | --- |
| `internships` | Date Applied, Company, Role, Location, Season, Result, Notes |
| `newgrad` | Date Applied, Company, Role, Location, Result, Notes |

Result values: Applied, OA, Interview, Offer, Rejected.

## Install (once)

1. Open the spreadsheet while signed into the **same Google account as your Gmail**.
2. **Extensions → Apps Script**.
3. Delete any stub code. Copy [`Code.gs`](Code.gs) and [`appsscript.json`](appsscript.json) from this folder into the script project.
4. Save, go back to the sheet, reload.
5. Menu **Tracker → Sync Gmail now**. Approve Gmail (read-only) and this spreadsheet.
6. **Tracker → Install hourly sync**.

Use **Tracker → Sync Gmail now** anytime you want an immediate pass.

## What it does / skips

- Confirmation mail (`thank you for applying`, `application received`) adds a row, or fills the next blank Company row so your dropdowns stay intact.
- OA / interview / offer / reject mail updates **Result** on the matching company. It will not smash an Offer with a Rejected email.
- Intern / co-op mail goes to `internships` (Season defaults to Summer 2027). New-grad mail goes to `newgrad`.
- Each Gmail message is recorded on a hidden `_gmail_log` tab so it is not applied twice.
