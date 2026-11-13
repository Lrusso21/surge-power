# Surge Power LLC — owner review

Prepared November 10, 2026 from the local public site and Flask workspace source. The implementation status below records changes made after this review.

## Current build at a glance

The public site has the company logo and black, antique-gold, and signal-red palette; EV charger and general electrical service descriptions; Phoenix metro coverage; the ROC/license trust statements; three curated project stories that link back to Instagram; privacy information; and a quote inquiry form.

The owner workspace currently includes a “Today” dashboard, inquiry CRM with stages, urgency/follow-up and city/service filters, customer/job records, a month calendar and agenda, appointment collision checks, estimate/invoice records with line items, partial payment/refund tracking, PDF documents, CSV export, and activity/task records. The workspace is protected by login and CSRF tokens. Email sending and online payments are not configured. The owner interface could not be shown live in this walkthrough because it redirected to sign-in.

## Recommended changes, in priority order

### P0 — Before a real owner begins using this for customers

1. **Finish production data protection.** Replace the local SQLite file with a managed database and migrations; schedule encrypted backups and prove restore; set a managed secret; require HTTPS; define retention/deletion; and add error and uptime monitoring. The current login attempt control is process-local, so it does not reliably rate-limit across multiple workers or restarts.
2. **Harden owner access.** Add password reset and account recovery, optional MFA, separate staff accounts and roles, and a durable login rate limit. Keep customer and payment records out of logs and analytics. Confirm secure cookie and deployment settings in the actual production environment.
3. **Make the CRM the reliable source of truth.** Finish duplicate detection/merge for repeat inquiries; add an explicit owner/assignee and a required next-action date for every open lead; provide a visible activity timeline for stage, appointment, estimate, invoice, and contact changes; and define safe edit/archive behavior. Validate that CSV export honors the filters and permissions shown in the UI.
4. **Complete the invoice workflow.** Add clear business identity/contact and verified license details, invoice/estimate terms, itemized labor/materials, tax/discount controls where applicable, payment instructions, due dates, balance-due display, and document revision/void history. Confirm numbering and rounding rules. Keep card/bank data out of this app; connect a payment processor only through its hosted checkout if online payment is wanted.
5. **Verify delivery and customer messaging.** Configure and test a real email provider, sender domain, bounce handling, and message templates before enabling “send.” Add owner-approved inquiry acknowledgements, estimate delivery, appointment reminders, and payment reminders with an auditable sent/failed status. SMS should be a separate opt-in decision.
6. **Validate claims before launch.** Confirm ROC #336067, the exact “licensed, bonded & insured” wording, current service territory, and the public phone number against owner-approved records. The website currently shows the ROC/trust claims; the Instagram screenshot also showed (602) 935-0427, which could be made tappable once the owner confirms it is the right number.

### P1 — Make the day-to-day flow smoother

#### Public website

1. **Make the next step immediate.** Add a confirmed tap-to-call number beside the quote button, retain the short quote path, and show response expectations only after the owner chooses a realistic service standard. Keep Instagram as proof and a secondary path.
2. **Improve quote intake.** Ask only the useful first-contact questions, then conditionally show charger/vehicle, panel, property type, or electrical-scope fields. Add preferred contact method/time and a clear consent/privacy sentence. Add an optional photo upload only with limits, secure storage, and a retention policy. Preserve entered data after validation errors and show a clear confirmation/reference number after submission.
3. **Show authentic proof more clearly.** Expand each of the three project examples into a short case study with location, work performed, approved photos, and a quote CTA. Add owner-approved testimonials and brand/equipment details only when supplied. Verify image rights, cropping, alt text, and the Instagram destinations.
4. **Strengthen local discovery.** Add page title/description, share preview image, canonical URL, structured LocalBusiness/service data, and a clear service-area list. Create separate service pages only when the owner can provide distinct, accurate details. Avoid unsupported claims such as emergency service, warranties, or guaranteed response times.
5. **Polish mobile and accessibility.** Check the logo and hero at small widths; confirm readable contrast, visible keyboard focus, label/error associations, keyboard navigation, reduced motion, and tap targets. Ensure project images reserve their layout space and load efficiently.
6. **Measure the funnel responsibly.** Track quote-button clicks, form starts/completions, and source at an aggregate level. Add analytics only after choosing a privacy approach; do not send form contents or contact details to analytics.

#### Owner workspace

1. **Give every screen a clear “next action.”** Put the highest-priority overdue follow-ups and today’s visits first; allow one-click call/email, set follow-up, schedule, create estimate, and mark outcome. Add an owner-controlled queue for unassigned work.
2. **Improve the inquiry table.** Keep the stage summary compact and aligned; keep filters on a consistent grid; add saved views (new leads, overdue, quotes awaiting response, unscheduled wins); show active filter chips and result count; preserve filters through pagination and record navigation; and make the mobile layout usable without sideways scrolling. Add bulk stage/assignment/archive actions with undo and a change log.
3. **Tighten the inquiry detail page.** Use a single customer/job header, contact actions, stage and next-step controls, a chronological activity timeline, and related visits/documents/tasks in one place. Offer a quick-add note/call/email and a one-click “schedule” or “create estimate” action without losing unsaved work.
4. **Make scheduling operational.** Add staff/crew assignment, working hours, travel buffers, service duration, blocked time, and timezone handling. Provide week/day agenda on smaller screens, clearer appointment status colors, and edit/reschedule/cancel flows. Add conflict checks per assigned crew rather than globally once multiple crews exist. Calendar reminders need owner-set timing and delivery logs.
5. **Clarify jobs and task ownership.** Connect inquiry → customer → job → appointment → estimate/invoice with consistent status rules. Make tasks creatable, assignable, due-dated, completable, and visible from both dashboard and job. Add lightweight checklists for EV charger and common electrical visits if they match the owner’s process.
6. **Make billing easier to reconcile.** Add dashboard totals by draft/sent/overdue/partial/paid; sort/filter by due date and balance; make partial balances prominent; record payment date/reference and refund reason; and make estimate acceptance/expiration and conversion states explicit. Ensure PDFs are branded, printable, and include all approved terms. Provide a clean print view and delivery log.
7. **Remove repetitive typing.** Add editable service presets, estimate templates, customer defaults, reusable notes, and a duplicate-aware “existing customer” selector. Keep every automation reviewable before sending.
8. **Make exports and records predictable.** Export exactly the filtered view (with an export summary); add a date range and selected fields; provide a customer/job export when appropriate; record who exported what; and make archive/restore distinct from permanent deletion.

### P2 — Growth and operational maturity

1. Add conversion and response-time reporting by lead source, service, city, and stage, with date ranges and a way to exclude demo records.
2. Add integrations only after workflow decisions: calendar sync, email inbox association, accounting export, and hosted payment checkout. Define which system owns each field to prevent conflicting copies.
3. Add multi-user collaboration: staff roles, assignment rules, internal mentions, and notifications for overdue work, new inquiries, schedule changes, and failed sends.
4. Add structured search across customers/jobs/documents and a change history with restore for important fields.
5. Prepare the operational runbook: deploy/rollback, backup restore, credential rotation, data export/deletion requests, incident response, and periodic dependency/security review.

## Suggested rollout

1. Confirm business facts and the owner’s intake/scheduling/billing rules.
2. Complete P0 controls and validate with synthetic records.
3. Refine the public quote journey and owner CRM/calendar/billing screens around those rules.
4. Set up and verify email and reminders; add online payments only if desired.
5. Run an owner walkthrough using test records, then migrate real records and train the owner.

## Decisions for the potential owner

- Confirm phone number, ROC number and wording, insurance/bond wording, service areas, business hours, and response expectations.
- Who will use the workspace, and what access should each person have?
- Which appointment durations, work hours, buffers, crews, and reminder channels should be supported?
- What estimate/invoice terms, deposit rules, tax handling, accepted payment methods, and numbering format should apply?
- Should the site accept photo attachments? Should it offer online payment, SMS, or calendar sync?
- Which customer data should be retained, and for how long?

## Preview limitation

The accompanying HTML file is a self-contained animated storyboard, not a captured/exported MP4 and not an authenticated owner session. This session has no video export tool; the live owner page redirects to sign-in. The public preview was inspected live. The owner panels in the storyboard are illustrative views based on implemented screens and should be reviewed with the owner before sharing as a product demo.

## Implementation status — November 10, 2026

### Completed in the local build

- Persistent development secret storage, production secret enforcement, secure cookie configuration, CSRF protection, security headers, private owner response caching, and database-backed hashed-IP throttles for public inquiries and owner sign-ins.
- Alembic/Flask-Migrate baseline, production schema-auto-create guard, SQLite backup command, secure owner create/reset commands, separate account roles and disable controls, and route permissions for owner/manager/staff.
- Business settings for public contact details, service area, ROC/trust wording, hours, terms, and payment instructions; privacy notice; consent-based quote intake with useful property/equipment/contact preferences, form recovery, confirmation reference, and bot trap.
- Inquiry CRM quick queues, active filter summary, filtered export, mobile card rows, assignee field and unassigned queue, soft archive/restore, customer/job links, task/activity history, and activity audit.
- Calendar month and agenda views with a narrow-screen chronological agenda, edit/reschedule status handling, overlap prevention, date/time controls, and local timezone-aware “today” defaults.
- Billing summaries for draft, overdue, partial, and paid documents; created-date filters; due/balance ordering; itemized estimates/invoices; decimal cent rounding; branded PDFs; balance tracking; document activity; export audit.
- A minimal public document shell removes the legacy prototype’s inline CSS from the homepage; `.env.example` and ignore rules make local setup safer.
- Fourteen automated tests pass, including role restrictions, production configuration checks, migration smoke coverage, and local session-key permissions.
- Local server restarted at `http://127.0.0.1:8002/`; the owner workspace is at `/owner/login` and requires the configured owner account.

### Still needs company decisions, credentials, or production infrastructure

- Verify the displayed phone, ROC #336067, exact license/bond/insurance wording, service areas, and company profile before publishing.
- Configure managed production hosting/database, HTTPS, a persistent production secret, encrypted scheduled backups plus a restore exercise, monitoring, and an incident/deployment runbook. The included SQLite backup command does not encrypt, schedule, or restore backups.
- Provide SMTP sender/provider credentials and verify deliverability before using email sends. SMS, automatic reminders, calendar sync, accounting integration, and hosted payment checkout require provider selection and owner approval.
- Define crew working hours, durations, buffers, and resource assignment rules before adding availability-aware scheduling. Inquiry ownership assignment is available; calendar crew assignment is not.
- Decide on MFA, invitation and password-reset experience, data retention/deletion, photo handling, optional funnel analytics, and any estimate presets/discount/tax policy.

No real customer contacts or payment credentials were added during this implementation. Existing demo inquiries remain marked as demo records.
