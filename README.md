# Job application tracker

Personal workspace for internship and early-career applications. See `PRD.md` and `PLAN.md`.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Demo account: `demo` / `DemoPass123!`

SQLite is the default database. Set `DATABASE_URL` to a Postgres URL when you want PostgreSQL.

## Tests

```bash
python manage.py test
```

Password reset emails are printed to the terminal in development.
