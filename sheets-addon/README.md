# Gmail → Google Sheet plugin

This lives **inside** the internship tracker spreadsheet (or a copy of it). It is not a separate website.

It searches Gmail for application confirmations and later recruiter mail, then fills:

| Tab | Columns |
| --- | --- |
| `internships` | Date Applied, Company, Role, Location, Season, Result, Notes |
| `newgrad` | Date Applied, Company, Role, Location, Result, Notes |

Result values: Applied, Rejected, OA, Interview, Offer. Season values: Winter 2027, Spring 2027, Summer 2027 (`CONFIG.seasonOptions`).

## Install (once)

1. Open the spreadsheet while signed into the **same Google account as your Gmail**.
2. **Extensions → Apps Script**.
3. Delete any stub code. Copy [`Code.gs`](Code.gs) and [`appsscript.json`](appsscript.json) from this folder into the script project.
4. Save, go back to the sheet, reload.
5. Menu **Tracker → Sync Gmail now**. Approve Gmail (read-only) and this spreadsheet.
That first sync also turns on **auto-sync**: Gmail is checked every 10 minutes (`CONFIG.syncEveryMinutes`), even when the sheet is closed. New applications, OAs, and rejections show up on their own.

Use **Tracker → Sync Gmail now** anytime you want an immediate pass. **Tracker → Turn off auto-sync** stops the timed runs (a manual sync will not turn it back on); **Turn on auto-sync** resumes them.

## What it does / skips

- Confirmation mail (`thank you for applying`, `application received`) adds a row, or fills the next blank Company row so your dropdowns stay intact.
- OA / interview / offer / reject mail updates **Result** on the matching company. It will not smash an Offer with a Rejected email.
- Intern / co-op mail goes to `internships`. Season is filled only when the email names a value from the Season dropdown (Winter/Spring/Summer 2027). Other seasons or years are left blank rather than written as invalid dropdown values.
- New-grad mail goes to `newgrad`.
- Rows are matched by company + role (and season when that is needed to tell two internships apart). The same company with two roles does not collapse into one row.
- New applications fill the first blank **Company** cell so dropdowns and formatting stay in place. Rows that only contain dropdowns count as blank. If every row is filled, a new row is appended with the previous row's formatting and dropdowns.
- After every sync, both tabs are sorted by **Date Applied**, earliest first. Rows with a company but no date go after the dated rows, and blank rows stay at the bottom. Whole rows move, so highlights and dropdowns stay with their row. **Tracker → Sort by Date Applied** does the same on demand, for example after you type a row by hand.
- Missing locations stay blank, are highlighted yellow, and are listed in the sync toast. A later email with a real location fills the cell and clears the highlight.
- A missing Role is left blank and highlighted light blue (`CONFIG.roleMissingColor`) so you can fill it in by hand.
- Company comes from the sender name (`Acme Talent Team`, `Workday Acme`, `Acme @ icims`), then phrases like "applying to X" / "role at X", then the email signature, then the sender domain. Job platforms (Greenhouse, Workday, Ashby, iCIMS, …) and recruiter personal names are never used as the company.
- Your own replies (mail from gmail.com and similar) and newsletters/job alerts are ignored. Companies listed in `CONFIG.ignoreCompanies` (for example on-campus student jobs) are never added.
- Result only moves forward: Applied → OA → Interview → Offer, with Rejected allowed from any step except Offer. Polite lines such as "unfortunately we can't reply to everyone" in a confirmation do not count as a rejection.
- Role titles drop job IDs, seasons (the Season column holds that), and a trailing city.
- Notes keep the useful recruiter line plus a `Source:` Gmail thread URL. A source-email column is used when present.
- Hidden `_gmail_log` stores message_id, thread_id, parser_version, parse_status, and application_key. Existing three-column logs are migrated in place.
- **Tracker → Sync Gmail now** reads new mail and any stale/failed log rows. A message is marked applied only after parse + row write succeed.
- **Tracker → Recheck scraped mail** reprocesses a batch of stale messages (older parser_version, failed, or review). **Reprocess all stale mail** resets the batch offset and does the same.
- **Sync Gmail now** walks every matching thread oldest first and stops before the 6-minute limit; auto-sync picks up the rest on its next run. After a full pass, runs only scan mail from the last 7 days (`CONFIG.recentDays`). Bumping the parser version triggers one more full pass.
- A lock keeps a timed run and a menu click from writing at the same time, so they cannot add the same row twice.
- Date Applied comes only from the confirmation email. Follow-up mail without a role never moves a row between tabs.
- No **Tracker** menu after reload? In the Apps Script editor, choose `installTracker` in the function dropdown and click **Run** once.
- Parser version is 10. Bump it in `Code.gs` whenever parse or merge behavior changes.
