"""Connected workspace experience for Surge Power's Flask application."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from calendar import monthrange
from io import BytesIO
from textwrap import wrap

from flask import abort, flash, redirect, request, send_file, url_for
from flask_login import login_required
from flask_wtf.csrf import generate_csrf
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from sqlalchemy import func, text

from backend import (
    db, Inquiry, Activity, Appointment, Document, Payment, SERVICES, STAGES,
    cents, balance, parsed_date, render, local_today, utc_now
)


class WorkTask(db.Model):
    __tablename__ = "work_task"
    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiry.id"), nullable=False, index=True)
    title = db.Column(db.String(220), nullable=False)
    due = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    created = db.Column(db.DateTime, nullable=False, default=utc_now)


class DocumentLineItem(db.Model):
    __tablename__ = "document_line_item"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("document.id"), nullable=False, index=True)
    description = db.Column(db.String(300), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    unit_cents = db.Column(db.Integer, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)


def money(cents_value):
    return "${:,.2f}".format((cents_value or 0) / 100)


def line_total(line):
    return int((Decimal(line.quantity) * line.unit_cents).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_lines(form):
    lines = []
    for number in range(1, 7):
        description = form.get(f"line_description_{number}", "").strip()
        quantity = form.get(f"line_quantity_{number}", "").strip()
        unit = form.get(f"line_price_{number}", "").strip()
        if not (description or quantity or unit):
            continue
        try:
            qty = Decimal(quantity or "1")
            unit_cents = cents(unit)
            if qty <= 0 or qty > 10000 or qty.as_tuple().exponent < -2:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("Each line needs a description, a positive quantity, and a valid unit price.")
        if not description or len(description) > 300:
            raise ValueError("Each line item needs a description under 300 characters.")
        lines.append((description, qty, unit_cents))
    if not lines:
        raise ValueError("Add at least one line item.")
    return lines


def install_workspace_upgrade(app):
    if app.config.get("AUTO_CREATE_SCHEMA", True):
        with app.app_context():
            db.create_all()

    @app.after_request
    def workspace_assets(response):
        if response.mimetype == "text/html":
            markup = response.get_data(as_text=True)
            if "/static/workspace.css" not in markup:
                response.set_data(markup.replace("</head>", '<link rel="stylesheet" href="/static/workspace.css?v=1"></head>'))
                markup = response.get_data(as_text=True)
            if request.path.startswith("/owner") and 'href="/owner/dashboard"' not in markup:
                markup = markup.replace('<nav><a href="/owner/inquiries">', '<nav><a href="/owner/dashboard">Today</a><a href="/owner/inquiries">')
            if request.path == "/owner/dashboard":
                markup = markup.replace('href="/owner/dashboard"', 'aria-current="page" href="/owner/dashboard"', 1)
            response.set_data(markup)
        return response

    @app.before_request
    def owner_home_to_dashboard():
        if request.path == "/owner":
            return redirect(url_for("dashboard"))

    @app.route("/owner/dashboard")
    @login_required
    def dashboard():
        today = local_today()
        tomorrow = today + timedelta(days=1)
        new_count = Inquiry.query.filter_by(stage="new").count()
        overdue = Inquiry.query.filter(Inquiry.followup.isnot(None), Inquiry.followup < today, Inquiry.stage.notin_(["won", "lost", "closed"])).order_by(Inquiry.followup).all()
        due_today = Inquiry.query.filter(Inquiry.followup == today).order_by(Inquiry.created).all()
        visits = Appointment.query.filter(Appointment.start >= datetime.combine(today, datetime.min.time()), Appointment.start < datetime.combine(tomorrow, datetime.min.time()), Appointment.status.notin_(["cancelled", "rescheduled"])).order_by(Appointment.start).all()
        task_rows = WorkTask.query.filter_by(status="open").filter(WorkTask.due <= today).order_by(WorkTask.due, WorkTask.created).limit(8).all()
        docs = Document.query.filter(Document.kind == "invoice", Document.status == "sent").all()
        outstanding = sum(max(0, balance(doc)) for doc in docs)
        estimates = Document.query.filter_by(kind="estimate", status="sent").count()
        names = {item.id: item.name for item in Inquiry.query.all()}
        return render("Today", '''
        <div class="workspace-heading"><div><p class="eyebrow">OWNER WORKSPACE</p><h1>Today’s work</h1><p>Priorities, visits, follow-ups, and money in one place.</p></div><a class="button primary-action" href="{{url_for('create_inquiry')}}">Add inquiry</a></div>
        <section class="dashboard-metrics">
          <a href="{{url_for('inquiries',stage='new')}}"><strong>{{new_count}}</strong><span>New inquiries</span></a>
          <a href="{{url_for('inquiries',followup='overdue')}}"><strong>{{overdue|length}}</strong><span>Overdue follow-ups</span></a>
          <a href="{{url_for('billing',status='sent')}}"><strong>{{money(outstanding)}}</strong><span>Outstanding invoices</span></a>
          <a href="{{url_for('billing',kind='estimate',status='sent')}}"><strong>{{estimates}}</strong><span>Open estimates</span></a>
        </section>
        <section class="dashboard-grid">
          <article class="panel dashboard-panel"><div class="panel-title"><h2>Today’s visits</h2><a href="{{url_for('calendar_view')}}">Calendar →</a></div>{% for visit in visits %}<a class="work-row" href="{{url_for('appointment_editor', ident=visit.id)}}"><time>{{visit.start.strftime('%-I:%M %p')}}</time><span><strong>{{names.get(visit.inquiry_id,'Customer')}}</strong><small>{{visit.status|title}} · {{visit.notes or 'Visit details'}}</small></span><b>Open</b></a>{% else %}<p class="empty">No visits scheduled today.</p>{% endfor %}</article>
          <article class="panel dashboard-panel"><div class="panel-title"><h2>Follow-ups</h2><a href="{{url_for('inquiries',followup='due')}}">View all →</a></div>{% for lead in overdue + due_today %}<a class="work-row" href="{{url_for('inquiry_detail',ident=lead.id)}}"><time>{{lead.followup.strftime('%b %-d')}}</time><span><strong>{{lead.name}}</strong><small>{{lead.service}} · {{lead.location or 'Location pending'}}</small></span><b class="{{'danger' if lead.followup < today else ''}}">{{'Overdue' if lead.followup < today else 'Today'}}</b></a>{% else %}<p class="empty">No follow-ups need attention.</p>{% endfor %}</article>
          <article class="panel dashboard-panel"><div class="panel-title"><h2>Tasks</h2></div>{% for task in task_rows %}<a class="work-row" href="{{url_for('inquiry_detail',ident=task.inquiry_id)}}"><time>{{task.due.strftime('%b %-d') if task.due else '—'}}</time><span><strong>{{task.title}}</strong><small>{{names.get(task.inquiry_id,'Customer')}}</small></span><b>Open</b></a>{% else %}<p class="empty">No overdue tasks.</p>{% endfor %}</article>
        </section>''', new_count=new_count, overdue=overdue, due_today=due_today, visits=visits, task_rows=task_rows, outstanding=outstanding, estimates=estimates, names=names, money=money, today=today)

    @app.route("/owner/inquiries/new", methods=["GET", "POST"])
    @login_required
    def create_inquiry():
        if request.method == "POST":
            name = request.form.get("name", "").strip(); contact = request.form.get("contact", "").strip()
            service = request.form.get("service", ""); location = request.form.get("location", "").strip(); details = request.form.get("details", "").strip()
            if not name or not contact or service not in SERVICES or len(name) > 100 or len(contact) > 200 or len(location) > 100 or len(details) > 3000:
                flash("Add a name, contact method, service, and valid project details.")
            else:
                item = Inquiry(name=name, contact=contact, service=service, location=location, details=details, stage="new")
                db.session.add(item); db.session.commit(); flash("Inquiry added. Set the next action while the details are fresh.")
                return redirect(url_for("inquiry_detail", ident=item.id))
        return render("Add inquiry", '''<p><a href="{{url_for('dashboard')}}">← Today</a></p><h1>Add inquiry</h1><p>Use this for calls, referrals, or Instagram messages.</p><form method="post" class="panel form-grid"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Name<input name="name" required maxlength="100"></label><label>Phone or email<input name="contact" required maxlength="200"></label><label>Service<select name="service">{% for service in services %}<option>{{service}}</option>{% endfor %}</select></label><label>City or area<input name="location" maxlength="100"></label><label class="span-full">Project details<textarea name="details" rows="5" maxlength="3000"></textarea></label><button>Add inquiry</button></form>''', services=SERVICES)

    @app.route("/owner/inquiries")
    @login_required
    def upgraded_inquiries():
        query = Inquiry.query
        search = request.args.get("q", "").strip(); stage = request.args.get("stage", ""); urgency = request.args.get("urgency", ""); followup = request.args.get("followup", ""); service = request.args.get("service", ""); order = request.args.get("order", "priority")
        if search: query = query.filter(db.or_(Inquiry.name.ilike("%"+search+"%"), Inquiry.contact.ilike("%"+search+"%"), Inquiry.location.ilike("%"+search+"%")))
        if stage in STAGES: query = query.filter_by(stage=stage)
        if urgency in ["urgent", "within a week", "flexible", "unspecified"]: query = query.filter_by(urgency=urgency)
        if service in SERVICES: query = query.filter_by(service=service)
        today = local_today()
        if followup == "overdue": query = query.filter(Inquiry.followup < today)
        elif followup == "due": query = query.filter(Inquiry.followup <= today, Inquiry.followup.isnot(None))
        elif followup == "none": query = query.filter(Inquiry.followup.is_(None))
        if order == "oldest": query = query.order_by(Inquiry.created.asc())
        elif order == "followup": query = query.order_by(Inquiry.followup.is_(None), Inquiry.followup.asc(), Inquiry.created.desc())
        else: query = query.order_by(Inquiry.followup.is_(None), Inquiry.followup.asc(), Inquiry.created.desc())
        page = query.paginate(page=max(1, request.args.get("page", 1, type=int)), per_page=25, error_out=False)
        totals = dict(db.session.query(Inquiry.stage, func.count(Inquiry.id)).group_by(Inquiry.stage).all())
        return render("Inquiries", '''<div class="workspace-heading"><div><h1>Inquiries</h1><p>Sort by the next action, then keep each lead moving.</p></div><a class="button primary-action" href="{{url_for('create_inquiry')}}">Add inquiry</a></div><section class="stage-strip">{% for key in stages %}<a href="{{url_for('inquiries',stage=key)}}"><strong>{{totals.get(key,0)}}</strong><span>{{key}}</span></a>{% endfor %}</section><form class="filters filter-grid"><input name="q" value="{{request.args.get('q','')}}" placeholder="Search name, contact, area"><select name="stage"><option value="">All stages</option>{% for key in stages %}<option value="{{key}}" {{'selected' if stage==key}}>{{key|title}}</option>{% endfor %}</select><select name="service"><option value="">All services</option>{% for key in services %}<option {{'selected' if service==key}}>{{key}}</option>{% endfor %}</select><select name="followup"><option value="">Any follow-up</option><option value="overdue" {{'selected' if followup=='overdue'}}>Overdue</option><option value="due" {{'selected' if followup=='due'}}>Due today</option><option value="none" {{'selected' if followup=='none'}}>No follow-up</option></select><select name="order"><option value="priority">Next action first</option><option value="oldest" {{'selected' if order=='oldest'}}>Oldest first</option><option value="followup" {{'selected' if order=='followup'}}>Follow-up date</option></select><button>Apply</button><a href="{{url_for('inquiries')}}">Clear</a></form><p class="table-actions"><a href="{{url_for('export_inquiries')}}">Export these records</a> · {{page.total}} results</p><section class="inquiry-table"><div class="inquiry-head"><span>Customer</span><span>Project</span><span>Stage</span><span>Next action</span></div>{% for item in page.items %}<a class="inquiry-row" href="{{url_for('inquiry_detail',ident=item.id)}}"><span><strong>{{item.name}}</strong><small>{{item.contact}}</small></span><span><strong>{{item.service}}</strong><small>{{item.location or 'Location pending'}}</small></span><span><em class="status {{item.stage.replace(' ','-')}}">{{item.stage}}</em></span><span><strong class="{{'overdue' if item.followup and item.followup < today else ''}}">{{item.followup.strftime('%b %-d') if item.followup else 'Set follow-up'}}</strong><small>{{'Overdue' if item.followup and item.followup < today else 'Next step'}}</small></span></a>{% else %}<p class="empty">No inquiries match these filters.</p>{% endfor %}</section><nav class="pagination">{% if page.has_prev %}<a href="{{url_for('inquiries',page=page.prev_num,q=search,stage=stage,service=service,followup=followup,order=order)}}">← Previous</a>{% endif %}<span>Page {{page.page}} of {{page.pages or 1}}</span>{% if page.has_next %}<a href="{{url_for('inquiries',page=page.next_num,q=search,stage=stage,service=service,followup=followup,order=order)}}">Next →</a>{% endif %}</nav>''', page=page, stages=STAGES, services=SERVICES, totals=totals, stage=stage, service=service, followup=followup, order=order, search=search, today=today)

    @app.route("/owner/inquiries/<int:ident>", methods=["GET", "POST"])
    @login_required
    def upgraded_inquiry_detail(ident):
        item = db.get_or_404(Inquiry, ident)
        if request.method == "POST":
            action = request.form.get("action")
            if action == "update":
                stage = request.form.get("stage"); urgency = request.form.get("urgency")
                if stage not in STAGES or urgency not in ["urgent", "within a week", "flexible", "unspecified"]: abort(400)
                item.stage = stage; item.urgency = urgency; item.followup = parsed_date(request.form.get("followup")); item.name = request.form.get("name", item.name).strip()[:100]; item.contact = request.form.get("contact", item.contact).strip()[:200]; item.location = request.form.get("location", item.location).strip()[:100]; item.details = request.form.get("details", item.details).strip()[:3000]
                db.session.add(Activity(inquiry_id=ident, kind="update", body="Customer and workflow details updated."))
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
                task = db.session.get(WorkTask, int(request.form.get("task_id", 0)))
                if not task or task.inquiry_id != ident: abort(404)
                task.status = "done"
            else: abort(400)
            db.session.commit(); flash("Saved."); return redirect(url_for("inquiry_detail", ident=ident))
        appointments = Appointment.query.filter_by(inquiry_id=ident).order_by(Appointment.start.desc()).all(); docs = Document.query.filter_by(inquiry_id=ident).order_by(Document.created.desc()).all(); activities = Activity.query.filter_by(inquiry_id=ident).order_by(Activity.created.desc()).limit(100).all(); tasks = WorkTask.query.filter_by(inquiry_id=ident).order_by(WorkTask.status, WorkTask.due).all()
        return render("Customer", '''<p><a href="{{url_for('inquiries')}}">← Inquiries</a></p><div class="record-heading"><div><p class="eyebrow">{{item.service}}</p><h1>{{item.name}}</h1><p>{{item.location or 'Location pending'}} · {{item.contact}}</p></div><div class="record-actions"><a class="button" href="{{url_for('calendar_view',inquiry=item.id)}}">Schedule visit</a><a class="button primary-action" href="{{url_for('billing',inquiry=item.id)}}">Create estimate</a></div></div><section class="record-grid"><article class="panel"><h2>Customer & project</h2><form method="post" class="compact-form"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="update"><label>Name<input name="name" value="{{item.name}}"></label><label>Phone or email<input name="contact" value="{{item.contact}}"></label><label>Service area<input name="location" value="{{item.location}}"></label><label>Service<select name="service" disabled><option>{{item.service}}</option></select></label><label>Stage<select name="stage">{% for key in stages %}<option {{'selected' if item.stage==key}}>{{key}}</option>{% endfor %}</select></label><label>Urgency<select name="urgency">{% for key in urgencies %}<option {{'selected' if item.urgency==key}}>{{key}}</option>{% endfor %}</select></label><label>Follow-up<input type="date" name="followup" value="{{item.followup or ''}}"></label><label class="span-full">Project details<textarea name="details" rows="5">{{item.details}}</textarea></label><button>Save customer</button></form></article><article class="panel"><div class="panel-title"><h2>Upcoming work</h2><a href="{{url_for('calendar_view',inquiry=item.id)}}">Schedule →</a></div>{% for visit in appointments %}<a class="work-row" href="{{url_for('appointment_editor',ident=visit.id)}}"><time>{{visit.start.strftime('%b %-d')}}</time><span><strong>{{visit.start.strftime('%-I:%M %p')}}–{{visit.end.strftime('%-I:%M %p')}}</strong><small>{{visit.status|title}} · {{visit.notes or 'No notes'}}</small></span><b>Edit</b></a>{% else %}<p class="empty">No visits scheduled.</p>{% endfor %}<div class="panel-title section-break"><h2>Documents</h2><a href="{{url_for('billing',inquiry=item.id)}}">Create →</a></div>{% for doc in docs %}<a class="work-row" href="{{url_for('document_view',ident=doc.id)}}"><time>{{doc.number}}</time><span><strong>{{doc.kind|title}} · {{money(doc.amount_cents)}}</strong><small>{{doc.status|title}}{% if doc.due %} · due {{doc.due.strftime('%b %-d')}}{% endif %}</small></span><b>Open</b></a>{% else %}<p class="empty">No estimate or invoice yet.</p>{% endfor %}</article></section><section class="record-grid"><article class="panel"><h2>Next actions</h2><form method="post" class="task-form"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="task"><input name="title" placeholder="Add a task" required><input type="date" name="due"><button>Add</button></form>{% for task in tasks %}<div class="task-row"><span><strong>{{task.title}}</strong><small>{{task.due or 'No due date'}}</small></span>{% if task.status=='open' %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="complete_task"><input type="hidden" name="task_id" value="{{task.id}}"><button>Done</button></form>{% else %}<em>Done</em>{% endif %}</div>{% else %}<p class="empty">No tasks added.</p>{% endfor %}</article><article class="panel"><h2>Activity</h2><form method="post" class="activity-form"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="activity"><select name="kind"><option>note</option><option>call</option><option>email</option><option>meeting</option><option>other</option></select><textarea name="body" placeholder="Record what happened" required></textarea><button>Add activity</button></form>{% for activity in activities %}<div class="timeline"><strong>{{activity.kind|title}}</strong><small>{{activity.created.strftime('%b %-d, %Y · %-I:%M %p')}}</small><p>{{activity.body}}</p></div>{% endfor %}</article></section>''', item=item, stages=STAGES, urgencies=["urgent", "within a week", "flexible", "unspecified"], appointments=appointments, docs=docs, activities=activities, tasks=tasks, money=money)

    @app.route("/owner/calendar", methods=["GET", "POST"])
    @login_required
    def upgraded_calendar():
        if request.method == "POST":
            try:
                inquiry_id = int(request.form["inquiry_id"]); service_date = date.fromisoformat(request.form["service_date"]); start = datetime.combine(service_date, datetime.strptime(request.form["start_time"], "%H:%M").time()); end = datetime.combine(service_date, datetime.strptime(request.form["end_time"], "%H:%M").time()); status = request.form["status"]
                if not db.session.get(Inquiry, inquiry_id) or end <= start or status not in ["tentative", "confirmed", "en route", "in progress", "completed", "rescheduled", "cancelled", "no access"]: raise ValueError
                conflict = Appointment.query.filter(Appointment.start < end, Appointment.end > start, Appointment.status.notin_(["cancelled", "rescheduled"])).first()
                if conflict: raise ValueError("That time conflicts with an existing visit. Choose another time or edit the other appointment.")
                visit = Appointment(inquiry_id=inquiry_id, start=start, end=end, status=status, notes=request.form.get("notes", "")[:2000]); db.session.add(visit); db.session.add(Activity(inquiry_id=inquiry_id, kind="appointment", body="Visit scheduled for " + start.strftime("%b %-d at %-I:%M %p") + ".")); db.session.commit(); flash("Visit scheduled."); return redirect(url_for("appointment_editor", ident=visit.id))
            except (KeyError, ValueError) as error:
                flash(str(error) if str(error) else "Choose a customer, valid date, start time, and end time.")
        month_key = request.args.get("month", local_today().strftime("%Y-%m"))
        try: shown = datetime.strptime(month_key, "%Y-%m").date().replace(day=1)
        except ValueError: shown = local_today().replace(day=1)
        next_month = (shown.replace(day=28) + timedelta(days=4)).replace(day=1); previous = (shown - timedelta(days=1)).replace(day=1)
        visits = Appointment.query.filter(Appointment.start >= datetime.combine(shown, datetime.min.time()), Appointment.start < datetime.combine(next_month, datetime.min.time())).order_by(Appointment.start).all(); people = Inquiry.query.order_by(Inquiry.name).all(); names = {person.id: person.name for person in people}; events = {}
        for visit in visits: events.setdefault(visit.start.date(), []).append(visit)
        start = shown - timedelta(days=shown.weekday()); cells = [start + timedelta(days=offset) for offset in range(42)]
        return render("Calendar", '''<div class="calendar-heading"><div><p class="eyebrow">SCHEDULING</p><h1>Calendar</h1><p>Plan work, avoid overlaps, and keep every customer informed.</p></div><div class="calendar-controls"><a href="{{url_for('calendar_view',month=previous.strftime('%Y-%m'))}}" aria-label="Previous month">←</a><strong>{{shown.strftime('%B %Y')}}</strong><a href="{{url_for('calendar_view',month=next_month.strftime('%Y-%m'))}}" aria-label="Next month">→</a><a href="{{url_for('calendar_view')}}">Today</a></div></div><details class="panel schedule-panel" {{'open' if request.args.get('inquiry')}}><summary>Schedule a visit</summary><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Customer<select name="inquiry_id">{% for person in people %}<option value="{{person.id}}" {{'selected' if request.args.get('inquiry')==person.id|string}}>{{person.name}} — {{person.service}}</option>{% endfor %}</select></label><label>Service date<input type="date" name="service_date" required></label><fieldset class="time-range"><legend>Visit time</legend><label>Start<input type="time" name="start_time" required></label><span>to</span><label>End<input type="time" name="end_time" required></label></fieldset><label>Status<select name="status">{% for state in statuses %}<option>{{state}}</option>{% endfor %}</select></label><label class="span-full">Notes<textarea name="notes" placeholder="Access, scope, materials, or arrival notes"></textarea></label><button>Schedule visit</button></form></details><section class="calendar-grid">{% for day in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] %}<div class="weekday">{{day}}</div>{% endfor %}{% for day in cells %}<article class="calendar-day {{'outside-month' if day.month != shown.month}} {{'today' if day == today}}"><time>{{day.day}}</time>{% for visit in events.get(day,[]) %}<a class="calendar-event event-{{visit.status.replace(' ','-')}}" href="{{url_for('appointment_editor',ident=visit.id)}}"><span>{{visit.start.strftime('%-I:%M %p')}}</span><strong>{{names.get(visit.inquiry_id)}}</strong><em>{{visit.status}}</em></a>{% endfor %}</article>{% endfor %}</section><section class="calendar-agenda panel"><h2>{{shown.strftime('%B')}} visits</h2>{% for visit in visits %}<a class="work-row" href="{{url_for('appointment_editor',ident=visit.id)}}"><time>{{visit.start.strftime('%b %-d')}}</time><span><strong>{{visit.start.strftime('%-I:%M %p')}} · {{names.get(visit.inquiry_id)}}</strong><small>{{visit.status|title}}</small></span><b>Edit</b></a>{% else %}<p class="empty">No visits this month.</p>{% endfor %}</section>''', previous=previous, next_month=next_month, shown=shown, people=people, statuses=["tentative", "confirmed", "en route", "in progress", "completed", "rescheduled", "cancelled", "no access"], cells=cells, events=events, names=names, today=local_today())

    @app.route("/owner/calendar/appointment/<int:ident>", methods=["GET", "POST"])
    @login_required
    def appointment_editor(ident):
        visit = db.get_or_404(Appointment, ident); person = db.get_or_404(Inquiry, visit.inquiry_id)
        if request.method == "POST":
            try:
                service_date = date.fromisoformat(request.form["service_date"]); start = datetime.combine(service_date, datetime.strptime(request.form["start_time"], "%H:%M").time()); end = datetime.combine(service_date, datetime.strptime(request.form["end_time"], "%H:%M").time()); status = request.form["status"]
                if end <= start or status not in ["tentative", "confirmed", "en route", "in progress", "completed", "rescheduled", "cancelled", "no access"]: raise ValueError
                conflict = Appointment.query.filter(Appointment.id != ident, Appointment.start < end, Appointment.end > start, Appointment.status.notin_(["cancelled", "rescheduled"])).first()
                if conflict: raise ValueError("This overlaps another active visit.")
                visit.start = start; visit.end = end; visit.status = status; visit.notes = request.form.get("notes", "")[:2000]; db.session.add(Activity(inquiry_id=person.id, kind="appointment", body="Visit updated: " + status + ".")); db.session.commit(); flash("Appointment updated."); return redirect(url_for("appointment_editor", ident=ident))
            except (KeyError, ValueError) as error: flash(str(error) if str(error) else "Enter a valid visit range.")
        return render("Appointment", '''<p><a href="{{url_for('calendar_view',month=visit.start.strftime('%Y-%m'))}}">← Calendar</a></p><div class="record-heading"><div><p class="eyebrow">{{person.service}}</p><h1>{{person.name}}</h1><p>{{person.location or 'Location pending'}} · {{person.contact}}</p></div><a class="button" href="{{url_for('inquiry_detail',ident=person.id)}}">Open customer</a></div><section class="panel appointment-editor"><h2>Edit visit</h2><form method="post" class="form-grid"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Service date<input type="date" name="service_date" value="{{visit.start.date()}}" required></label><fieldset class="time-range"><legend>Visit time</legend><label>Start<input type="time" name="start_time" value="{{visit.start.strftime('%H:%M')}}" required></label><span>to</span><label>End<input type="time" name="end_time" value="{{visit.end.strftime('%H:%M')}}" required></label></fieldset><label>Status<select name="status">{% for state in statuses %}<option {{'selected' if visit.status==state}}>{{state}}</option>{% endfor %}</select></label><label class="span-full">Notes<textarea name="notes" rows="5">{{visit.notes}}</textarea></label><button>Save visit</button></form></section>''', visit=visit, person=person, statuses=["tentative", "confirmed", "en route", "in progress", "completed", "rescheduled", "cancelled", "no access"])

    @app.route("/owner/billing", methods=["GET", "POST"])
    @login_required
    def upgraded_billing():
        if request.method == "POST":
            try:
                inquiry_id = int(request.form["inquiry_id"]); kind = request.form["kind"]
                if not db.session.get(Inquiry, inquiry_id) or kind not in ["estimate", "invoice"]: raise ValueError("Choose a customer and document type.")
                lines = parse_lines(request.form); tax_rate = Decimal(request.form.get("tax_rate", "0") or "0")
                if tax_rate < 0 or tax_rate > 20: raise ValueError("Tax rate must be between 0% and 20%.")
                subtotal = sum(int((qty * unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for _, qty, unit in lines); tax = int((Decimal(subtotal) * tax_rate / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)); amount = subtotal + tax
                db.session.execute(text("BEGIN IMMEDIATE")); number = db.session.execute(text("SELECT COALESCE(MAX(id),0)+1 FROM document")).scalar_one(); doc = Document(number=("EST" if kind == "estimate" else "INV") + "-" + str(number).zfill(5), kind=kind, inquiry_id=inquiry_id, description=request.form.get("summary", "Work as quoted").strip()[:300] or "Work as quoted", amount_cents=amount, due=parsed_date(request.form.get("due")))
                db.session.add(doc); db.session.flush()
                for position, (description, qty, unit) in enumerate(lines, 1): db.session.add(DocumentLineItem(document_id=doc.id, description=description, quantity=qty, unit_cents=unit, sort_order=position))
                if tax: db.session.add(DocumentLineItem(document_id=doc.id, description="Sales tax ({:g}%)".format(tax_rate), quantity=Decimal("1"), unit_cents=tax, sort_order=99))
                db.session.add(Activity(inquiry_id=inquiry_id, kind="billing", body=kind.title() + " " + doc.number + " created.")); db.session.commit(); return redirect(url_for("document_view", ident=doc.id))
            except (KeyError, ValueError) as error: db.session.rollback(); flash(str(error) if str(error) else "Check the document details.")
        query = Document.query; kind = request.args.get("kind", ""); status = request.args.get("status", ""); search = request.args.get("q", "")
        if kind in ["estimate", "invoice"]: query = query.filter_by(kind=kind)
        if status in ["draft", "sent", "paid", "void"]: query = query.filter_by(status=status)
        if search: query = query.join(Inquiry).filter(db.or_(Document.number.ilike("%"+search+"%"), Inquiry.name.ilike("%"+search+"%")))
        page = query.order_by(Document.created.desc()).paginate(page=max(1, request.args.get("page", 1, type=int)), per_page=25, error_out=False); people = Inquiry.query.order_by(Inquiry.name).all(); names = {person.id: person.name for person in people}; open_total = sum(max(0, balance(doc)) for doc in Document.query.filter_by(kind="invoice", status="sent").all())
        return render("Billing", '''<div class="workspace-heading"><div><h1>Billing</h1><p>Build clear estimates, track invoices, and see what is outstanding.</p></div><div class="billing-summary"><strong>{{money(open_total)}}</strong><span>Outstanding</span></div></div><details class="panel document-builder" {{'open' if request.args.get('inquiry')}}><summary>Create estimate or invoice</summary><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><div class="form-grid"><label>Customer<select name="inquiry_id">{% for person in people %}<option value="{{person.id}}" {{'selected' if request.args.get('inquiry')==person.id|string}}>{{person.name}} — {{person.service}}</option>{% endfor %}</select></label><label>Document type<select name="kind"><option>estimate</option><option>invoice</option></select></label><label>Due or review date<input type="date" name="due"></label><label>Tax rate %<input type="number" min="0" max="20" step="0.01" name="tax_rate" value="0"></label><label class="span-full">Project summary<input name="summary" maxlength="300" placeholder="Example: Level 2 charger installation"></label></div><div class="line-items"><div class="line-head"><span>Description</span><span>Qty</span><span>Unit price</span></div>{% for line in range(1,5) %}<div class="line-input"><input name="line_description_{{line}}" placeholder="{{'Labor or material' if line==1 else 'Optional line item'}}" {{'required' if line==1}}><input type="number" step="0.01" min="0.01" name="line_quantity_{{line}}" value="{{'1' if line==1 else ''}}"><input inputmode="decimal" name="line_price_{{line}}" placeholder="0.00" {{'required' if line==1}}></div>{% endfor %}</div><button>Create document</button></form></details><form class="filters filter-grid"><input name="q" value="{{search}}" placeholder="Search customer or number"><select name="kind"><option value="">All types</option><option {{'selected' if kind=='estimate'}}>estimate</option><option {{'selected' if kind=='invoice'}}>invoice</option></select><select name="status"><option value="">All statuses</option>{% for state in ['draft','sent','paid','void'] %}<option {{'selected' if status==state}}>{{state}}</option>{% endfor %}</select><button>Apply</button><a href="{{url_for('billing')}}">Clear</a></form><section class="inquiry-table"><div class="inquiry-head"><span>Document</span><span>Customer</span><span>Status</span><span>Balance</span></div>{% for doc in page.items %}<a class="inquiry-row" href="{{url_for('document_view',ident=doc.id)}}"><span><strong>{{doc.number}}</strong><small>{{doc.kind|title}}</small></span><span><strong>{{names.get(doc.inquiry_id)}}</strong><small>{{doc.due.strftime('Due %b %-d') if doc.due else 'No due date'}}</small></span><span><em class="status {{doc.status}}">{{doc.status}}</em></span><span><strong>{{money(balance(doc))}}</strong><small>Total {{money(doc.amount_cents)}}</small></span></a>{% else %}<p class="empty">No documents match these filters.</p>{% endfor %}</section><nav class="pagination">{% if page.has_prev %}<a href="{{url_for('billing',page=page.prev_num,q=search,kind=kind,status=status)}}">← Previous</a>{% endif %}<span>Page {{page.page}} of {{page.pages or 1}}</span>{% if page.has_next %}<a href="{{url_for('billing',page=page.next_num,q=search,kind=kind,status=status)}}">Next →</a>{% endif %}</nav>''', people=people, page=page, names=names, money=money, balance=balance, open_total=open_total, search=search, kind=kind, status=status)

    @app.route("/owner/billing/<int:ident>", methods=["GET", "POST"])
    @login_required
    def upgraded_document_view(ident):
        doc = db.get_or_404(Document, ident); person = db.get_or_404(Inquiry, doc.inquiry_id)
        if request.method == "POST":
            action = request.form.get("action")
            if action == "status":
                status = request.form.get("status")
                if status not in ["draft", "sent", "void"] or (status == "void" and any(True for _ in Payment.query.filter_by(document_id=doc.id))): abort(400)
                doc.status = status
            elif action in ["payment", "refund"]:
                try:
                    amount = cents(request.form.get("amount", "")); method = request.form.get("method", "").strip()
                    remaining = balance(doc); paid = doc.amount_cents - remaining
                    if doc.kind != "invoice" or doc.status in ["draft", "void"] or not method or len(method) > 50 or (action == "payment" and amount > remaining) or (action == "refund" and amount > paid): raise ValueError
                    db.session.add(Payment(document_id=doc.id, amount_cents=amount, kind=action, method=method)); db.session.flush(); doc.status = "paid" if action == "payment" and amount == remaining else "sent"
                except ValueError: flash("The payment amount or method is not valid."); return redirect(url_for("document_view", ident=ident))
            elif action == "convert" and doc.kind == "estimate":
                existing = Document.query.filter_by(converted_from=doc.id).first()
                if existing: return redirect(url_for("document_view", ident=existing.id))
                number = db.session.execute(text("SELECT COALESCE(MAX(id),0)+1 FROM document")).scalar_one(); invoice = Document(number="INV-" + str(number).zfill(5), kind="invoice", inquiry_id=doc.inquiry_id, description=doc.description, amount_cents=doc.amount_cents, converted_from=doc.id, due=doc.due); db.session.add(invoice); db.session.flush()
                for line in DocumentLineItem.query.filter_by(document_id=doc.id): db.session.add(DocumentLineItem(document_id=invoice.id, description=line.description, quantity=line.quantity, unit_cents=line.unit_cents, sort_order=line.sort_order))
                db.session.commit(); return redirect(url_for("document_view", ident=invoice.id))
            else: abort(400)
            db.session.commit(); flash("Document updated."); return redirect(url_for("document_view", ident=ident))
        lines = DocumentLineItem.query.filter_by(document_id=doc.id).order_by(DocumentLineItem.sort_order).all(); payments = Payment.query.filter_by(document_id=doc.id).order_by(Payment.id.desc()).all(); remaining = balance(doc)
        return render("Document", '''<p><a href="{{url_for('billing')}}">← Billing</a></p><div class="record-heading"><div><p class="eyebrow">{{doc.kind|title}} · {{doc.number}}</p><h1>{{person.name}}</h1><p>{{doc.description}}</p></div><div class="record-actions"><a class="button" href="{{url_for('document_pdf',ident=doc.id)}}">Download PDF</a>{% if doc.kind=='estimate' %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="convert"><button class="primary-action">Convert to invoice</button></form>{% endif %}</div></div><section class="document-layout"><article class="panel"><div class="document-state"><em class="status {{doc.status}}">{{doc.status}}</em><span>{{'Balance due' if doc.kind=='invoice' else 'Estimate total'}} <strong>{{money(remaining if doc.kind=='invoice' else doc.amount_cents)}}</strong></span></div><div class="line-summary">{% if lines %}{% for line in lines %}<div><span>{{line.description}}<small>{{line.quantity}} × {{money(line.unit_cents)}}</small></span><strong>{{money(line_total(line))}}</strong></div>{% endfor %}{% else %}<div><span>{{doc.description}}</span><strong>{{money(doc.amount_cents)}}</strong></div>{% endif %}<div class="grand-total"><span>Total</span><strong>{{money(doc.amount_cents)}}</strong></div></div>{% if doc.due %}<p class="due-line">Due or review date: {{doc.due.strftime('%B %-d, %Y')}}</p>{% endif %}</article><article class="panel"><h2>Document controls</h2><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="status"><label>Delivery status<select name="status"><option {{'selected' if doc.status=='draft'}}>draft</option><option {{'selected' if doc.status in ['sent','paid']}}>sent</option><option>void</option></select></label><button>Save status</button></form>{% if doc.kind=='invoice' %}<hr><h2>Record payment</h2><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Action<select name="action"><option>payment</option><option>refund</option></select></label><label>Amount<input name="amount" inputmode="decimal" required></label><label>Method<input name="method" placeholder="Card, check, cash…" required></label><button>Record</button></form>{% for payment in payments %}<div class="payment-row"><span>{{payment.kind|title}} · {{payment.method}}</span><strong>{{money(payment.amount_cents)}}</strong></div>{% endfor %}{% endif %}</article></section>''', doc=doc, person=person, lines=lines, payments=payments, remaining=remaining, money=money, line_total=line_total)

    @app.get("/owner/billing/<int:ident>/pdf")
    @login_required
    def upgraded_document_pdf(ident):
        doc = db.get_or_404(Document, ident); person = db.get_or_404(Inquiry, doc.inquiry_id); lines = DocumentLineItem.query.filter_by(document_id=doc.id).order_by(DocumentLineItem.sort_order).all(); buffer = BytesIO(); pdf = canvas.Canvas(buffer, pagesize=letter); width, height = letter
        pdf.setFillColor("#17120e"); pdf.rect(0, height-112, width, 112, fill=1, stroke=0); pdf.setFillColor("#e4c182"); pdf.setFont("Helvetica-Bold", 22); pdf.drawString(48, height-58, "SURGE POWER LLC"); pdf.setFillColor("white"); pdf.setFont("Helvetica", 10); pdf.drawString(48, height-78, "Electrical work for the Phoenix metro")
        y = height-148; pdf.setFillColor("#17120e"); pdf.setFont("Helvetica-Bold", 18); pdf.drawString(48, y, doc.kind.title().upper() + " " + doc.number); y -= 28; pdf.setFont("Helvetica", 11)
        for entry in ["Customer: " + person.name, "Contact: " + person.contact, "Project: " + doc.description, "Date: " + doc.created.strftime("%B %-d, %Y"), "Due: " + (doc.due.strftime("%B %-d, %Y") if doc.due else "Not specified")]: pdf.drawString(48, y, entry[:110]); y -= 18
        y -= 18; pdf.setFont("Helvetica-Bold", 10); pdf.drawString(48, y, "DESCRIPTION"); pdf.drawRightString(550, y, "TOTAL"); y -= 12; pdf.line(48, y, 550, y); y -= 20; pdf.setFont("Helvetica", 10)
        display_lines = lines or [type("LegacyLine", (), {"description": doc.description, "quantity": 1, "unit_cents": doc.amount_cents})()]
        for line in display_lines:
            for index, part in enumerate(wrap(line.description, width=68)):
                if y < 88: pdf.showPage(); y = height-60
                pdf.drawString(48, y, part); 
                if index == 0: pdf.drawRightString(550, y, money(line_total(line)))
                y -= 14
            pdf.setFillColor("#70665d"); pdf.drawString(48, y, "{} × {}".format(line.quantity, money(line.unit_cents))); pdf.setFillColor("#17120e"); y -= 22
        pdf.line(355, y, 550, y); y -= 20; pdf.setFont("Helvetica-Bold", 13); pdf.drawRightString(550, y, "Total " + money(doc.amount_cents)); pdf.setFont("Helvetica", 9); pdf.setFillColor("#70665d"); pdf.drawString(48, 48, "Thank you for considering Surge Power LLC."); pdf.save(); buffer.seek(0)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=doc.number + ".pdf")

    def upgraded_public_home():
        from app import page
        token = generate_csrf()
        markup = '''<header><a class="brand" href="#top" aria-label="Surge Power home"><img src="/static/surge-power-logo.png" alt="Surge Power LLC"></a><nav class="desktop-nav" aria-label="Main navigation"><a href="#services">Services</a><a href="#proof">Our work</a><a href="#process">How it works</a><a href="#contact">Contact</a></nav><a class="btn" href="#contact">Request a quote ↗</a></header><main id="top"><section class="hero"><div class="hero-copy"><p class="eyebrow">EAST VALLEY · PHOENIX METRO</p><h1>EV charging,<br>powered right.</h1><p class="lead">Surge Power installs EV chargers and handles the electrical work that keeps homes and businesses ready for what’s next.</p><div class="hero-actions"><a class="btn" href="#contact">Request an installation quote ↗</a><a class="text-link" href="#services">Explore services</a></div><ul class="trust-list"><li>East Valley based</li><li>Phoenix metro service</li><li>Residential & commercial</li></ul></div><div class="charge-scene" role="img" aria-label="Illustration of an EV charging station"><div class="cable"></div><div class="charger"></div><div class="scene-caption">A better way to power your day<span>EV charging · General electrical work</span></div></div></section><section class="section service-intro" id="services"><p class="eyebrow">WHAT WE DO</p><h2>Electrical work with a clear next step.</h2><div class="grid"><article class="card"><b>01 / EV CHARGING</b><h3>EV charger installation</h3><p>Home and business charger installation planned around your vehicle, parking setup, panel capacity, and daily routine.</p><a href="#contact">Request an EV quote →</a></article><article class="card"><b>02 / ELECTRICAL</b><h3>General electrical work</h3><p>New circuits, electrical updates, and project guidance for the places you live and work.</p><a href="#contact">Talk through your project →</a></article><article class="card"><b>03 / PLANNING</b><h3>Project guidance</h3><p>Bring the details you have. We’ll help identify the practical next step before work begins.</p><a href="#contact">Start the conversation →</a></article></div></section><section class="proof-band" id="proof"><p class="eyebrow">BUILT FOR THE WAY YOU LIVE</p><h2>From the driveway to the workspace.</h2><div class="proof-grid"><div><strong>EV-ready homes</strong><span>Charging access that fits your routine.</span></div><div><strong>Thoughtful upgrades</strong><span>Clear scope before electrical work begins.</span></div><div><strong>Phoenix metro reach</strong><span>East Valley roots, service throughout the Valley.</span></div></div></section><section class="section dark" id="process"><p class="eyebrow">A STRAIGHTFORWARD PROCESS</p><h2>From first message to powered-up.</h2><div class="grid process-grid"><article class="card"><b>01</b><h3>Share the project</h3><p>Tell us where you are, what you need, and how to reach you.</p></article><article class="card"><b>02</b><h3>Talk through the details</h3><p>We’ll discuss the location, scope, and next step for the work.</p></article><article class="card"><b>03</b><h3>Move forward clearly</h3><p>You’ll have a clear path for scheduling and the work ahead.</p></article></div></section><section class="section service-area"><p class="eyebrow">WHERE WE WORK</p><h2>East Valley based.<br>Phoenix connected.</h2><p>Surge Power LLC serves homeowners and businesses throughout the Phoenix metro area.</p></section><section class="section contact" id="contact"><div><p class="eyebrow">LET’S GET TO WORK</p><h2>Tell us what you’re powering.</h2><p>Send a few details and a contact method. We’ll use your request to plan the next conversation.</p><p class="contact-note">Prefer Instagram? <a href="https://www.instagram.com/theazevguy/">Find Surge Power there ↗</a></p></div><form method="post" action="/inquiry"><input type="hidden" name="csrf_token" value="'''+token+'''"><label>Name<input name="name" maxlength="100" autocomplete="name" required></label><label>Phone or email<input name="contact" maxlength="200" autocomplete="tel" required></label><label>What can we help with?<select name="service"><option>EV charger installation</option><option>General electrical work</option><option>Other project</option></select></label><label>City or area<input name="location" maxlength="100" autocomplete="address-level2"></label><label>Project details<textarea name="details" rows="4" maxlength="3000" placeholder="Tell us about the location, project, or charger you have in mind."></textarea></label><button>Send request ↗</button><small>We’ll use these details only to respond to your request.</small></form></section></main><footer><div><strong>SURGE POWER LLC</strong><p>EV charger installation and electrical work for the Phoenix metro.</p></div><div><a href="/privacy">Privacy</a><a href="https://www.instagram.com/theazevguy/">Instagram ↗</a></div></footer>'''
        return page(markup)

    app.view_functions["inquiries"] = upgraded_inquiries
    app.view_functions["inquiry_detail"] = upgraded_inquiry_detail
    app.view_functions["calendar_view"] = upgraded_calendar
    app.view_functions["billing"] = upgraded_billing
    app.view_functions["document_view"] = upgraded_document_view
    app.view_functions["document_pdf"] = upgraded_document_pdf
    app.view_functions["home"] = upgraded_public_home
