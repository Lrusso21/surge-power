# Production launch

The current application requires a Python/container host and a persistent database. GitHub Pages serves the older static preview and cannot run this application.

## Host configuration

- Build context: `surge-power-fresh` in this repository; use its Dockerfile.
- Attach a managed PostgreSQL database with encrypted backups enabled.
- Set `SURGE_ENV=production`, `SURGE_AUTO_CREATE_SCHEMA=false`, `SURGE_TIMEZONE=America/Phoenix`.
- Set a randomly generated, persistent `SURGE_SECRET` (at least 32 characters) through the host's secret manager.
- Set `DATABASE_URL=postgresql+psycopg://...` using the database provider's TLS requirements.
- Set `PUBLIC_BASE_URL` to the final HTTPS address. Route traffic through the host's HTTPS endpoint only.
- Configure health monitoring against `/health/ready`; `/health/live` checks the process only.

Before routing traffic, run `flask --app backend db upgrade` as a single release job. Do not run migrations in every web worker. Then run `flask --app backend create-owner` in a secure console with `OWNER_EMAIL` and `OWNER_PASSWORD` supplied privately (16+ characters). Remove these temporary environment values afterward. Do not seed demonstration customers into production.

## Email and owner setup

Supply `SURGE_SMTP_HOST`, `SURGE_SMTP_FROM`, and optional port, TLS, username and password through the host. Verify sender-domain authentication with the email provider. Test delivery to an owner-controlled address and verify failed-send behavior before sending customer documents.

In Business settings, confirm the public contact details, service area, ROC statement, hours, invoice terms and payment instructions with the owner.

## Launch acceptance

1. Submit a clearly labeled test inquiry on the HTTPS site; confirm its reference and owner CRM record.
2. Assign and update the lead, set follow-up, schedule and reschedule a visit, and verify overlap protection.
3. Create an itemized estimate, download its PDF, convert it to an invoice, and record a partial payment and refund. Verify balances.
4. Test owner-triggered email delivery, role restrictions, filtered exports and sign-out.
5. Restart the service and verify records persist. Restore a database backup to an isolated database and verify records there.
6. Archive the test records. Enable uptime/error alerts and confirm who receives them.

## Recovery

Keep the previous container image/revision available. Roll back application code through the host; inspect schema compatibility first. Never downgrade or replace a production database to roll back code. Restore backups into an isolated database first, verify them, then coordinate any production switch. Rotate secrets if exposed and use the secure password reset command documented in README.md for account recovery.

## Deferred capabilities

## Operational additions

`/owner/tools` provides manager/owner service presets, bulk stage changes with guarded undo, and matching-contact customer job merges. The source customer remains in history. `/owner/search` searches inquiries, customers and document numbers. Calendar export downloads an iCalendar file for manual import; it is not two-way synchronization.

Schedule `flask --app backend process-reminders` to preview eligibility. After SMTP is verified, a single daily scheduler may run `flask --app backend process-reminders --send`. It sends next-day visit reminders and weekly overdue-invoice reminders to email contacts, retaining sent/failed history. Run only one scheduler to avoid concurrent duplicate delivery. This does not activate a scheduler automatically.

Password recovery uses single-use, hashed tokens expiring after 30 minutes. It requires a verified SMTP sender and an HTTPS `PUBLIC_BASE_URL`. Until configured, recovery requests show a generic response and send nothing; the secure console reset remains available. Review existing session revocation and MFA requirements before production launch.

Hosted card payments, SMS delivery, recurring reminders, external calendar sync, secure photo uploads, self-service password recovery/MFA, crew availability and automatic retention are not enabled by this deployment package. Each needs its own implementation and acceptance testing. Hosting and email account selection remain pending; no paid service is provisioned by these files.
