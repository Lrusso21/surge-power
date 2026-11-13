# Autonomous development log

Updated 2026-11-10. The project is a local Flask application for Surge Power LLC; no hosted Site project or production deployment was identified.

## Baseline and repository state

- Public marketing site and private owner workspace share a Flask/SQLAlchemy application. The public page uses local project images and business profile data; the owner workspace includes CRM, calendar, billing, customers, tasks, and activity history.
- A separate `app.py` contains an older HTTP server prototype. `backend.py` is the active application entry point and still uses some legacy page content as its fallback route.
- Checkout is on `main` with no commits yet. Git reports the project directories as untracked, so no branch or history changes were made.
- Demo inquiries are labeled and remain in the local database; no real customer data was added.

## Prioritized work and current status

1. **Reliability, privacy, and access control — improved.** Added DB-backed request throttling, persistent local session signing key, production secret and schema guards, hardened response headers, account roles/disable controls, protected exports/billing, database migration support, privacy text, and owner CLI commands.
2. **Customer conversion — improved.** Added tap-to-call, project examples linked to their Instagram sources, consent-based inquiry intake, preferred contact/time and property/equipment details, form recovery, confirmation reference, structured business data, and Open Graph/canonical metadata when a public HTTPS base URL is configured.
3. **CRM flow — improved.** Added useful quick views, active filter summary, filtered CSV export, unassigned/assignee queue, audit details for stage/job/next-action changes, archive/restore, and mobile inquiry cards.
4. **Scheduling and billing — improved.** Added month/agenda scheduling, overlap checks and clearer validation, mobile agenda, local timezone defaults, invoice status summaries, created-date filters, due/balance sorting, and decimal cent rounding.
5. **Maintainability and performance — improved.** Added a minimal `public_shell.py` so the public landing page no longer inherits the legacy prototype’s inline stylesheet; shared database timestamps use an explicit UTC helper; SMTP calls have a bounded timeout; local session files are permission tightened; environment sample and ignore rules are in place.

## Verification

- `.venv/bin/python -m py_compile backend.py workspace_upgrade.py workspace_phase_two.py public_shell.py test_backend.py migrations/env.py migrations/versions/0001_schema_baseline.py` — passed.
- `.venv/bin/pytest -q` — 14 passed without warnings. Coverage includes CRM, consent intake, assignment/archive/restore, calendar collisions, invoice conversion/payment/PDF/CSV, billing summaries/filters/rounding, role permissions, login throttling, production secret/schema settings, local key permissions, privacy headers, and public metadata.
- Fresh-database migration smoke check with `SURGE_AUTO_CREATE_SCHEMA=false` — passed; required tables were created.
- Public page opened at `http://127.0.0.1:8002/`. The owner workspace requires the configured owner login.
- No Lighthouse, axe, or screen-reader diagnostic was available in this pass. Browser QA was limited to the live local page and application navigation. Production deployment was not attempted.

## Decisions and remaining dependencies

- Confirm phone number, ROC number, exact license/bond/insurance wording, service territory, business hours, invoice terms, tax policy, accepted payment methods, and estimate acceptance rules with the owner.
- Production needs managed hosting/database, HTTPS, externally managed secrets, scheduled encrypted backups plus a restore exercise, monitoring, and a documented incident/deployment process.
- SMTP credentials and sender-domain verification are required before email delivery. SMS, hosted checkout, calendar sync, scheduled reminders, and accounting integration need provider and workflow choices.
- MFA, invite/password-reset experience, data retention and deletion, optional photo uploads, and privacy-aware funnel analytics remain undecided.
- Calendar crew assignment/availability needs work-hour, duration, travel-buffer, and crew rules. Inquiry assignees exist; calendar crew-resource assignment does not.
- No production data, deployment, paid dependency, destructive migration, or credential change was performed.

## Git checkpoint

Current branch is `codex/autonomous-site-improvements`. The checkout has no committed baseline and project files are untracked; no commit was created. Preserve the working directory as-is before later Git initialization or history setup.
