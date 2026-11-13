# Surge Power LLC

This checkout contains the current public website and Flask owner workspace. The older `app.py` is retained as the original prototype; `backend.py` is the application entry point.

## Local setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app backend db upgrade
OWNER_EMAIL='owner@example.com' OWNER_PASSWORD='use-a-long-unique-password' .venv/bin/flask --app backend create-owner
.venv/bin/flask --app backend seed-demo
.venv/bin/flask --app backend run --port 8001
```

Use `.env.example` as the configuration reference. Supply real values through your shell or hosting secret store; do not commit credentials. Production requires a persistent `SURGE_SECRET` with at least 32 characters.

Open `http://127.0.0.1:8001/` for the public site and `/owner/login` for the workspace. The app stores its local SQLite database and a persistent, permission-restricted session key under Flask’s `instance` folder. Keep that folder out of source control and back it up only to encrypted, access-controlled storage. Demo records are labeled and are not customer records.

## Database changes

The repository includes Flask-Migrate/Alembic support and a non-destructive bootstrap revision. To generate and apply future model changes, disable development schema auto-creation while invoking migration commands:

```sh
SURGE_AUTO_CREATE_SCHEMA=false .venv/bin/flask --app backend db migrate -m 'describe the schema change'
SURGE_AUTO_CREATE_SCHEMA=false .venv/bin/flask --app backend db upgrade
```

Review generated migrations before applying them to any database with real records. Never use `db downgrade` as a data deletion mechanism. The bootstrap migration creates missing tables without dropping or replacing existing data.

## Owner operations

- `flask --app backend init-db` initializes a local development schema.
- `flask --app backend backup-db` creates a SQLite snapshot in `instance/backups`; set `SURGE_BACKUP_DIR` to an encrypted mounted backup location. This command does not encrypt the backup itself or schedule backups.
- `OWNER_EMAIL` plus `OWNER_PASSWORD` (16+ characters) and `flask --app backend reset-owner-password` reset a known account from a secure terminal. Password recovery email is not configured.
- `OWNER_EMAIL`, `OWNER_PASSWORD` (16+ characters), and `USER_ROLE=owner|manager|staff` with `flask --app backend create-user` add a separate workspace account from the server terminal. The owner can change roles and disable accounts under Business settings; there is no public invitation or password-reset link.
- `flask --app backend seed-demo` creates labeled demo records.
- `/owner/settings` holds the public phone, email, service area, ROC statement, hours, invoice terms, and payment instructions. Only enter verified owner-approved values. Business hours, invoice terms, and payment instructions start blank.
- `/owner/audit` shows recorded workflow changes and CSV/PDF exports. Projects can be archived and restored, and inquiry views include needs-action, overdue, quote follow-up, and won-but-unscheduled queues.
- Billing shows draft, overdue, partial, and paid summaries, supports created-date filters and due/balance sorting, and calculates tax using decimal half-up cent rounding.

## Production deployment requirements

Set `SURGE_ENV=production`, a persistent high-entropy `SURGE_SECRET`, `DATABASE_URL` for a managed database, `PUBLIC_BASE_URL` for canonical/SEO metadata, and the correct `SURGE_TIMEZONE` (defaults to `America/Phoenix`). Production startup requires the secret, uses secure session cookies, and refuses automatic schema creation; apply reviewed migrations before starting the WSGI server behind HTTPS. Use the database provider’s encrypted backups and restore process for non-SQLite databases. Configure access logs, monitoring, incident response, and dependency updates at the hosting layer.

Persistent IP-based rate limits are stored in the application database. If the app sits behind a reverse proxy, configure a trusted proxy layer at the hosting edge; do not blindly trust forwarded-IP headers. The app includes CSRF protection, Argon2 password hashing, secure response headers, no-store/noindex owner responses, and a local secret file for development sessions.

## Integrations and remaining owner decisions

SMTP delivery is available only after a provider and sender credentials are configured (`SURGE_SMTP_HOST`, `SURGE_SMTP_FROM`, and optional port/TLS/user/password). Email sends only when the owner chooses the explicit send action. SMS remains a saved draft; online payments, calendar sync, scheduled reminders, photo uploads, MFA, staff invitation/reset links, crew assignment/availability, and automated data retention/deletion still need owner choices and/or external provider credentials. Card and bank details must not be entered in this workspace.

The website uses the public business phone shown in the supplied Instagram creative as its initial profile default; the owner should verify it in Business settings. Confirm the ROC number and license/insurance wording before launch. Local development is not a substitute for a production security review or verified backup restore.
