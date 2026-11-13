"""Operational tools with audited, owner-controlled changes."""
import json
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import os
import re
import click

from flask import abort, flash, redirect, request, send_file
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf
from backend import db, Inquiry, Activity, Appointment, Document, User, STAGES, render, utc_now, cents
from workspace_phase_two import Customer, Job, AuditEvent, InquiryAssignment, InquiryArchive, account_role, audit, normalize_contact


class ServicePreset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    unit_cents = db.Column(db.Integer, nullable=False)


class BulkChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    changes = db.Column(db.Text, nullable=False)
    undone = db.Column(db.Boolean, nullable=False, default=False)


def install(app):
    if app.config.get('AUTO_CREATE_SCHEMA'):
        with app.app_context():
            db.create_all()

    def manager():
        if account_role() not in ('owner', 'manager'):
            abort(403)

    @app.cli.command('process-reminders')
    @click.option('--send', is_flag=True, help='Send due reminders through configured SMTP; otherwise preview counts only.')
    def process_reminders(send):
        """Run daily from the host scheduler. No customer data printed."""
        from datetime import timedelta
        from backend import balance, local_today
        from workspace_phase_two import MessageLog, send_message
        today = local_today(); queued = []
        for visit in Appointment.query.filter(Appointment.status.in_(['tentative', 'confirmed']), Appointment.start >= datetime.combine(today + timedelta(days=1), datetime.min.time()), Appointment.start < datetime.combine(today + timedelta(days=2), datetime.min.time())).all():
            person = db.session.get(Inquiry, visit.inquiry_id)
            queued.append((person, 'Visit reminder #' + str(visit.id) + ' ' + visit.start.isoformat(), 'Your Surge Power visit is scheduled for ' + visit.start.strftime('%b %d, %Y at %I:%M %p') + ' (' + os.environ.get('SURGE_TIMEZONE', 'America/Phoenix') + '). Contact us if you need to change the visit.'))
        for doc in Document.query.filter(Document.kind == 'invoice', Document.status == 'sent', Document.due < today).all():
            if balance(doc) > 0:
                person = db.session.get(Inquiry, doc.inquiry_id)
                queued.append((person, 'Invoice reminder ' + doc.number + ' ' + today.strftime('%Y-%W'), 'Invoice ' + doc.number + ' has an outstanding balance of $' + format(balance(doc)/100, '.2f') + '. Contact Surge Power with any questions.'))
        eligible = [(p, s, b) for p, s, b in queued if '@' in p.contact and not MessageLog.query.filter_by(inquiry_id=p.id, subject=s, status='sent').first()]
        if not send:
            click.echo(str(len(eligible)) + ' reminders eligible. No messages sent.'); return
        if not os.environ.get('SURGE_SMTP_HOST') or not os.environ.get('SURGE_SMTP_FROM'):
            raise click.ClickException('Configure SMTP before enabling reminder sends.')
        sent = failed = 0
        for person, subject, body in eligible:
            record = MessageLog(inquiry_id=person.id, channel='email', recipient=person.contact, subject=subject, body=body)
            try:
                send_message(record); sent += 1
            except Exception:
                record.status = 'failed'; failed += 1
            db.session.add(record); db.session.commit()
        click.echo(f'{sent} sent; {failed} failed. Review message history for delivery results.')

    @app.route('/owner/tools', methods=['GET', 'POST'])
    @login_required
    def operations_tools():
        manager()
        if request.method == 'POST':
            try:
                action = request.form.get('action')
                if action == 'preset':
                    name = request.form.get('name', '').strip()
                    description = request.form.get('description', '').strip()
                    if not name or len(name) > 120 or not description or len(description) > 300:
                        raise ValueError('Enter a name and description within the field limits.')
                    preset = ServicePreset(name=name, description=description, unit_cents=cents(request.form.get('price', '')))
                    db.session.add(preset)
                    audit('create', 'preset', 0, 'Service preset created: ' + name)
                elif action == 'bulk':
                    ids = request.form.getlist('inquiry_id')
                    stage = request.form.get('stage')
                    if not ids or len(ids) > 100 or stage not in STAGES or any(not x.isdigit() for x in ids):
                        raise ValueError('Select up to 100 inquiries and a valid stage.')
                    items = Inquiry.query.filter(Inquiry.id.in_([int(x) for x in ids])).all()
                    changes = []
                    for item in items:
                        changes.append({'id': item.id, 'before': item.stage, 'after': stage})
                        item.stage = stage
                        db.session.add(Activity(inquiry_id=item.id, kind='update', body='Bulk stage changed to ' + stage))
                        audit('bulk-stage', 'inquiry', item.id, 'Stage changed to ' + stage)
                    db.session.add(BulkChange(actor_id=current_user.id, changes=json.dumps(changes)))
                elif action == 'undo':
                    batch = db.get_or_404(BulkChange, int(request.form.get('batch_id', '0')))
                    if batch.undone:
                        raise ValueError('This batch has already been undone.')
                    changes = json.loads(batch.changes)
                    items = {x['id']: db.session.get(Inquiry, x['id']) for x in changes}
                    if any(not items[x['id']] or items[x['id']].stage != x['after'] for x in changes):
                        raise ValueError('A record changed after this batch. Review it individually; undo would overwrite newer work.')
                    for change in changes:
                        items[change['id']].stage = change['before']
                        audit('undo-stage', 'inquiry', change['id'], 'Bulk stage change reversed.')
                        db.session.add(Activity(inquiry_id=change['id'], kind='update', body='Bulk stage change reversed to ' + change['before']))
                    batch.undone = True
                elif action == 'merge':
                    source_id = int(request.form.get('source', '0')); target_id = int(request.form.get('target', '0'))
                    source = db.get_or_404(Customer, source_id); target = db.get_or_404(Customer, target_id)
                    if source.id == target.id or normalize_contact(source.contact) != normalize_contact(target.contact):
                        raise ValueError('Merge requires two different customers with the same normalized contact.')
                    # Reassign jobs; retain the source customer as a recoverable record.
                    jobs = Job.query.filter_by(customer_id=source.id).all()
                    if not jobs:
                        raise ValueError('This customer has no jobs to merge.')
                    for job in jobs:
                        job.customer_id = target.id
                    audit('merge', 'customer', target.id, 'Moved jobs ' + ','.join(str(j.id) for j in jobs) + ' from customer #' + str(source.id) + '; source record retained.')
                else:
                    abort(400)
                db.session.commit(); flash('Saved.')
            except (ValueError, TypeError) as error:
                db.session.rollback(); flash(str(error))
            return redirect('/owner/tools')
        groups = defaultdict(list)
        for customer in Customer.query.order_by(Customer.name).all():
            key = normalize_contact(customer.contact)
            if key and Job.query.filter_by(customer_id=customer.id).first():
                groups[key].append(customer)
        return render('Operations', '''<h1>Operations tools</h1>
        <section class="panel"><h2>Service presets</h2><p>Owner-approved pricing for reuse in estimates. Prices are never published automatically.</p>
        <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="preset">
        <label>Name<input name="name" required maxlength="120"></label><label>Description<input name="description" required maxlength="300"></label><label>Unit price ($)<input name="price" type="number" min="0.01" step="0.01" required></label><button>Save preset</button></form>
        {% for p in presets %}<p><strong>{{p.name}}</strong> · ${{'%.2f'|format(p.unit_cents/100)}}<br>{{p.description}}<br><a href="/owner/billing?preset={{p.id}}">Use in estimate</a></p>{% endfor %}</section>
        <section class="panel"><h2>Bulk stage update</h2><p>Choose records deliberately. The most recent batches can be undone if no newer stage edits have occurred.</p>
        <form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="bulk">
        <label>New stage<select name="stage">{% for s in stages %}<option>{{s}}</option>{% endfor %}</select></label>
        <label>Inquiries (select multiple)<select name="inquiry_id" multiple size="10" required>{% for i in inquiries %}<option value="{{i.id}}">#{{i.id}} {{i.name}} · {{i.stage}}</option>{% endfor %}</select></label><button>Update selected inquiries</button></form>
        {% for b in batches %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="undo"><input type="hidden" name="batch_id" value="{{b.id}}"><button>Undo batch #{{b.id}}</button></form>{% endfor %}</section>
        <section class="panel"><h2>Possible duplicate customers</h2><p>Only matching contact details are suggested. Merge moves jobs to the selected customer and retains the source record.</p>
        {% for group in duplicates %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="merge"><label>Move jobs from<select name="source">{% for c in group %}<option value="{{c.id}}">#{{c.id}} {{c.name}} · {{c.contact}}</option>{% endfor %}</select></label><label>Keep customer<select name="target">{% for c in group %}<option value="{{c.id}}">#{{c.id}} {{c.name}}</option>{% endfor %}</select></label><button>Merge customer jobs</button></form>{% else %}<p>No matching-contact duplicates found.</p>{% endfor %}</section>''',
            presets=ServicePreset.query.order_by(ServicePreset.name).all(), stages=STAGES,
            inquiries=Inquiry.query.order_by(Inquiry.name).limit(500).all(),
            batches=BulkChange.query.filter_by(undone=False).order_by(BulkChange.id.desc()).limit(10).all(),
            duplicates=[group for group in groups.values() if len(group) > 1])

    @app.get('/owner/calendar/export.ics')
    @login_required
    def calendar_export():
        def escaped(value):
            return str(value or '').replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '').replace(',', '\\,').replace(';', '\\;')
        def timestamp(value):
            return value.replace(tzinfo=ZoneInfo(os.environ.get('SURGE_TIMEZONE', 'America/Phoenix'))).astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Surge Power//Calendar//EN']
        for visit in Appointment.query.filter(Appointment.status.notin_(['cancelled', 'rescheduled'])).order_by(Appointment.start).all():
            inquiry = db.session.get(Inquiry, visit.inquiry_id)
            lines += ['BEGIN:VEVENT', 'UID:surge-visit-' + str(visit.id) + '@surge-power', 'DTSTAMP:' + utc_now().strftime('%Y%m%dT%H%M%SZ'), 'DTSTART:' + timestamp(visit.start), 'DTEND:' + timestamp(visit.end), 'SUMMARY:' + escaped(inquiry.name + ' — ' + inquiry.service), 'LOCATION:' + escaped(inquiry.location), 'END:VEVENT']
        lines.append('END:VCALENDAR')
        # Fold long UTF-8 lines to the iCalendar byte limit.
        folded = []
        for line in lines:
            current = ''
            for char in line:
                if len((current + char).encode()) > 73:
                    folded.append(current); current = ' '
                current += char
            folded.append(current)
        audit('export', 'calendar', 0, 'Calendar file downloaded.'); db.session.commit()
        return send_file(BytesIO(('\r\n'.join(folded) + '\r\n').encode()), mimetype='text/calendar', as_attachment=True, download_name='surge-visits.ics', max_age=0)

    @app.after_request
    def operation_links(response):
        if response.mimetype != 'text/html' or response.status_code != 200:
            return response
        html = response.get_data(as_text=True)
        if current_user.is_authenticated and request.path.startswith('/owner/'):
            if account_role() in ('owner', 'manager'):
                html = html.replace('</nav>', '<a href="/owner/tools">Operations tools</a></nav>', 1)
            if request.path == '/owner/calendar':
                html = html.replace('<h1>Calendar</h1>', '<h1>Calendar</h1><p><a href="/owner/calendar/export.ics">Download calendar for Google / Outlook</a></p>')
            if request.path == '/owner/billing' and request.args.get('preset', '').isdigit():
                preset = db.session.get(ServicePreset, int(request.args['preset']))
                if preset:
                    from markupsafe import escape
                    for field, value in [('line_description_1', str(escape(preset.description))), ('line_quantity_1', '1'), ('line_price_1', format(preset.unit_cents / 100, '.2f'))]:
                        html = re.sub(r'(name="' + field + r'"\s+value=")[^"]*', lambda match: match[1] + value, html)
        response.set_data(html)
        return response
