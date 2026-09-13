# Product Requirements Document: Job Application Tracker

## 1. Product overview

Build a clean, personal job-search workspace for students and early-career professionals applying to internships and new-grad roles.

The product sits above job boards, referrals, career fairs, and networking channels. It does not need to be another job-discovery website. Its main purpose is to help a user decide which opportunities deserve attention, prepare stronger application materials, submit applications consistently, and follow up without losing information.

The product must be major-agnostic. It should support users from software, hardware, business, design, science, and other fields by using neutral terms such as “profile,” “skills,” and “application materials.”

## 2. Problem statement

Students and early-career applicants often apply through multiple sources and manage the process with scattered browser tabs, notes, spreadsheets, resume files, and LinkedIn messages. This creates several problems:

- They lose track of where and when they applied.
- They submit the wrong resume or forget which version was used.
- They spend too much time applying to poor-fit roles.
- They cannot quickly tell whether a position matches their skills, location, work authorization, sponsorship needs, or graduation timeline.
- They forget recruiter, employee, alumni, and career-fair follow-ups.
- They prepare for interviews without preserving the job description, required skills, recruiter questions, or notes.
- They do not know whether their problem is targeting, application quality, networking, or interviewing because they have no useful search metrics.

The solution should reduce this friction through a single, explainable workflow.

## 3. Product goals

### Primary goals

1. Give users one reliable place to manage every target role and application.
2. Help users prioritize roles using transparent job–profile matching.
3. Make it easy to select and record the correct application-materials version.
4. Organize networking, recruiter conversations, career-fair contacts, and follow-ups.
5. Preserve interview preparation notes and next actions for each opportunity.
6. Show practical metrics that help users improve their search process.

### Non-goals for V1

- Automatically applying to jobs.
- Scraping LinkedIn or other websites in a way that violates their terms.
- Replacing LinkedIn, Indeed, company career pages, or referral networks.
- Automatically sending messages or emails.
- Making employment, immigration, or sponsorship guarantees.
- Building a complex AI chatbot before the core tracker works.

## 4. Target users

### Primary user

A student or early-career professional applying to internships, co-ops, apprenticeships, or new-grad positions.

### Example user profile for development and testing

- Software Engineering student.
- Applying to software, embedded systems, systems, test, robotics, and semiconductor roles.
- Wants a combined resume for career fairs but may maintain specialized resume versions.
- May need employer sponsorship and wants sponsorship information recorded as a user-verified field, not an assumed fact.
- Wants concise, practical recruiter-facing preparation.

## 5. Core product principles

- Clean: the user should understand the next action immediately.
- Explainable: every score or recommendation should show why it was produced.
- User-controlled: the user owns the data and confirms important information.
- Action-oriented: each opportunity should have a clear next step.
- Evidence-based: do not invent job requirements, sponsorship policies, or recruiter details.
- Lightweight: recording an opportunity should take less than two minutes.

## 6. MVP user journey

1. User creates a profile with education, graduation date, target role types, locations, work authorization, sponsorship preference, skills, projects, experience, and application materials.
2. User adds a job manually by pasting a URL and job description or entering the fields directly.
3. The system extracts or stores title, company, location, work arrangement, requirements, preferred skills, degree requirements, application deadline, and source.
4. The system calculates an explainable match summary.
5. User reviews the match, selects a priority, and chooses the application-materials version.
6. User applies externally and changes the opportunity status to Applied.
7. User records contacts, messages, recruiter questions, and a follow-up date.
8. User adds interview stages and preparation notes if contacted.
9. Dashboard shows overdue actions, upcoming follow-ups, pipeline status, and search metrics.

## 7. Functional requirements

### 7.1 Authentication and account

- Email/password authentication for V1.
- Password reset.
- User data must be isolated by account.
- Logout and account deletion.
- Do not require LinkedIn or job-board login.

### 7.2 Profile management

Users can create and edit:

- Name and contact information.
- School, degree, major or field, and graduation date.
- Preferred role categories.
- Preferred locations and remote/hybrid/on-site preference.
- Work authorization status.
- Sponsorship requirement or preference.
- Skills with proficiency or evidence notes.
- Projects, work experience, coursework, certifications, and achievements.
- Short professional pitch.

The profile should support multiple target tracks, for example “Software,” “Embedded/Systems,” and “Test/Validation.” Each track can have different skills, keywords, pitch, and preferred materials.

### 7.3 Application materials

Users can store and label:

- Resume versions.
- Cover letters.
- Portfolio or project links.
- Transcript or other supporting documents.
- A short pitch.
- Recruiter questions.
- Interview stories or notes.

Each material should include a name, type, target role track, upload/link, created date, and optional notes. When an application is created, the selected material versions must be snapshotted or referenced so the user knows exactly what was used.

### 7.4 Opportunity management

Users can create, edit, archive, duplicate, and delete opportunities.

Required opportunity fields:

- Job title.
- Company or organization.
- Job URL.
- Source: company site, LinkedIn, Indeed, referral, career fair, recruiter, professor, alumni, or other.
- Location.
- Work arrangement.
- Role type: internship, co-op, new grad, contract, part-time, or full-time.
- Posting date and application deadline when known.
- Job description.
- Required skills.
- Preferred skills.
- Degree, graduation, and experience requirements.
- Sponsorship information: unknown, appears available, not available, or user verified.
- Salary or compensation when known.
- Notes.

The system should detect possible duplicates using company, title, URL, and similar job-description text.

### 7.5 Status pipeline

Supported statuses:

- Saved.
- Researching.
- Preparing.
- Applied.
- Recruiter Contacted.
- Recruiter Screen.
- Online Assessment.
- Interviewing.
- Offer.
- Accepted.
- Rejected.
- Withdrawn.
- Closed/Expired.

Users can move an opportunity between statuses using a board view or detail page. Every status change should record a timestamp and optional note.

### 7.6 Job–profile matching

V1 should provide an explainable match summary, not an opaque AI score.

The system should compare the opportunity with the selected profile track using:

- Required-skill overlap.
- Preferred-skill overlap.
- Role-title/category alignment.
- Education and graduation compatibility.
- Location and work-arrangement compatibility.
- Work authorization and sponsorship compatibility.
- Experience level.
- Evidence from the user’s projects, experience, coursework, or certifications.

Display:

- Overall match category: Strong, Possible, or Weak.
- Matching strengths.
- Missing or uncertain requirements.
- Potential blockers.
- Recommended application track.
- Suggested resume/material keywords, only when supported by the job description and user profile.
- A short “why this recommendation” explanation.

Do not claim that a company sponsors the user unless the user verifies the information. Mark unknown values clearly.

### 7.7 Application preparation checklist

Each opportunity should have a checklist that can be customized:

- Read and saved the job description.
- Confirmed eligibility.
- Checked location and work arrangement.
- Checked sponsorship/work authorization information.
- Selected resume version.
- Selected supporting materials.
- Tailored relevant bullets or keywords.
- Prepared short pitch.
- Submitted application.
- Recorded confirmation number.
- Added networking contact.
- Scheduled follow-up.

### 7.8 Networking and contacts

Users can add contacts connected to an opportunity:

- Name.
- Organization.
- Role/title.
- Relationship: recruiter, employee, alumni, professor, career-fair contact, referral, or other.
- Profile/contact link.
- Communication channel.
- Last contact date.
- Next follow-up date.
- Message or conversation notes.
- Referral status.

The system should show short reusable message templates, but users must review and send them manually.

### 7.9 Tasks and follow-ups

Users can create tasks linked to an opportunity or contact.

Task fields:

- Task title.
- Due date.
- Priority.
- Type: apply, tailor materials, research, message, follow up, interview preparation, thank-you note, or other.
- Completion status.
- Notes.

Dashboard should surface overdue and upcoming tasks first.

### 7.10 Interview preparation

For opportunities that reach screening or interviews, users can store:

- Interview stage and date.
- Interviewer names and roles.
- Interview format.
- Topics to prepare.
- Technical questions.
- Behavioral questions.
- Questions to ask the employer.
- STAR examples.
- Interview notes.
- Thank-you message status.
- Next step and expected response date.

### 7.11 Dashboard and analytics

Dashboard cards should include:

- Applications by status.
- Applications this week and month.
- Overdue follow-ups.
- Upcoming interviews.
- Opportunities needing action.
- Strong-match opportunities not yet applied to.
- Response rate.
- Interview conversion rate.
- Offer conversion rate.
- Results by source, role track, company type, location, and resume version.

Analytics must explain the calculation and support date-range filtering. Do not show misleading metrics when the sample size is too small; display “Not enough data” where appropriate.

### 7.12 Search, filters, and views

Users can search and filter by:

- Company.
- Job title.
- Status.
- Match category.
- Priority.
- Role track.
- Source.
- Location.
- Work arrangement.
- Sponsorship status.
- Deadline.
- Follow-up date.
- Date added.

Required views:

- Dashboard.
- Opportunity table.
- Kanban pipeline.
- Opportunity detail.
- Contacts.
- Tasks.
- Profile/materials.
- Analytics.

### 7.13 Import and export

V1 should support:

- CSV import for existing application spreadsheets.
- CSV export of opportunities, contacts, tasks, and status history.
- JSON export of the full account data.
- Plain-text or Markdown export of an opportunity preparation brief.

## 8. Recommended data model

Use PostgreSQL and Django models.

Core entities:

- `User`
- `Profile`
- `ProfileTrack`
- `Skill`
- `ProfileSkill`
- `Experience`
- `Project`
- `ApplicationMaterial`
- `Opportunity`
- `OpportunitySkill`
- `Application`
- `ApplicationMaterialSnapshot`
- `StatusHistory`
- `Contact`
- `ContactInteraction`
- `Task`
- `InterviewStage`
- `InterviewNote`
- `SavedTemplate`

Important relationships:

- A user has one profile and many profile tracks.
- A profile track has many skills and can be linked to many opportunities.
- A user has many opportunities.
- An opportunity can have one application record and many contacts, tasks, status events, interview stages, and notes.
- An application can reference multiple application materials.
- All user-owned records must include ownership protection through the authenticated user relationship.

## 9. Suggested technology stack

- Backend: Django 6 with Django REST Framework.
- Database: PostgreSQL.
- Frontend: Django templates with HTMX or React if the existing project already uses it. Prefer the simpler option for V1.
- Styling: clean responsive CSS or Tailwind.
- Authentication: Django authentication.
- File storage: local storage for development, configurable object storage for production.
- Background jobs: optional; do not add Celery unless a real asynchronous task is required.
- NLP/matching: deterministic keyword normalization and weighted rules first. Keep the matching service replaceable so an LLM can be added later with user approval.
- Environment configuration: `.env`; never commit secrets.

## 10. Matching logic for V1

Use a transparent weighted score, configurable in one service.

Suggested weighting:

- Required skills: 40%.
- Role/category alignment: 20%.
- Education and experience level: 15%.
- Location/work arrangement: 10%.
- Work authorization/sponsorship compatibility: 10%.
- Preferred skills: 5%.

Rules:

- Missing required skills reduce the score more than missing preferred skills.
- Unknown sponsorship information must not be treated as either positive or negative; show it as uncertain.
- The score is guidance, not a hiring probability.
- The UI must show the matched and missing items behind the score.
- Users can override the recommended priority and record why.

## 11. UX requirements

- The dashboard should answer: “What should I do next?”
- Adding a job should require only title, company, URL, and description at first; remaining fields may be completed later.
- Use clear status colors but do not rely on color alone.
- Use empty states with helpful examples.
- Keep forms short and group advanced fields behind expandable sections.
- Make the opportunity detail page the main workspace.
- Show the next task and next deadline prominently.
- Avoid generic productivity features that do not help the application workflow.
- Make the interface professional and uncluttered.

## 12. Security and privacy requirements

- Enforce authentication on every private page and API endpoint.
- Enforce object-level ownership checks.
- Protect uploaded resumes and personal contact information.
- Validate file types and file sizes.
- Sanitize pasted job descriptions and notes before rendering HTML.
- Use CSRF protection.
- Keep secrets in environment variables.
- Provide account/data deletion.
- Do not scrape authenticated sites or store third-party credentials.
- Add audit-friendly timestamps for application and status changes.

## 13. Acceptance criteria for MVP

The MVP is complete when a user can:

1. Create an account and profile.
2. Create at least two profile tracks.
3. Upload or link multiple application-material versions.
4. Add a job manually by pasting a description.
5. See an explainable match summary.
6. Select a priority and application-material version.
7. Track the job through the full status pipeline.
8. Add a contact and record an interaction.
9. Create and complete a follow-up task.
10. Store interview details and preparation notes.
11. View dashboard counts and basic conversion metrics.
12. Filter opportunities and export data.
13. Confirm that one user cannot access another user’s records.
14. Run automated tests for authentication, ownership, matching, status changes, duplicate detection, and analytics calculations.

## 14. Build order for Cursor

Implement in vertical slices:

### Phase 1: Foundation

- Inspect the existing repository before changing architecture.
- Preserve the current Django/PostgreSQL setup if present.
- Configure authentication, base layout, navigation, and environment variables.
- Add models and migrations for users, profiles, tracks, opportunities, and statuses.

### Phase 2: Core tracker

- Opportunity create/edit/detail pages.
- Status pipeline.
- Search and filters.
- Tasks and deadlines.
- Dashboard with next actions.

### Phase 3: Materials and matching

- Materials library.
- Profile tracks.
- Deterministic matching service.
- Explainable match display.
- Material selection on each application.

### Phase 4: Networking and interviews

- Contacts and interactions.
- Message templates.
- Follow-up workflow.
- Interview stages and preparation notes.

### Phase 5: Import, export, and quality

- CSV import/export.
- Markdown preparation brief export.
- Analytics improvements.
- Security review.
- Responsive polish.
- Automated tests and seed/demo data.

Do not build scraping, automatic messaging, or LLM-based resume rewriting until the core workflow is stable.

## 15. Cursor implementation instructions

Before writing code:

1. Inspect the repository structure, existing models, routes, templates, settings, dependencies, and tests.
2. Identify what already works and avoid replacing working code unnecessarily.
3. Propose a short implementation plan and list any schema changes.
4. Build the MVP in small, testable increments.

For every increment:

- Add or update migrations.
- Add model and API/view tests.
- Add ownership tests.
- Use realistic seed data.
- Keep business logic out of templates.
- Put matching logic in a dedicated service module.
- Use clear names and type hints where practical.
- Run formatting, linting, and tests.
- Report changed files, commands run, and any remaining limitations.

When a requirement is ambiguous, choose the smallest implementation that supports the workflow and document the decision. Do not invent external integrations or claim that sponsorship data is verified.

## 16. Future roadmap

- Browser extension for saving public job postings.
- Optional compliant job-board imports.
- Resume-to-job keyword comparison.
- AI-assisted but user-approved tailoring suggestions.
- Calendar integration for interviews and follow-ups.
- Email integration with explicit user authorization.
- Referral relationship tracking.
- Team or career-coach sharing.
- Saved search alerts.
- Personalized weekly review.

## 17. Success metrics

Measure product usefulness through:

- Median time to record a new opportunity.
- Percentage of opportunities with a selected material version.
- Percentage of applications with a next task.
- Follow-up completion rate.
- Weekly active users.
- Application-to-screen conversion rate.
- Screen-to-interview conversion rate.
- Interview-to-offer conversion rate.
- Number of opportunities archived without losing notes or materials.

The product succeeds when the user can quickly identify the best next opportunity, submit an organized application, remember every relevant conversation, and learn from the results of the search.
