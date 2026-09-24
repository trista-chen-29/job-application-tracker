# Job application tracker

Gmail fills your existing Google Sheet. Application confirmation emails become new rows; later recruiter mail updates **Result** (OA, Interview, Offer, Rejected).

The live tracker is the spreadsheet, not the Django site. Tabs:

| Tab | Columns |
| --- | --- |
| `internships` | Date Applied, Company, Role, Location, Season, Result, Notes |
| `newgrad` | Date Applied, Company, Role, Location, Result, Notes |

Default season for internships is **Summer 2027**. New-grad mail goes to `newgrad`.

## Sheet plugin (use this)

Runs inside Google Sheets. No server, no deploy.

1. Open the spreadsheet while signed into the **same Google account as Gmail**.
2. **Extensions → Apps Script**.
3. Replace the stub with [`sheets-addon/Code.gs`](sheets-addon/Code.gs).
4. In **Project Settings**, enable `appsscript.json` and replace it with [`sheets-addon/appsscript.json`](sheets-addon/appsscript.json).
5. Save, return to the sheet, reload.
6. Menu **Tracker → Sync Gmail now**. Approve Gmail (read) and this spreadsheet.
7. **Tracker → Install hourly sync**.

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
