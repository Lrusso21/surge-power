# Completion record

## Implemented and covered by local checks

- Dedicated public service information pages; sitemap includes the new pages.
- Workspace search for inquiries, customers and document numbers.
- Manager/owner service presets with estimate form prefill.
- Bulk inquiry stage updates with audit history and undo that rejects newer edits.
- Matching-contact customer job merges that retain source records.
- Calendar iCalendar export, with Phoenix times converted to UTC; manual import only.
- Daily reminder command with preview default, configured SMTP sends, sent/failed history and sent-message deduplication. A single scheduler is required.
- Single-use, hashed email recovery tokens with 30-minute expiry, generic account lookup responses and rate limiting.
- Skip navigation, mobile checkbox wrapping, readable mobile inputs and duplicate-submit button safeguards.
- Production container/server configuration, PostgreSQL driver, health endpoints and launch/recovery instructions.
- 19 local tests pass. Browser verification and real-provider acceptance remain separate requirements.

## Requires company input or external setup

- Owner-approved high-resolution project images and testimonials.
- Hosting, database, HTTPS/domain, production secrets, backups, restore exercise and monitoring. Hosting was explicitly deferred.
- Verified SMTP sender/credentials and deliverability checks; scheduler activation.
- Payment processor and merchant account; calendar account access; SMS provider and contact consent workflow.
- Owner-approved prices, terms, crew availability, retention periods and account recovery policy.

## Still requires implementation and testing

- MFA and revocation of existing sessions after password reset.
- Crew assignments, working hours, travel buffers and blocked time.
- Two-way Google/Outlook sync (calendar download is not sync).
- Secure customer estimate acceptance and hosted payment checkout.
- Secure photo uploads and storage.
- Automated retention/deletion with record-specific retention rules.
- Privacy-conscious conversion reporting.
- Full mobile/browser walkthrough of every workflow and production end-to-end acceptance.

No paid service has been activated. The entire recommendation list is not complete; these remaining items must not be described as implemented or live.
