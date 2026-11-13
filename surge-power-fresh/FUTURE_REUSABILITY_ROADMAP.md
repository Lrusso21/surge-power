# Future reusability roadmap

The current business site remains the primary product. Extract shared systems only when doing so simplifies real maintenance or a second customer project exists.

## Already reusable in practice

- `BusinessProfile` centralizes company name, public phone/email, service area, ROC statement, hours, invoice terms, and payment instructions.
- `public_shell.py` provides a small, business-independent public HTML document shell.
- `utc_now`, `local_today`, currency parsing, line-item math, and audit helpers provide shared backend primitives.
- SQLAlchemy models and Flask-Migrate provide a documented path for repeatable local and production schema management.
- Owner role checks, CSRF, request throttling, message logs, and audit events are reusable security/workflow patterns.

## Practical next extraction steps

1. Move Flask route groups into blueprints (`public`, `owner_crm`, `owner_calendar`, `owner_billing`, `owner_settings`) while preserving existing URL names and route permissions.
2. Separate SQLAlchemy models from route modules and keep schema migrations explicit. Add service modules for inquiry intake, document totals, email delivery, and backups.
3. Centralize visual tokens and brand assets in one theme configuration; keep the black, antique-gold, and signal-red values as this company’s defaults.
4. Convert the main public page and repeated owner views to small Jinja templates with shared base layouts. Keep one-off markup inline only where it is simpler.
5. Represent optional features (SMTP, hosted payments, uploads, calendar sync) behind interfaces with configuration-based adapters, and enable each only after credentials and business rules are supplied.
6. Add a documented local onboarding path, environment-variable template without secrets, and a deployment checklist before treating the repository as a reusable starter.

## Keep business-specific

Service descriptions, ROC/licensing facts, the Instagram-derived portfolio, service area, invoice rules, and Surge Power brand styling must remain tied to verified Surge Power information. Do not build multi-tenant tables or a generic theme editor until multiple real businesses need the same system.
