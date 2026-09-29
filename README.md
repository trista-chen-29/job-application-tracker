# Job application tracker

Gmail fills your existing Google Sheet. Application confirmation emails become new rows; later recruiter mail updates **Result** (OA, Interview, Offer, Rejected).

The live tracker is the spreadsheet, not the Django site. Tabs:

| Tab | Columns |
| --- | --- |
| `internships` | Date Applied, Company, Role, Location, Season, Result, Notes |
| `newgrad` | Date Applied, Company, Role, Location, Result, Notes |

Result values: Applied, Rejected, OA, Interview, Offer. Season values: Winter 2027, Spring 2027, Summer 2027.

Season is **not invented**. It is filled only when the email names one of the three dropdown values; anything else (Fall 2027, Summer 2026, a bare "summer") leaves Season blank or keeps what you typed.

## Sync and recheck

The live tracker is the spreadsheet plugin.

- **Tracker → Sync Gmail now** reads new recruiter mail and also retries log rows whose parser version is old, whose status is `failed`/`review`, or that never finished applying.
- Matching is **company + role + season**. Two roles, or the same role in two seasons, stay separate rows. Confirmation mail fills blanks and can replace a machine-written role from an older parse. It does not wipe a location you typed or move Result backwards (Rejected never replaces Offer).
- **Tracker → Recheck scraped mail** walks stale `_gmail_log` rows in batches of 30. **Reprocess all stale mail** restarts that walk.
- A message ID in the log is not a permanent skip. Failed writes stay `failed` and are retried. Ignored mail (no company/status) is stored separately from failures.
- Paste the latest [`sheets-addon/Code.gs`](sheets-addon/Code.gs) after pulling parser changes. The current parser version is **11**.
- **Sync Gmail now** walks every matching thread (not just the newest 50), oldest first, and stops before the 6-minute Apps Script limit. Auto-sync (every 10 minutes) picks up anything left, then only scans the last 7 days.
- Rows are kept in **Date Applied** order, earliest first, after every sync. Rows without a date go after dated rows. **Tracker → Sort by Date Applied** re-sorts on demand.
- Date Applied comes only from the confirmation email. Follow-up mail without a role (OA, rejection) updates the row in whatever tab it is already in.
- Blank Role cells are highlighted light blue and blank Location cells yellow. Your own replies, job alerts, and anything in `CONFIG.ignoreCompanies` are skipped.
- The Django app uses a Python port of the same extraction ([`tracker/services/extract.py`](tracker/services/extract.py)); keep the two in step when changing either.
- Opening the sheet syncs Gmail through an installable on-open trigger. The simple `onOpen` only adds the **Tracker** menu and cannot read Gmail. The 10-minute trigger remains as a backup. **Turn off auto-sync** removes both.
- If the menu does not appear, pick `installTracker` in the Apps Script editor and click **Run** once, then approve Gmail, the spreadsheet, and trigger permissions. `appsscript.json` must include the `script.container.ui` scope. Reload the sheet after that. `node sheets-addon/parse_check.js` checks the Apps Script parser without Google.

## Switching to a new spreadsheet

1. In the new spreadsheet, create tabs `internships` and `newgrad` with the headers above. Pre-filled Season/Result dropdowns are fine.
2. Open **Extensions → Apps Script** *in the new spreadsheet* (the script is bound to one sheet) and paste `Code.gs` + `appsscript.json`. Save and reload.
3. **Tracker → Sync Gmail now**, then **Tracker → Recheck scraped mail** until it reports nothing left. The new sheet gets its own empty `_gmail_log`, so every email is processed again.
4. Local Django app only: paste the new sheet URL on the Gmail page. Saving a different sheet marks logged mail as stale so the next sync writes it to the new sheet.

## Sheet plugin (use this)

Runs inside Google Sheets. No server, no deploy.

1. Open the spreadsheet while signed into the **same Google account as Gmail**.
2. **Extensions → Apps Script**.
3. Replace the stub with [`sheets-addon/Code.gs`](sheets-addon/Code.gs).
4. In **Project Settings**, enable `appsscript.json` and replace it with [`sheets-addon/appsscript.json`](sheets-addon/appsscript.json).
5. Save, return to the sheet, reload.
6. Menu **Tracker → Sync Gmail now**. Approve Gmail (read) and this spreadsheet.
7. Done. The first sync turns on auto-sync: opening the sheet syncs Gmail, and a 10-minute trigger is the backup (**Tracker → Turn off auto-sync** removes both).

Details and behavior notes: [`sheets-addon/README.md`](sheets-addon/README.md).

It fills the first blank **Company** cell so pre-filled Result dropdowns stay in place. Each message is logged on a hidden `_gmail_log` tab so it is not applied twice. An **Offer** is not overwritten by a rejection.

## Optional local app

A small Django page can push the same rows if you connect Gmail there.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver 127.0.0.1:8002
```

Open http://127.0.0.1:8002/ , sign in, paste the Google Sheet URL, then **Connect Gmail**.

OAuth scopes: Gmail readonly and Google Sheets. Redirect URI must match Google Cloud exactly:

`http://127.0.0.1:8002/gmail/callback/`

Put client id/secret in `.env` (never commit `.env`). Demo login if you seeded: `demo` / `DemoPass123!`.

```bash
python manage.py test
```
