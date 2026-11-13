from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=64)
def screen_template(name):
    return (Path(__file__).parent / "templates" / "workspace" / name).read_text()

"""Second-pass operations layer: customers, jobs, reliable workflow and conversion."""
import os
import smtplib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from io import BytesIO
from calendar import monthrange

from flask import abort, flash, redirect, request, send_file, session, url_for
from flask_login import login_required, current_user, logout_user
from flask_wtf.csrf import generate_csrf
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from sqlalchemy import func, text, case

from backend import db, Inquiry, Activity, Appointment, Document, Payment, User, STAGES, SERVICES, cents, balance, parsed_date, render, local_today, utc_now
from workspace_upgrade import WorkTask, DocumentLineItem, money, line_total, parse_lines


class Customer(db.Model):
    __tablename__ = "customer"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(200), nullable=False, index=True)
    preferred_contact = db.Column(db.String(20), nullable=False, default="contact")
    created = db.Column(db.DateTime, nullable=False, default=utc_now)


class Job(db.Model):
    __tablename__ = "job"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id"), unique=True, nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    service = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(220), default="")
    status = db.Column(db.String(30), nullable=False, default="lead", index=True)
    source = db.Column(db.String(50), nullable=False, default="website")
    created = db.Column(db.DateTime, nullable=False, default=utc_now)


class DocumentMeta(db.Model):
    __tablename__ = "document_meta"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("document.id"), nullable=False, unique=True, index=True)
    delivery_status = db.Column(db.String(20), nullable=False, default="draft")
    approval_status = db.Column(db.String(20), nullable=False, default="not_applicable")
    expires = db.Column(db.Date)
    updated = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class MessageLog(db.Model):
    __tablename__ = "message_log"
    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id"), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False)
    recipient = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(200), nullable=False, default="")
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    created = db.Column(db.DateTime, nullable=False, default=utc_now)
    sent = db.Column(db.DateTime)


class Attachment(db.Model):
    __tablename__ = "attachment"
    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id"), nullable=False, index=True)
    label = db.Column(db.String(160), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    created = db.Column(db.DateTime, nullable=False, default=utc_now)


class InquiryIntake(db.Model):
    __tablename__ = "inquiry_intake"
    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id"), nullable=False, unique=True, index=True)
    preferred_contact = db.Column(db.String(20), nullable=False, default="contact")
    best_time = db.Column(db.String(30), nullable=False, default="anytime")
    property_type = db.Column(db.String(30), nullable=False, default="unspecified")
    vehicle_or_equipment = db.Column(db.String(160), nullable=False, default="")
    consented_at = db.Column(db.DateTime, nullable=False, default=utc_now)


class BusinessProfile(db.Model):
    __tablename__ = "business_profile"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False, default="Surge Power LLC")
    phone = db.Column(db.String(40), nullable=False, default="(602) 935-0427")
    email = db.Column(db.String(200), nullable=False, default="")
    business_address = db.Column(db.String(220), nullable=False, default="")
    roc_number = db.Column(db.String(40), nullable=False, default="336067")
    license_statement = db.Column(db.String(160), nullable=False, default="Licensed, bonded & insured")
    service_area = db.Column(db.String(180), nullable=False, default="East Valley · Phoenix metro")
    business_hours = db.Column(db.String(180), nullable=False, default="")
    invoice_terms = db.Column(db.String(500), nullable=False, default="")
    payment_instructions = db.Column(db.String(500), nullable=False, default="")
    updated = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class AuditEvent(db.Model):
    __tablename__ = "audit_event"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    summary = db.Column(db.String(500), nullable=False)
    created = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)


class AccountAccess(db.Model):
    __tablename__ = "account_access"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    role = db.Column(db.String(20), nullable=False, default="owner")
    active = db.Column(db.Boolean, nullable=False, default=True)


class InquiryAssignment(db.Model):
    __tablename__ = "inquiry_assignment"
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id", ondelete="CASCADE"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    assigned_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    updated = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class InquiryArchive(db.Model):
    __tablename__ = "inquiry_archive"
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id", ondelete="CASCADE"), primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reason = db.Column(db.String(240), nullable=False, default="Archived from active work.")
    archived_at = db.Column(db.DateTime, nullable=False, default=utc_now)


def account_role(user_id=None):
    user_id = user_id or (current_user.id if current_user.is_authenticated else None)
    access = db.session.get(AccountAccess, user_id) if user_id else None
    return access.role if access and access.active else ("owner" if user_id else "")


def audit(action, entity_type, entity_id, summary):
    from flask_login import current_user
    actor_id = current_user.id if current_user.is_authenticated else None
    db.session.add(AuditEvent(actor_id=actor_id, entity_type=entity_type,
                              entity_id=entity_id, action=action, summary=summary[:500]))


def get_business_profile():
    profile = BusinessProfile.query.first()
    if profile is None:
        profile = BusinessProfile()
        db.session.add(profile)
        db.session.commit()
    return profile


VALID_VISIT_STATUSES = ["tentative", "confirmed", "en route", "in progress", "completed", "rescheduled", "cancelled", "no access"]
VALID_JOB_STATUSES = ["lead", "assessment", "quoted", "approved", "scheduled", "in progress", "completed", "lost"]


def normalize_contact(value):
    return "".join(char.lower() for char in (value or "") if char.isalnum() or char in "@._+-")


def ensure_customer_and_job(inquiry):
    job = Job.query.filter_by(inquiry_id=inquiry.id).first()
    if job:
        return db.session.get(Customer, job.customer_id), job
    key = normalize_contact(inquiry.contact)
    candidates = Customer.query.all()
    customer = next((candidate for candidate in candidates if normalize_contact(candidate.contact) == key), None)
    if not customer:
        customer = Customer(name=inquiry.name, contact=inquiry.contact)
        db.session.add(customer); db.session.flush()
    job = Job(customer_id=customer.id, inquiry_id=inquiry.id, title=inquiry.service, service=inquiry.service, address=inquiry.location or "", status="lead")
    db.session.add(job); db.session.flush()
    return customer, job


def doc_meta(document):
    meta = DocumentMeta.query.filter_by(document_id=document.id).first()
    if not meta:
        meta = DocumentMeta(document_id=document.id, delivery_status="sent" if document.status in ["sent", "paid"] else document.status, approval_status="not_applicable" if document.kind == "invoice" else "pending")
        db.session.add(meta); db.session.flush()
    return meta


def payment_status(document):
    if document.status == "void":
        return "void"
    if document.kind != "invoice":
        return "not_applicable"
    remaining = balance(document)
    if remaining <= 0:
        return "paid"
    if remaining < document.amount_cents:
        return "partial"
    return "unpaid"


def query_inquiries():
    archived_ids = db.session.query(InquiryArchive.inquiry_id)
    query = Inquiry.query.filter(~Inquiry.id.in_(archived_ids))
    search = request.args.get("q", "").strip(); stage = request.args.get("stage", ""); urgency = request.args.get("urgency", ""); followup = request.args.get("followup", ""); service = request.args.get("service", ""); city = request.args.get("city", "").strip(); view = request.args.get("view", ""); assigned = request.args.get("assigned", "")
    today = local_today()
    if search:
        query = query.filter(db.or_(Inquiry.name.ilike("%" + search + "%"), Inquiry.contact.ilike("%" + search + "%"), Inquiry.location.ilike("%" + search + "%")))
    if stage in STAGES:
        query = query.filter_by(stage=stage)
    if urgency in ["urgent", "within a week", "flexible", "unspecified"]:
        query = query.filter_by(urgency=urgency)
    if service in SERVICES:
        query = query.filter_by(service=service)
    if city:
        query = query.filter(Inquiry.location.ilike("%" + city + "%"))
    if assigned == "unassigned":
        query = query.filter(~Inquiry.id.in_(db.session.query(InquiryAssignment.inquiry_id)))
    elif assigned.isdigit():
        query = query.filter(Inquiry.id.in_(db.session.query(InquiryAssignment.inquiry_id).filter(InquiryAssignment.user_id == int(assigned))))
    if followup == "overdue":
        query = query.filter(Inquiry.followup.isnot(None), Inquiry.followup < today, Inquiry.stage.notin_(["won", "lost", "closed"]))
    elif followup == "today":
        query = query.filter(Inquiry.followup == today, Inquiry.stage.notin_(["won", "lost", "closed"]))
    elif followup == "action":
        query = query.filter(db.or_(Inquiry.followup.is_(None), Inquiry.followup <= today)).filter(Inquiry.stage.notin_(["won", "lost", "closed"]))
    elif followup == "none":
        query = query.filter(Inquiry.followup.is_(None))
    if view == "unscheduled-wins":
        scheduled_ids = db.session.query(Appointment.inquiry_id).filter(Appointment.status.notin_(["cancelled", "rescheduled"]))
        query = query.filter(Inquiry.stage == "won", ~Inquiry.id.in_(scheduled_ids))
    return query, {"q": search, "stage": stage, "urgency": urgency, "followup": followup, "service": service, "city": city, "view": view, "assigned": assigned}


def redirect_with_form(endpoint, **values):
    session["form_recovery"] = dict(request.form)
    return redirect(url_for(endpoint, **values))


def recovered_form():
    return session.pop("form_recovery", {})


def send_message(record):
    host = os.environ.get("SURGE_SMTP_HOST")
    sender = os.environ.get("SURGE_SMTP_FROM")
    if not host or not sender:
        record.status = "ready"
        return False
    message = EmailMessage(); message["From"] = sender; message["To"] = record.recipient; message["Subject"] = record.subject; message.set_content(record.body)
    with smtplib.SMTP(host, int(os.environ.get("SURGE_SMTP_PORT", "587")), timeout=10) as server:
        if os.environ.get("SURGE_SMTP_TLS", "true").lower() == "true": server.starttls()
        username = os.environ.get("SURGE_SMTP_USERNAME")
        password = os.environ.get("SURGE_SMTP_PASSWORD")
        if username and password: server.login(username, password)
        server.send_message(message)
    record.status = "sent"; record.sent = utc_now()
    return True


def install_phase_two(app):
    if app.config.get("AUTO_CREATE_SCHEMA", True):
        with app.app_context():
            db.create_all()
            for user in User.query.all():
                if db.session.get(AccountAccess, user.id) is None:
                    db.session.add(AccountAccess(user_id=user.id, role="owner", active=True))
            for inquiry in Inquiry.query.all():
                ensure_customer_and_job(inquiry)
            for document in Document.query.all():
                doc_meta(document)
            db.session.commit()

    @app.before_request
    def reject_disabled_account():
        if current_user.is_authenticated:
            access = db.session.get(AccountAccess, current_user.id)
            if access and not access.active:
                logout_user(); session.clear(); flash("This workspace account is disabled.")
                return redirect(url_for("signin"))

    def phase_two_public_inquiry():
        allowed = app.extensions["surge_take_rate_limit"]("public-inquiry", 5, 900)
        if not allowed:
            session["public_form_notice"] = "Please wait before submitting another request, or call us for help."
            return redirect("/?sent=0#contact")
        # Quietly accept bot traps without creating a record or exposing the filter.
        if request.form.get("website", "").strip():
            return redirect("/?sent=1#contact")
        fields = {key: request.form.get(key, "").strip() for key in
                  ["name", "contact", "service", "location", "details", "preferred_contact", "best_time", "property_type", "vehicle_or_equipment"]}
        fields["consent"] = "yes" if request.form.get("consent") == "yes" else ""
        allowed_contact = {"phone", "email", "contact"}
        allowed_time = {"anytime", "morning", "afternoon", "evening"}
        allowed_property = {"unspecified", "home", "business"}
        valid = (fields["name"] and fields["contact"] and fields["service"] in SERVICES
                 and len(fields["name"]) <= 100 and len(fields["contact"]) <= 200
                 and len(fields["location"]) <= 100 and len(fields["details"]) <= 3000
                 and len(fields["vehicle_or_equipment"]) <= 160
                 and fields["preferred_contact"] in allowed_contact
                 and fields["best_time"] in allowed_time
                 and fields["property_type"] in allowed_property
                 and request.form.get("consent") == "yes")
        if not valid:
            session["public_form_recovery"] = fields
            session["public_form_notice"] = "Check the required fields and confirm how we may use your details to respond."
            return redirect("/?sent=0#contact")
        item = Inquiry(name=fields["name"], contact=fields["contact"], service=fields["service"],
                       location=fields["location"], details=fields["details"], stage="new")
        db.session.add(item); db.session.flush()
        intake = InquiryIntake(inquiry_id=item.id, preferred_contact=fields["preferred_contact"],
                               best_time=fields["best_time"], property_type=fields["property_type"],
                               vehicle_or_equipment=fields["vehicle_or_equipment"])
        db.session.add(intake)
        customer, job = ensure_customer_and_job(item)
        job.source = "website"
        db.session.add(Activity(inquiry_id=item.id, kind="intake", body="Quote request received through the public website."))
        audit("create", "inquiry", item.id, "New public quote request received.")
        db.session.commit()
        session["public_form_notice"] = f"Thanks. Request #{item.id} is in. We’ll follow up using your preferred contact method."
        return redirect("/?sent=1#contact")

    @app.after_request
    def phase_two_assets(response):
        if response.mimetype == "text/html":
            markup = response.get_data(as_text=True)
            if "/static/phase2.css" not in markup:
                markup = markup.replace("</head>", '<link rel="stylesheet" href="/static/phase2.css?v=2"><script defer src="/static/usability.js"></script></head>')
            if request.path.startswith("/owner"):
                markup = markup.replace('<a href="/owner/inquiries">Inquiries</a><a href="/owner/calendar">', '<a href="/owner/inquiries">Inquiries</a><a href="/owner/customers">Customers</a><a href="/owner/calendar">')
                markup = markup.replace('</nav><form method="post" action="/owner/logout">', '<a class="workspace-settings-link" href="/owner/settings">Business settings</a></nav><form method="post" action="/owner/logout">')
                if current_user.is_authenticated and account_role() == "staff":
                    markup = markup.replace('<a href="/owner/billing">Billing</a>', '')
                    markup = markup.replace('<a class="workspace-settings-link" href="/owner/settings">Business settings</a>', '')
                if current_user.is_authenticated and account_role() == "manager":
                    markup = markup.replace('<a class="workspace-settings-link" href="/owner/settings">Business settings</a>', '<a class="workspace-settings-link" href="/owner/audit">Activity history</a>')
                if request.path == "/owner/settings":
                    markup = markup.replace('href="/owner/settings"', 'aria-current="page" href="/owner/settings"', 1)
                elif request.path == "/owner/audit":
                    markup = markup.replace('href="/owner/audit"', 'aria-current="page" href="/owner/audit"', 1)
            if request.path.startswith("/owner") and current_user.is_authenticated:
                import re
                role = account_role()
                links = [("/owner/dashboard", "Today"), ("/owner/inquiries", "Inquiries"), ("/owner/customers", "Customers"), ("/owner/calendar", "Calendar")]
                if role in ["owner", "manager"]: links.append(("/owner/billing", "Billing"))
                links.append(("/owner/settings", "Business settings") if role == "owner" else ("/owner/audit", "Activity history")) if role != "staff" else None
                nav = '<nav aria-label="Workspace navigation">' + ''.join('<a ' + ('aria-current="page" ' if request.path.startswith(path) else '') + 'href="' + path + '">' + label + '</a>' for path, label in links) + '</nav>'
                markup = re.sub(r'(<header[^>]*>.*?)<nav[^>]*>.*?</nav>', lambda m: m.group(1) + nav, markup, count=1, flags=re.S)
                kind = "billing" if request.path.startswith("/owner/billing") else "customers" if request.path.startswith("/owner/customers") else "inquiries"
                markup = markup.replace('class="inquiry-table"', 'class="inquiry-table table-' + kind + '"')
            response.set_data(markup)
        return response

    app.view_functions["submit_inquiry"] = phase_two_public_inquiry

    @app.route("/owner/settings", methods=["GET", "POST"])
    @login_required
    def business_settings():
        if account_role() != "owner": abort(403)
        profile = get_business_profile()
        if request.method == "POST":
            fields = {
                "company_name": (120, True), "phone": (40, True), "email": (200, False), "business_address": (220, False),
                "roc_number": (40, False), "license_statement": (160, False),
                "service_area": (180, True), "business_hours": (180, False),
                "invoice_terms": (500, False), "payment_instructions": (500, False),
            }
            values = {key: request.form.get(key, "").strip() for key in fields}
            invalid = any((not values[key] if required else False) or len(values[key]) > limit
                          for key, (limit, required) in fields.items())
            if values["email"] and ("@" not in values["email"] or len(values["email"]) > 200):
                invalid = True
            if invalid:
                flash("Check required fields and length limits; no settings were saved.")
            else:
                for key, value in values.items():
                    setattr(profile, key, value)
                audit("update", "business_profile", profile.id, "Business profile and document defaults updated.")
                db.session.commit()
                flash("Business settings saved. Public profile and new PDFs now use these values.")
                return redirect(url_for("business_settings"))
        return render("Business settings", screen_template("business_settings.html"), profile=profile)

    @app.route("/owner/audit")
    @login_required
    def audit_history():
        if account_role() not in ["owner", "manager"]: abort(403)
        page = AuditEvent.query.order_by(AuditEvent.created.desc(), AuditEvent.id.desc()).paginate(
            page=max(1, request.args.get("page", 1, type=int)), per_page=50, error_out=False)
        zone = ZoneInfo(os.environ.get("SURGE_TIMEZONE", "America/Phoenix"))
        for event in page.items:
            event.display_time = event.created.replace(tzinfo=timezone.utc).astimezone(zone)
        users = {user.id: user.email for user in User.query.all()}
        return render("Activity history", screen_template("activity_history.html"), page=page, users=users)

    @app.route("/owner/users", methods=["GET", "POST"])
    @login_required
    def workspace_users():
        if account_role() != "owner": abort(403)
        if request.method == "POST":
            access = db.get_or_404(AccountAccess, request.form.get("user_id", type=int))
            role = request.form.get("role"); active = request.form.get("active") == "yes"
            if role not in ["owner", "manager", "staff"]: abort(400)
            if access.user_id == current_user.id and (not active or role != "owner"):
                flash("You cannot disable or demote the account you are currently using.")
            else:
                access.role = role; access.active = active
                audit("update", "account", access.user_id, "Account access updated to " + role + (" (active)." if active else " (disabled)."))
                db.session.commit(); flash("Account access saved.")
            return redirect(url_for("workspace_users"))
        accounts = User.query.order_by(User.email).all()
        for user in accounts:
            if db.session.get(AccountAccess, user.id) is None:
                db.session.add(AccountAccess(user_id=user.id, role="owner", active=True))
        db.session.commit()
        access = {item.user_id: item for item in AccountAccess.query.all()}
        return render("Workspace accounts", screen_template("workspace_accounts.html"), accounts=accounts, access=access)

    @app.route("/owner/customers")
    @login_required
    def customers():
        query = Customer.query
        term = request.args.get("q", "").strip()
        if term:
            query = query.filter(db.or_(Customer.name.ilike("%" + term + "%"), Customer.contact.ilike("%" + term + "%")))
        pagination = query.order_by(Customer.name, Customer.id).paginate(page=max(1, request.args.get("page", 1, type=int)), per_page=25, error_out=False)
        rows = pagination.items
        jobs = dict(db.session.query(Job.customer_id, func.count(Job.id)).filter(Job.customer_id.in_([c.id for c in rows])).group_by(Job.customer_id).all())
        return render("Customers", screen_template("customers.html"), rows=rows, jobs=jobs, term=term, pagination=pagination)

    @app.route("/owner/customers/<int:ident>")
    @login_required
    def customer_detail(ident):
        customer = db.get_or_404(Customer, ident); jobs = Job.query.filter_by(customer_id=ident).order_by(Job.created.desc()).all(); inquiry_by_id = {item.id: item for item in Inquiry.query.filter(Inquiry.id.in_([job.inquiry_id for job in jobs if job.inquiry_id])).all()}
        return render("Customer", screen_template("customer.html"), customer=customer, jobs=jobs, inquiry_by_id=inquiry_by_id)

    @app.route("/owner/inquiries/new", methods=["GET", "POST"])
    @login_required
    def phase_two_create_inquiry():
        customer_id = request.values.get("customer", type=int)
        customer = db.session.get(Customer, customer_id) if customer_id else None
        if request.method == "POST":
            name = request.form.get("name", "").strip(); contact = request.form.get("contact", "").strip(); service = request.form.get("service", ""); location = request.form.get("location", "").strip(); details = request.form.get("details", "").strip(); project_title = request.form.get("project_title", "").strip()
            if not name or not contact or service not in SERVICES or len(name) > 100 or len(contact) > 200 or len(location) > 100 or len(details) > 3000:
                flash("Add a name, contact method, service, and valid project details.")
            else:
                selected_customer = db.session.get(Customer, request.form.get("customer_id", type=int)) if request.form.get("customer_id") else None
                if not selected_customer:
                    key = normalize_contact(contact); selected_customer = next((entry for entry in Customer.query.all() if normalize_contact(entry.contact) == key), None)
                if not selected_customer:
                    selected_customer = Customer(name=name, contact=contact, preferred_contact=request.form.get("preferred_contact", "contact")); db.session.add(selected_customer); db.session.flush()
                item = Inquiry(name=name, contact=contact, service=service, location=location, details=details, stage="new")
                db.session.add(item); db.session.flush(); db.session.add(Job(customer_id=selected_customer.id, inquiry_id=item.id, title=project_title[:180] or service, service=service, address=location, status="lead", source=request.form.get("source", "manual")))
                db.session.add(Activity(inquiry_id=item.id, kind="intake", body="Project created from " + request.form.get("source", "manual") + ".")); audit("create", "inquiry", item.id, "Owner created a project inquiry."); db.session.commit(); flash("Project added. Set the next action while the details are fresh."); return redirect(url_for("inquiry_detail", ident=item.id))
        return render("Add project", screen_template("add_project.html"), customer=customer, services=SERVICES)

    @app.route("/owner/dashboard")
    @login_required
    def phase_two_dashboard():
        if account_role() == "staff": return redirect(url_for("inquiries"))
        today = local_today(); tomorrow = today + timedelta(days=1)
        archived_ids = db.session.query(InquiryArchive.inquiry_id)
        new_count = Inquiry.query.filter_by(stage="new").filter(~Inquiry.id.in_(archived_ids)).count()
        overdue = Inquiry.query.filter(Inquiry.followup.isnot(None), Inquiry.followup < today, Inquiry.stage.notin_(["won", "lost", "closed"]), ~Inquiry.id.in_(archived_ids)).order_by(Inquiry.followup).limit(5).all()
        overdue_count = Inquiry.query.filter(Inquiry.followup < today, Inquiry.stage.notin_(["won", "lost", "closed"]), ~Inquiry.id.in_(archived_ids)).count()
        due_today = Inquiry.query.filter(Inquiry.followup == today, Inquiry.stage.notin_(["won", "lost", "closed"]), ~Inquiry.id.in_(archived_ids)).order_by(Inquiry.created).limit(5).all()
        actionless = Inquiry.query.filter(Inquiry.followup.is_(None), Inquiry.stage.notin_(["won", "lost", "closed"]), ~Inquiry.id.in_(archived_ids)).count()
        visits = Appointment.query.filter(Appointment.start >= datetime.combine(today, datetime.min.time()), Appointment.start < datetime.combine(tomorrow, datetime.min.time()), Appointment.status.notin_(["cancelled", "rescheduled"])).order_by(Appointment.start).all()
        tasks = WorkTask.query.filter_by(status="open").filter(db.or_(WorkTask.due.is_(None), WorkTask.due <= today)).order_by(WorkTask.due.is_(None), WorkTask.due).limit(6).all()
        invoices = Document.query.filter_by(kind="invoice").all(); outstanding = sum(max(0, balance(doc)) for doc in invoices if payment_status(doc) in ["unpaid", "partial"])
        names = {item.id: item.name for item in Inquiry.query.all()}; unassigned_count = Inquiry.query.filter(~Inquiry.id.in_(archived_ids), ~Inquiry.id.in_(db.session.query(InquiryAssignment.inquiry_id))).filter(Inquiry.stage.notin_(["won", "lost", "closed"])).count()
        return render("Today", screen_template("today.html"), today=today, tomorrow=tomorrow, overdue_count=overdue_count, new_count=new_count, overdue=overdue, due_today=due_today, actionless=actionless, visits=visits, tasks=tasks, names=names, outstanding=outstanding, unassigned_count=unassigned_count, money=money)

    @app.route("/owner/inquiries")
    @login_required
    def phase_two_inquiries():
        query, filters = query_inquiries(); order = request.args.get("order", "priority")
        if order == "newest": query = query.order_by(Inquiry.created.desc())
        elif order == "oldest": query = query.order_by(Inquiry.created.asc())
        else: query = query.order_by(Inquiry.followup.is_(None), Inquiry.followup.asc(), Inquiry.created.desc())
        page = query.paginate(page=max(1, request.args.get("page", 1, type=int)), per_page=25, error_out=False)
        assignment_rows = InquiryAssignment.query.filter(InquiryAssignment.inquiry_id.in_([item.id for item in page.items])).all() if page.items else []
        account_names = {user.id: user.email for user in User.query.all()}
        assignees = {assignment.inquiry_id: account_names.get(assignment.user_id, "Unassigned") for assignment in assignment_rows}
        totals = dict(db.session.query(Inquiry.stage, func.count(Inquiry.id)).filter(~Inquiry.id.in_(db.session.query(InquiryArchive.inquiry_id))).group_by(Inquiry.stage).all())
        export_url = url_for("export_inquiries", **filters)
        previous_url = url_for("inquiries", page=page.prev_num, order=order, **filters) if page.has_prev else ""
        next_url = url_for("inquiries", page=page.next_num, order=order, **filters) if page.has_next else ""
        return render("Inquiries", screen_template("inquiries.html"), page=page, filters=filters, order=order, stages=STAGES, services=SERVICES, totals=totals, accounts=User.query.order_by(User.email).all(), assignees=assignees, today=local_today(), export_url=export_url, can_export=account_role() in ["owner", "manager"], previous_url=previous_url, next_url=next_url)

    @app.route("/owner/inquiries/<int:ident>", methods=["GET", "POST"])
    @login_required
    def phase_two_inquiry(ident):
        item = db.get_or_404(Inquiry, ident)
        created_job = not bool(Job.query.filter_by(inquiry_id=ident).first())
        customer, job = ensure_customer_and_job(item)
        if created_job:
            db.session.commit()
        if request.method == "POST":
            action = request.form.get("action")
            if action == "update":
                previous_stage = item.stage; previous_job_status = job.status; previous_followup = item.followup
                stage = request.form.get("stage"); job_status = request.form.get("job_status"); urgency = request.form.get("urgency")
                if stage not in STAGES or urgency not in ["urgent", "within a week", "flexible", "unspecified"] or job_status not in VALID_JOB_STATUSES: abort(400)
                item.name = request.form.get("name", "").strip()[:100]; item.contact = request.form.get("contact", "").strip()[:200]; item.location = request.form.get("location", "").strip()[:100]; item.service = request.form.get("service", "") if request.form.get("service", "") in SERVICES else item.service; item.details = request.form.get("details", "").strip()[:3000]; item.stage = stage; item.urgency = urgency; item.followup = parsed_date(request.form.get("followup")); customer.name = item.name; customer.contact = item.contact; customer.preferred_contact = request.form.get("preferred_contact", "contact"); job.title = request.form.get("job_title", item.service).strip()[:180] or item.service; job.service = item.service; job.address = request.form.get("address", item.location).strip()[:220]; job.status = job_status
                assignment = db.session.get(InquiryAssignment, ident); assigned_to = request.form.get("assigned_to", "").strip()
                if assigned_to:
                    assignee = db.session.get(User, int(assigned_to)) if assigned_to.isdigit() else None
                    access = db.session.get(AccountAccess, assignee.id) if assignee else None
                    if not assignee or (access and not access.active): abort(400)
                    if assignment is None: assignment = InquiryAssignment(inquiry_id=ident, user_id=assignee.id)
                    assignment.user_id = assignee.id; assignment.assigned_by = current_user.id; db.session.add(assignment)
                elif assignment is not None:
                    db.session.delete(assignment)
                changes = []
                if previous_stage != item.stage: changes.append("stage " + previous_stage + " → " + item.stage)
                if previous_job_status != job.status: changes.append("job " + previous_job_status + " → " + job.status)
                if previous_followup != item.followup: changes.append("next action " + str(previous_followup or "none") + " → " + str(item.followup or "none"))
                changes.append("customer and project details updated")
                update_summary = "; ".join(changes)
                db.session.add(Activity(inquiry_id=ident, kind="update", body=update_summary))
            elif action == "activity":
                body = request.form.get("body", "").strip(); kind = request.form.get("kind")
                if not body or len(body) > 3000 or kind not in ["note", "call", "email", "meeting", "other"]: abort(400)
                db.session.add(Activity(inquiry_id=ident, kind=kind, body=body))
                if kind in ["call", "email", "meeting"] and item.stage == "new": item.stage = "contacted"
            elif action == "task":
                title = request.form.get("title", "").strip(); due = parsed_date(request.form.get("due"))
                if not title or len(title) > 220: abort(400)
                db.session.add(WorkTask(inquiry_id=ident, title=title, due=due))
            elif action == "complete_task":
                task = db.get_or_404(WorkTask, int(request.form.get("task_id", 0)))
                if task.inquiry_id != ident: abort(404)
                task.status = "done"
            elif action == "archive":
                if account_role() not in ["owner", "manager"]: abort(403)
                if db.session.get(InquiryArchive, ident) is None:
                    db.session.add(InquiryArchive(inquiry_id=ident, actor_id=current_user.id,
                                                  reason=request.form.get("reason", "Archived from active work.")[:240]))
                    audit("archive", "inquiry", ident, "Project archived from active work.")
                    db.session.commit(); flash("Project archived. You can restore it from the archive.")
                return redirect(url_for("inquiry_archive"))
            elif action == "attachment":
                label = request.form.get("label", "").strip(); url = request.form.get("url", "").strip()
                if not label or not url.startswith(("https://", "http://")) or len(url) > 500: abort(400)
                db.session.add(Attachment(inquiry_id=ident, label=label[:160], url=url))
            elif action == "message":
                channel = request.form.get("channel", "email"); recipient = request.form.get("recipient", item.contact).strip(); subject = request.form.get("subject", "").strip(); body = request.form.get("body", "").strip()
                if channel not in ["email", "sms"] or not recipient or not body: abort(400)
                record = MessageLog(inquiry_id=ident, channel=channel, recipient=recipient[:200], subject=subject[:200], body=body[:5000])
                if channel == "email" and request.form.get("send") == "1":
                    try: send_message(record)
                    except Exception: record.status = "failed"; flash("Email could not be delivered. It was saved as failed for review.")
                db.session.add(record); db.session.add(Activity(inquiry_id=ident, kind=channel, body=("Message " + record.status + ": " + subject)[:3000]))
            else: abort(400)
            audit("update", "inquiry", ident, (update_summary if action == "update" else "Project workflow updated: " + action + "."))
            db.session.commit(); flash("Saved."); return redirect(url_for("inquiry_detail", ident=ident))
        appointments = Appointment.query.filter_by(inquiry_id=ident).order_by(Appointment.start.desc()).all(); documents = Document.query.filter_by(inquiry_id=ident).order_by(Document.created.desc()).all(); activities = Activity.query.filter_by(inquiry_id=ident).order_by(Activity.created.desc()).limit(100).all(); tasks = WorkTask.query.filter_by(inquiry_id=ident).order_by(WorkTask.status, WorkTask.due).all(); messages = MessageLog.query.filter_by(inquiry_id=ident).order_by(MessageLog.created.desc()).limit(10).all(); attachments = Attachment.query.filter_by(inquiry_id=ident).order_by(Attachment.created.desc()).all(); assignment = db.session.get(InquiryAssignment, ident); accounts = User.query.order_by(User.email).all()
        project_page = render("Project", screen_template("project.html"), item=item, customer=customer, job=job, services=SERVICES, stages=STAGES, urgencies=["urgent", "within a week", "flexible", "unspecified"], job_statuses=VALID_JOB_STATUSES, appointments=appointments, documents=documents, activities=activities, tasks=tasks, messages=messages, attachments=attachments, accounts=accounts, assignment=assignment, role=account_role(), money=money, payment_status=payment_status)
        if account_role() in ["owner", "manager"]:
            archive_form = '<form method="post" class="archive-form"><input type="hidden" name="csrf_token" value="' + generate_csrf() + '"><input type="hidden" name="action" value="archive"><button class="quiet-danger">Archive project</button></form>'
            project_page = project_page.replace("<h2>Next actions</h2>", "<h2>Next actions</h2>" + archive_form, 1)
        intake = InquiryIntake.query.filter_by(inquiry_id=ident).first()
        if intake:
            from markupsafe import escape
            preferences = [("Preferred contact", intake.preferred_contact), ("Best time", intake.best_time), ("Property", intake.property_type), ("Vehicle / equipment", intake.vehicle_or_equipment)]
            info = "".join("<p><strong>" + str(escape(label)) + ":</strong> " + str(escape(value or "Not provided")) + "</p>" for label, value in preferences)
            intake_panel = "<section class=\"panel intake-summary\"><h2>Request preferences</h2>" + info + "</section>"
            project_page = project_page.replace("<form method=\"post\" class=\"compact-form\">", intake_panel + "<form method=\"post\" class=\"compact-form\">", 1)
        return project_page

    @app.route("/owner/archive", methods=["GET", "POST"])
    @login_required
    def inquiry_archive():
        if account_role() not in ["owner", "manager"]: abort(403)
        if request.method == "POST":
            inquiry_id = request.form.get("inquiry_id", type=int)
            archived = db.get_or_404(InquiryArchive, inquiry_id)
            db.session.delete(archived)
            audit("restore", "inquiry", inquiry_id, "Project restored to active work.")
            db.session.commit(); flash("Project restored."); return redirect(url_for("inquiry_archive"))
        rows = db.session.query(InquiryArchive, Inquiry).join(Inquiry, Inquiry.id == InquiryArchive.inquiry_id).order_by(InquiryArchive.archived_at.desc()).all()
        return render("Archived projects", screen_template("archived_projects.html"), rows=rows)

    @app.route("/owner/calendar", methods=["GET", "POST"])
    @login_required
    def phase_two_calendar():
        recovered = recovered_form()
        if request.method == "POST":
            try:
                inquiry_id = int(request.form["inquiry_id"]); service_date = date.fromisoformat(request.form["service_date"]); start = datetime.combine(service_date, datetime.strptime(request.form["start_time"], "%H:%M").time()); end = datetime.combine(service_date, datetime.strptime(request.form["end_time"], "%H:%M").time()); status = request.form["status"]
                if not db.session.get(Inquiry, inquiry_id) or status not in VALID_VISIT_STATUSES: raise ValueError("Choose a valid inquiry and appointment status.")
                if end <= start: raise ValueError("End time must be after the start time.")
                if status not in ["cancelled", "rescheduled"]:
                    conflict = Appointment.query.filter(Appointment.start < end, Appointment.end > start, Appointment.status.notin_(["cancelled", "rescheduled"])).first()
                    if conflict: raise ValueError("This overlaps an active visit. Review the calendar and choose another time.")
                visit = Appointment(inquiry_id=inquiry_id, start=start, end=end, status=status, notes=request.form.get("notes", "")[:2000]); db.session.add(visit); db.session.flush(); db.session.add(Activity(inquiry_id=inquiry_id, kind="appointment", body="Visit scheduled for " + start.strftime("%b %-d at %-I:%M %p") + ".")); audit("create", "appointment", visit.id, "Appointment created for inquiry #" + str(inquiry_id) + "."); db.session.commit(); flash("Visit scheduled."); return redirect(url_for("appointment_editor", ident=visit.id))
            except (KeyError, ValueError) as error:
                flash(str(error)); return redirect_with_form("calendar_view", month=request.args.get("month", ""), inquiry=request.form.get("inquiry_id", ""), date=request.form.get("service_date", ""))
        month_key = request.args.get("month", local_today().strftime("%Y-%m"))
        try: shown = datetime.strptime(month_key, "%Y-%m").date().replace(day=1)
        except ValueError: shown = local_today().replace(day=1)
        next_month = (shown.replace(day=28) + timedelta(days=4)).replace(day=1); previous = (shown - timedelta(days=1)).replace(day=1); visits = Appointment.query.filter(Appointment.start >= datetime.combine(shown, datetime.min.time()), Appointment.start < datetime.combine(next_month, datetime.min.time())).order_by(Appointment.start).all(); people = Inquiry.query.order_by(Inquiry.name).all(); names = {person.id: person.name for person in people}; events = {}
        for visit in visits: events.setdefault(visit.start.date(), []).append(visit)
        grid_start = shown - timedelta(days=shown.weekday()); cells = [grid_start + timedelta(days=index) for index in range(42)]; view = request.args.get("view", "month"); default_date = request.args.get("date", "") or recovered.get("service_date", "")
        return render("Calendar", screen_template("calendar.html"), previous=previous, next_month=next_month, shown=shown, people=people, statuses=VALID_VISIT_STATUSES, cells=cells, events=events, names=names, today=local_today(), view=view, recovered=recovered, default_date=default_date)

    @app.route("/owner/calendar/appointment/<int:ident>", methods=["GET", "POST"])
    @login_required
    def phase_two_appointment(ident):
        visit = db.get_or_404(Appointment, ident); person = db.get_or_404(Inquiry, visit.inquiry_id)
        if request.method == "POST":
            try:
                service_date = date.fromisoformat(request.form["service_date"]); start = datetime.combine(service_date, datetime.strptime(request.form["start_time"], "%H:%M").time()); end = datetime.combine(service_date, datetime.strptime(request.form["end_time"], "%H:%M").time()); status = request.form["status"]
                if end <= start or status not in VALID_VISIT_STATUSES: raise ValueError("Enter a valid visit range.")
                if status not in ["cancelled", "rescheduled"]:
                    conflict = Appointment.query.filter(Appointment.id != ident, Appointment.start < end, Appointment.end > start, Appointment.status.notin_(["cancelled", "rescheduled"])).first()
                    if conflict: raise ValueError("This overlaps another active visit.")
                previous_start = visit.start; visit.start = start; visit.end = end; visit.status = status; visit.notes = request.form.get("notes", "")[:2000]; db.session.add(Activity(inquiry_id=person.id, kind="appointment", body="Visit updated from " + previous_start.strftime("%b %-d") + " to " + start.strftime("%b %-d") + " (" + status + ").")); audit("update", "appointment", visit.id, "Appointment updated to " + start.strftime("%b %-d, %Y %-I:%M %p") + " (" + status + ")."); db.session.commit(); flash("Appointment updated."); return redirect(url_for("appointment_editor", ident=ident))
            except (KeyError, ValueError) as error: flash(str(error))
        return render("Appointment", screen_template("appointment.html"), visit=visit, person=person, statuses=VALID_VISIT_STATUSES)

    @app.route("/owner/billing", methods=["GET", "POST"])
    @login_required
    def phase_two_billing():
        if account_role() not in ["owner", "manager"]: abort(403)
        recovered = recovered_form()
        if request.method == "POST":
            try:
                inquiry_id = int(request.form["inquiry_id"]); kind = request.form["kind"]
                if not db.session.get(Inquiry, inquiry_id) or kind not in ["estimate", "invoice"]: raise ValueError("Choose a customer and document type.")
                lines = parse_lines(request.form); subtotal = sum(line[1] * line[2] for line in lines)
                try: tax_rate = Decimal(request.form.get("tax_rate", "0") or "0")
                except InvalidOperation: raise ValueError("Enter a valid tax rate.")
                if not tax_rate.is_finite() or tax_rate < 0 or tax_rate > 20 or tax_rate.as_tuple().exponent < -2: raise ValueError("Tax must be between 0% and 20%, with at most two decimal places.")
                tax = int((Decimal(subtotal) * tax_rate / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)); total = int(subtotal) + tax; db.session.execute(text("BEGIN IMMEDIATE")); number = db.session.execute(text("SELECT COALESCE(MAX(id),0)+1 FROM document")).scalar_one(); document = Document(number=("EST" if kind == "estimate" else "INV") + "-" + str(number).zfill(5), kind=kind, inquiry_id=inquiry_id, description=request.form.get("summary", "Work as quoted").strip()[:300] or "Work as quoted", amount_cents=total, due=parsed_date(request.form.get("due")))
                db.session.add(document); db.session.flush()
                for position, (description, quantity, unit) in enumerate(lines, 1): db.session.add(DocumentLineItem(document_id=document.id, description=description, quantity=quantity, unit_cents=unit, sort_order=position))
                if tax: db.session.add(DocumentLineItem(document_id=document.id, description="Sales tax ({:g}%)".format(tax_rate), quantity=1, unit_cents=tax, sort_order=99))
                meta = DocumentMeta(document_id=document.id, delivery_status="draft", approval_status="pending" if kind == "estimate" else "not_applicable", expires=parsed_date(request.form.get("expires"))); db.session.add(meta); db.session.add(Activity(inquiry_id=inquiry_id, kind="billing", body=kind.title() + " " + document.number + " created.")); audit("create", "document", document.id, kind.title() + " " + document.number + " created."); db.session.commit(); return redirect(url_for("document_view", ident=document.id))
            except (KeyError, ValueError) as error:
                db.session.rollback(); flash(str(error)); return redirect_with_form("billing", inquiry=request.form.get("inquiry_id", ""))
        query = Document.query; term = request.args.get("q", "").strip(); kind = request.args.get("kind", ""); delivery = request.args.get("delivery", ""); payment = request.args.get("payment", ""); due_filter = request.args.get("due", ""); sort = request.args.get("sort", "newest")
        try:
            date_from = parsed_date(request.args.get("date_from", "")); date_to = parsed_date(request.args.get("date_to", ""))
        except ValueError:
            date_from = date_to = None
        if term: query = query.join(Inquiry).filter(db.or_(Document.number.ilike("%" + term + "%"), Inquiry.name.ilike("%" + term + "%")))
        if kind in ["estimate", "invoice"]: query = query.filter_by(kind=kind)
        paid_sum = db.session.query(Payment.document_id.label("doc_id"), func.sum(case((Payment.kind == "payment", Payment.amount_cents), else_=-Payment.amount_cents)).label("paid")).group_by(Payment.document_id).subquery()
        remaining = Document.amount_cents - func.coalesce(paid_sum.c.paid, 0)
        status = case((Document.status == "void", "void"), (Document.kind != "invoice", "not_applicable"), (remaining <= 0, "paid"), (remaining < Document.amount_cents, "partial"), else_="unpaid")
        query = query.outerjoin(paid_sum, paid_sum.c.doc_id == Document.id).outerjoin(DocumentMeta, DocumentMeta.document_id == Document.id)
        if delivery: query = query.filter(DocumentMeta.delivery_status == delivery)
        if payment: query = query.filter(status.in_(["unpaid", "partial"]) if payment == "open" else status == payment)
        if date_from: query = query.filter(Document.created >= datetime.combine(date_from, datetime.min.time()))
        if date_to: query = query.filter(Document.created < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
        if due_filter == "overdue": query = query.filter(Document.kind == "invoice", Document.due < local_today(), remaining > 0, Document.status != "void")
        if sort == "due": query = query.order_by(Document.due.is_(None), Document.due, Document.id)
        elif sort == "balance": query = query.order_by(case((Document.kind == "invoice", remaining), else_=0).desc(), Document.id.desc())
        else: sort = "newest"; query = query.order_by(Document.created.desc(), Document.id.desc())
        page_number = max(1, request.args.get("page", 1, type=int)); page = query.paginate(page=page_number, per_page=25, error_out=False)
        shown = page.items; total_pages = max(1, page.pages)
        people = Inquiry.query.order_by(Inquiry.name).all(); names = {person.id: person.name for person in people}
        summary = db.session.query(Document.id, remaining.label("remaining"), status.label("state"), Document.due).outerjoin(paid_sum, paid_sum.c.doc_id == Document.id).filter(Document.kind == "invoice").subquery()
        open_total, overdue_total, overdue_count, partial_count, paid_count = db.session.query(
            func.coalesce(func.sum(case((summary.c.state.in_(["unpaid", "partial"]), summary.c.remaining), else_=0)), 0),
            func.coalesce(func.sum(case((db.and_(summary.c.state.in_(["unpaid", "partial"]), summary.c.due < local_today()), summary.c.remaining), else_=0)), 0),
            func.count(case((db.and_(summary.c.state.in_(["unpaid", "partial"]), summary.c.due < local_today()), 1))),
            func.count(case((summary.c.state == "partial", 1))), func.count(case((summary.c.state == "paid", 1)))).one()
        draft_count = DocumentMeta.query.filter_by(delivery_status="draft").count()
        return render("Billing", screen_template("billing.html"), people=people, recovered=recovered, term=term, kind=kind, delivery=delivery, payment=payment, due_filter=due_filter, date_from=date_from, date_to=date_to, sort=sort, shown=shown, page_number=page_number, total_pages=total_pages, names=names, meta=doc_meta, payment_status=payment_status, money=money, balance=balance, open_total=open_total, overdue_total=overdue_total, overdue_count=overdue_count, partial_count=partial_count, paid_count=paid_count, draft_count=draft_count)

    @app.route("/owner/billing/<int:ident>", methods=["GET", "POST"])
    @login_required
    def phase_two_document(ident):
        if account_role() not in ["owner", "manager"]: abort(403)
        document = db.get_or_404(Document, ident); person = db.get_or_404(Inquiry, document.inquiry_id); meta = doc_meta(document)
        if request.method == "POST":
            action = request.form.get("action")
            if action == "meta":
                delivery = request.form.get("delivery_status"); approval = request.form.get("approval_status")
                if delivery not in ["draft", "ready", "sent", "failed"] or approval not in ["pending", "accepted", "declined", "expired", "not_applicable"]: abort(400)
                meta.delivery_status = delivery; meta.approval_status = approval; meta.expires = parsed_date(request.form.get("expires"))
            elif action in ["payment", "refund"]:
                try:
                    amount = cents(request.form.get("amount", "")); method = request.form.get("method", "").strip(); outstanding = balance(document); paid = document.amount_cents - outstanding
                    if document.kind != "invoice" or not method or len(method) > 50 or (action == "payment" and amount > outstanding) or (action == "refund" and amount > paid): raise ValueError
                    db.session.add(Payment(document_id=document.id, amount_cents=amount, kind=action, method=method)); db.session.flush(); document.status = "paid" if action == "payment" and amount == outstanding else "sent"
                except ValueError: flash("Payment amount or method is not valid."); return redirect(url_for("document_view", ident=ident))
            elif action == "convert" and document.kind == "estimate":
                existing = Document.query.filter_by(converted_from=document.id).first()
                if existing: return redirect(url_for("document_view", ident=existing.id))
                number = db.session.execute(text("SELECT COALESCE(MAX(id),0)+1 FROM document")).scalar_one(); invoice = Document(number="INV-" + str(number).zfill(5), kind="invoice", inquiry_id=document.inquiry_id, description=document.description, amount_cents=document.amount_cents, converted_from=document.id, due=document.due); db.session.add(invoice); db.session.flush()
                for line in DocumentLineItem.query.filter_by(document_id=document.id): db.session.add(DocumentLineItem(document_id=invoice.id, description=line.description, quantity=line.quantity, unit_cents=line.unit_cents, sort_order=line.sort_order))
                db.session.add(DocumentMeta(document_id=invoice.id, delivery_status="draft", approval_status="not_applicable")); audit("convert", "document", invoice.id, "Estimate converted to invoice " + invoice.number + "."); db.session.commit(); return redirect(url_for("document_view", ident=invoice.id))
            else: abort(400)
            audit("update", "document", document.id, "Document workflow updated: " + action + ".")
            db.session.commit(); flash("Document updated."); return redirect(url_for("document_view", ident=ident))
        lines = DocumentLineItem.query.filter_by(document_id=document.id).order_by(DocumentLineItem.sort_order).all(); payments = Payment.query.filter_by(document_id=document.id).order_by(Payment.id.desc()).all(); remaining = balance(document)
        return render("Document", screen_template("document.html"), document=document, person=person, meta=meta, lines=lines, payments=payments, remaining=remaining, money=money, line_total=line_total, payment_status=payment_status)

    @app.get("/owner/export.csv")
    @login_required
    def phase_two_export():
        if account_role() not in ["owner", "manager"]: abort(403)
        import csv
        query, _ = query_inquiries(); output = BytesIO(); text_output = __import__('io').StringIO(); writer = csv.writer(text_output); writer.writerow(["Name", "Contact", "Service", "Location", "Details", "Stage", "Urgency", "Follow-up"])
        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value
        for item in query.order_by(Inquiry.id): writer.writerow([safe(value) for value in [item.name, item.contact, item.service, item.location, item.details, item.stage, item.urgency, item.followup]])
        audit("export", "inquiry", 0, "Filtered inquiry CSV exported."); db.session.commit()
        output.write(text_output.getvalue().encode("utf-8")); output.seek(0)
        return send_file(output, mimetype="text/csv", as_attachment=True, download_name="surge-inquiries.csv")

    def phase_two_document_pdf(ident):
        if account_role() not in ["owner", "manager"]: abort(403)
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.utils import simpleSplit
        document = db.get_or_404(Document, ident)
        person = db.get_or_404(Inquiry, document.inquiry_id)
        profile = get_business_profile()
        metadata = doc_meta(document)
        lines = DocumentLineItem.query.filter_by(document_id=ident).order_by(DocumentLineItem.sort_order).all()
        tax_lines = [line for line in lines if line.description.lower().startswith("sales tax")]
        item_lines = [line for line in lines if line not in tax_lines]
        subtotal = sum(line_total(line) for line in item_lines) if lines else document.amount_cents
        tax = sum(line_total(line) for line in tax_lines) if tax_lines else max(0, document.amount_cents - subtotal)
        buffer = BytesIO(); pdf = canvas.Canvas(buffer, pagesize=letter); width, height = letter
        pdf.setFillColorRGB(.04,.04,.035); pdf.rect(0,height-112,width,112,fill=1,stroke=0)
        pdf.setFillColorRGB(.91,.82,.66); pdf.setFont("Helvetica-Bold",21); pdf.drawString(48,height-53,profile.company_name[:55])
        pdf.setFillColorRGB(1,1,1); pdf.setFont("Helvetica",9)
        identity = [profile.phone, profile.email, profile.business_address, ("Arizona ROC #" + profile.roc_number) if profile.roc_number else ""]
        pdf.drawString(48,height-78,"  ·  ".join(value for value in identity if value)[:115])
        pdf.setFillColorRGB(.12,.1,.08); pdf.setFont("Helvetica-Bold",17); pdf.drawString(48,height-147,document.kind.title()+"  "+document.number)
        pdf.setFont("Helvetica-Bold",9); pdf.drawString(48,height-176,"CUSTOMER")
        pdf.setFont("Helvetica",10); pdf.drawString(48,height-193,person.name[:80]); pdf.drawString(48,height-209,person.contact[:95])
        y=height-246; pdf.setFillColorRGB(.38,.34,.29); pdf.setFont("Helvetica-Bold",8); pdf.drawString(48,y,"DESCRIPTION"); pdf.drawRightString(width-48,y,"AMOUNT")
        y-=15; pdf.setStrokeColorRGB(.82,.78,.72); pdf.line(48,y,width-48,y); pdf.setFillColorRGB(.12,.1,.08); pdf.setFont("Helvetica",9)
        if lines:
            for line in item_lines:
                wrapped=simpleSplit(line.description,"Helvetica",9,365)
                pdf.drawString(48,y-12,wrapped[0][:110]); pdf.drawRightString(width-48,y-12,money(line_total(line))); y-=16
                for extra in wrapped[1:]: pdf.drawString(48,y-7,extra[:110]); y-=13
                if y<125: pdf.showPage(); y=height-60
        else:
            pdf.drawString(48,y-12,document.description[:110]); pdf.drawRightString(width-48,y-12,money(document.amount_cents)); y-=22
        y-=7; pdf.setFont("Helvetica",9); pdf.drawRightString(width-100,y,"Subtotal"); pdf.drawRightString(width-48,y,money(subtotal)); y-=15
        if tax:
            pdf.drawRightString(width-100,y,"Tax / adjustment"); pdf.drawRightString(width-48,y,money(tax)); y-=15
        pdf.setFont("Helvetica-Bold",11); pdf.drawRightString(width-100,y,"Total"); pdf.drawRightString(width-48,y,money(document.amount_cents)); y-=17
        if document.kind=="invoice":
            pdf.drawRightString(width-100,y,"Balance due"); pdf.drawRightString(width-48,y,money(balance(document))); y-=18
        if document.due:
            pdf.setFont("Helvetica",9); pdf.drawString(48,y,"Due date: " + document.due.strftime("%B %-d, %Y")); y-=16
        elif document.kind == "estimate" and metadata.expires:
            pdf.setFont("Helvetica",9); pdf.drawString(48,y,"Estimate valid through: " + metadata.expires.strftime("%B %-d, %Y")); y-=16
        for heading, text_value in [("PAYMENT INSTRUCTIONS",profile.payment_instructions),("TERMS",profile.invoice_terms)]:
            if text_value:
                y-=8; pdf.setFont("Helvetica-Bold",8); pdf.drawString(48,y,heading); y-=12; pdf.setFont("Helvetica",8)
                for row in simpleSplit(text_value,"Helvetica",8,width-96):
                    if y<48: pdf.showPage(); y=height-48; pdf.setFont("Helvetica",8)
                    pdf.drawString(48,y,row); y-=11
        pdf.setFillColorRGB(.45,.4,.34); pdf.setFont("Helvetica",7)
        footer=" · ".join(value for value in [profile.license_statement, ("Arizona ROC #"+profile.roc_number) if profile.roc_number else ""] if value)
        pdf.drawString(48,30,footer[:120]); pdf.save(); buffer.seek(0)
        audit("download", "document", document.id, document.number + " PDF downloaded."); db.session.commit()
        return send_file(buffer,mimetype="application/pdf",as_attachment=True,download_name=document.number+".pdf")

    def phase_two_home():
        from public_shell import page
        from markupsafe import escape
        token = generate_csrf()
        profile = get_business_profile()
        recovery = session.pop("public_form_recovery", {})
        notice = session.pop("public_form_notice", "")
        markup = '''<header><a class="brand" href="#top" aria-label="Surge Power home"><img src="/static/surge-power-logo.png" alt="Surge Power LLC"></a><nav class="desktop-nav" aria-label="Main navigation"><a href="#services">Services</a><a href="#work">Our work</a><a href="#process">How it works</a><a href="#contact">Contact</a></nav><details class="mobile-menu"><summary>Menu</summary><nav aria-label="Mobile navigation"><a href="#services">Services</a><a href="#work">Our work</a><a href="#process">How it works</a><a href="#contact">Contact</a></nav></details><a class="btn" href="#contact">Request a quote ↗</a></header><main id="top"><section class="hero"><div class="hero-copy"><p class="eyebrow">EAST VALLEY · PHOENIX METRO</p><h1>EV charging,<br>powered right.</h1><p class="lead">Surge Power installs EV chargers and handles the electrical work that keeps homes and businesses ready for what’s next.</p><div class="hero-actions"><a class="btn" href="#contact">Request an installation quote ↗</a><a class="text-link" href="#services">Explore services</a></div><ul class="trust-list"><li>East Valley based</li><li>Phoenix metro service</li><li>Residential & commercial</li></ul></div><div class="charge-scene" role="img" aria-label="Illustration of an EV charging station"><div class="cable"></div><div class="charger"></div><div class="scene-caption">A better way to power your day<span>EV charging · General electrical work</span></div></div></section><section class="section service-intro" id="services"><p class="eyebrow">WHAT WE DO</p><h2>Electrical work with a clear next step.</h2><div class="grid"><article class="card"><b>01 / EV CHARGING</b><h3>EV charger installation</h3><p>Home and business charger installation planned around your vehicle, parking setup, panel capacity, and daily routine.</p><a href="#contact">Request an EV quote →</a></article><article class="card"><b>02 / ELECTRICAL</b><h3>General electrical work</h3><p>New circuits, electrical updates, and project guidance for the places you live and work.</p><a href="#contact">Talk through your project →</a></article><article class="card"><b>03 / PLANNING</b><h3>Project guidance</h3><p>Bring the details you have. We’ll help identify the practical next step before work begins.</p><a href="#contact">Start the conversation →</a></article></div></section><!-- CURATED_PROJECTS --><section class="section dark" id="process"><p class="eyebrow">A STRAIGHTFORWARD PROCESS</p><h2>From first message to powered-up.</h2><div class="grid process-grid"><article class="card"><b>01</b><h3>Share the project</h3><p>Tell us where you are, what you need, and how to reach you.</p></article><article class="card"><b>02</b><h3>Talk through the details</h3><p>We’ll discuss the location, scope, and next step for the work.</p></article><article class="card"><b>03</b><h3>Move forward clearly</h3><p>You’ll have a clear path for scheduling and the work ahead.</p></article></div></section><section class="section service-area"><p class="eyebrow">WHERE WE WORK</p><h2>East Valley based.<br>Phoenix connected.</h2><p>Surge Power LLC serves homeowners and businesses throughout the Phoenix metro area.</p></section><section class="section contact" id="contact"><div><p class="eyebrow">LET’S GET TO WORK</p><h2>Tell us what you’re powering.</h2><p>Send a few details and your preferred contact method. We’ll use your request to plan the next conversation.</p><p class="contact-note">Prefer Instagram? <a href="https://www.instagram.com/theazevguy/">Find Surge Power there ↗</a></p></div><form method="post" action="/inquiry"><input type="hidden" name="csrf_token" value="'''+token+'''"><label>Name<input name="name" maxlength="100" autocomplete="name" required></label><label>Phone or email<input name="contact" maxlength="200" autocomplete="tel" required></label><label>What can we help with?<select name="service"><option>EV charger installation</option><option>General electrical work</option><option>Other project</option></select></label><label>City or area<input name="location" maxlength="100" autocomplete="address-level2"></label><label>Project details<textarea name="details" rows="4" maxlength="3000" placeholder="Tell us about the location, project, or charger you have in mind."></textarea></label><div class="form-submit"><button>Send request ↗</button><small>We’ll use these details only to respond to your request.</small></div></form></section></main><footer><div><strong>SURGE POWER LLC</strong><p>EV charger installation and electrical work for the Phoenix metro.</p></div><div><a href="/privacy">Privacy</a><a href="https://www.instagram.com/theazevguy/">Instagram ↗</a></div></footer>'''
        from flask import render_template
        markup = markup.replace('<!-- CURATED_PROJECTS -->', render_template('projects.html'))
        markup = markup.replace(
            '<li>Residential & commercial</li></ul>',
            '<li>Residential & commercial</li><li>Licensed, bonded &amp; insured</li><li>Arizona ROC #336067</li></ul>',
        )
        markup = markup.replace(
            'Surge Power LLC serves homeowners and businesses throughout the Phoenix metro area.</p>',
            'Surge Power LLC serves homeowners and businesses throughout the Phoenix metro area. Licensed, bonded &amp; insured. Arizona ROC #336067.</p>',
        )
        markup = markup.replace(
            'EV charger installation and electrical work for the Phoenix metro.</p>',
            'EV charger installation and electrical work for the Phoenix metro.<br>Licensed, bonded &amp; insured · Arizona ROC #336067</p>',
        )
        phone = str(escape(profile.phone))
        phone_digits = "".join(character for character in profile.phone if character.isdigit())
        if len(phone_digits) == 10: phone_digits = "1" + phone_digits
        area = str(escape(profile.service_area))
        license_text = str(escape(profile.license_statement))
        roc_text = ("Arizona ROC #" + str(escape(profile.roc_number))) if profile.roc_number else ""
        markup = markup.replace("EAST VALLEY · PHOENIX METRO", area.upper())
        markup = markup.replace("East Valley based.", area.split("·")[0].strip() + " based.")
        markup = markup.replace("Phoenix connected.", area.split("·")[-1].strip() + " connected.")
        markup = markup.replace("Licensed, bonded &amp; insured", license_text)
        markup = markup.replace("Arizona ROC #336067", roc_text)
        markup = markup.replace(
            '<a class="btn" href="#contact">Request a quote ↗</a>',
            '<a class="btn" href="#contact">Request a quote ↗</a><a class="header-phone" href="tel:+' + phone_digits + '">' + phone + '</a>',
        )
        markup = markup.replace(
            '<p class="contact-note">Prefer Instagram?',
            '<p class="contact-note"><a class="contact-phone" href="tel:+' + phone_digits + '">Call ' + phone + '</a> · Prefer Instagram?',
        )
        if profile.email:
            email = str(escape(profile.email))
            markup = markup.replace('<p class="contact-note">', '<p class="contact-note"><a href="mailto:' + email + '">' + email + '</a> · ')
        if profile.business_hours:
            markup = markup.replace('<p class="contact-note">', '<p class="contact-hours">' + str(escape(profile.business_hours)) + '</p><p class="contact-note">')
        markup = markup.replace(
            '<input type="hidden" name="csrf_token" value="' + token + '">',
            '<input type="hidden" name="csrf_token" value="' + token + '"><div class="form-trap" aria-hidden="true"><label>Leave this field empty<input name="website" tabindex="-1" autocomplete="off"></label></div>',
        )
        markup = markup.replace(
            '<p id="project-selection" class="project-selection" role="status" aria-live="polite"></p><label>Name<input',
            '<p id="project-selection" class="project-selection" role="status" aria-live="polite"></p>' + ('<p class="form-notice" role="status">' + str(escape(notice)) + '</p>' if notice else '') + '<label>Name<input',
        )
        for field in ["name", "contact", "location"]:
            name_attr = 'name="' + field + '"'
            replacement = name_attr + ' value="' + str(escape(recovery.get(field, ""))) + '"'
            markup = markup.replace(name_attr, replacement, 1)
        if recovery.get("details"):
            markup = markup.replace('<textarea name="details"', '<textarea name="details"')
            markup = markup.replace('maxlength="3000" placeholder="Tell us about the location, project, or charger you have in mind."></textarea>', 'maxlength="3000" placeholder="Tell us about the location, project, or charger you have in mind.">' + str(escape(recovery["details"])) + '</textarea>')
        markup = markup.replace(
            '</select></label><label>City or area',
            '</select></label><label>Preferred contact<select name="preferred_contact"><option value="contact">Either phone or email</option><option value="phone" ' + ('selected' if recovery.get('preferred_contact')=='phone' else '') + '>Phone</option><option value="email" ' + ('selected' if recovery.get('preferred_contact')=='email' else '') + '>Email</option></select></label><label>Best time<select name="best_time"><option value="anytime">Any time</option><option value="morning" ' + ('selected' if recovery.get('best_time')=='morning' else '') + '>Morning</option><option value="afternoon" ' + ('selected' if recovery.get('best_time')=='afternoon' else '') + '>Afternoon</option><option value="evening" ' + ('selected' if recovery.get('best_time')=='evening' else '') + '>Evening</option></select></label><label>Property type<select name="property_type"><option value="unspecified">Not sure yet</option><option value="home" ' + ('selected' if recovery.get('property_type')=='home' else '') + '>Home</option><option value="business" ' + ('selected' if recovery.get('property_type')=='business' else '') + '>Business</option></select></label><label>Vehicle or equipment (optional)<input name="vehicle_or_equipment" maxlength="160" value="' + str(escape(recovery.get('vehicle_or_equipment',''))) + '" placeholder="Vehicle, charger, or equipment"></label><label>City or area',
        )
        markup = markup.replace(
            '<button>Send request ↗</button><small>We’ll use these details only to respond to your request.</small>',
            '<label class="consent-check"><input type="checkbox" name="consent" value="yes" required ' + ('checked' if recovery.get('consent')=='yes' else '') + '> I agree Surge Power may use these details to respond to my project request. See the <a href="/privacy">privacy notice</a>.</label><button>Send request ↗</button><small>We’ll use these details only to respond to your request.</small>',
        )
        notice_class = "success" if request.args.get("sent") == "1" else "error"
        form_notice = '<p class="form-notice ' + notice_class + '" role="status">' + str(escape(notice)) + '</p>' if notice else ""
        markup = markup.replace('<label>Name<input', form_notice + '<p id="project-selection" class="project-selection" role="status" aria-live="polite"></p><label>Name<input')
        from json import dumps
        base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        seo = '<meta property="og:title" content="Surge Power LLC | EV charging & electrical work"><meta property="og:description" content="EV charger installation and general electrical work throughout the Phoenix metro."><meta name="twitter:card" content="summary_large_image">'
        if base_url.startswith("https://"):
            canonical = str(escape(base_url + "/"))
            seo += '<link rel="canonical" href="' + canonical + '"><meta property="og:url" content="' + canonical + '"><meta property="og:image" content="' + str(escape(base_url + "/static/surge-power-logo.png")) + '">'
        business_data = {"@context":"https://schema.org","@type":"Electrician","name":profile.company_name,"telephone":profile.phone,"areaServed":profile.service_area,"description":"EV charger installation and general electrical work throughout the Phoenix metro."}
        if profile.roc_number: business_data["identifier"] = "Arizona ROC #" + profile.roc_number
        if base_url.startswith("https://"): business_data["url"] = base_url + "/"
        seo += '<script type="application/ld+json">' + dumps(business_data, ensure_ascii=True).replace("<", "\\u003c") + '</script>'
        return page(markup, "Surge Power LLC | EV Charger Installation & Electrical Work").replace('</head>', seo + '<link rel="stylesheet" href="/static/portfolio.css?v=1"><script src="/static/portfolio.js?v=1" defer></script></head>')

    app.view_functions["dashboard"] = phase_two_dashboard
    app.view_functions["create_inquiry"] = phase_two_create_inquiry
    app.view_functions["inquiries"] = phase_two_inquiries
    app.view_functions["inquiry_detail"] = phase_two_inquiry
    app.view_functions["calendar_view"] = phase_two_calendar
    app.view_functions["appointment_editor"] = phase_two_appointment
    app.view_functions["billing"] = phase_two_billing
    app.view_functions["document_view"] = phase_two_document
    app.view_functions["document_pdf"] = phase_two_document_pdf
    app.view_functions["export_inquiries"] = phase_two_export
    app.view_functions["home"] = phase_two_home
