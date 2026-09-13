# Implementation plan

## Repository inspection

The workspace at `/Users/trista/job` is a git repository with **no commits and no application code**. There is no existing Django project, models, routes, templates, or tests to preserve.

Decision: bootstrap a new Django 6 project in this directory instead of wrapping a prior app.

## Stack (V1)

| Area | Choice | Why |
| --- | --- | --- |
| Backend | Django 6 + Django templates + HTMX | PRD prefers the simpler option; no React in repo |
| API | No DRF in V1 | JSON export via Django views is enough |
| Database | SQLite by default; PostgreSQL via `DATABASE_URL` | Local/tests run without Postgres; production-ready setting remains |
| Auth | `django.contrib.auth` | Email/password, reset, logout, account deletion |
| Files | Local `MEDIA_ROOT` | Configurable later for object storage |
| Matching | `tracker/services/matching.py` | Deterministic, replaceable, no LLM |
| Jobs | None | No Celery |

## Schema (Django models)

All user-owned rows use an explicit `user` FK (or a parent that is user-owned) plus queryset scoping in views.

- `Profile` — 1:1 with User
- `ProfileTrack` — skills/keywords/pitch per target track
- `Skill` — user-owned skill catalog (name + normalized name)
- `ProfileSkill` — track/profile skill with proficiency and evidence
- `Experience`, `Project`
- `ApplicationMaterial`
- `Opportunity` — pipeline status, priority, selected track, cached match fields
- `OpportunitySkill` — required/preferred
- `Application` — 1:1 with opportunity
- `ApplicationMaterialSnapshot`
- `StatusHistory`
- `ChecklistItem`
- `Contact`, `ContactInteraction`
- `Task`
- `InterviewStage`, `InterviewNote`
- `SavedTemplate`

## Phases

1. **Foundation** — settings, auth, layout, models, migrations
2. **Core tracker** — opportunity CRUD, status pipeline, filters, tasks, dashboard
3. **Materials and matching** — tracks, materials, explainable match, snapshots
4. **Networking and interviews** — contacts, templates, follow-ups, interview notes
5. **Quality** — CSV/JSON/Markdown export, CSV import, analytics, tests, seed data

## Ambiguous requirements — smallest V1 choices

- Job-description “extraction” is rule-based (deadlines, location keywords, skill lines), not an LLM.
- Duplicate detection: same user + exact URL, or normalized company+title, or high description similarity.
- Match categories: Strong ≥ 70, Possible ≥ 40, Weak otherwise; unknown sponsorship is excluded from the weighted score (not treated as good or bad).
- Metrics with fewer than 5 applications in the selected range show “Not enough data”.
- Password reset uses the console email backend in development.

## Out of scope (per PRD)

Scraping, auto-apply, auto-send messages, LLM rewriting, LinkedIn login.
