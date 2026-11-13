"""Create 30 labeled, idempotent sample records for the owner workspace.

All data uses .invalid contacts and is safe to identify and remove later.
"""
from datetime import date, datetime, timedelta

from backend import Activity, Appointment, Document, Inquiry, Payment, app, db

NAMES = [
    "Alex Morgan", "Casey Rivera", "Riley Chen", "Morgan Patel", "Jamie Brooks",
    "Cameron Lewis", "Drew Foster", "Jordan Kim", "Parker Reed", "Avery Stone",
    "Taylor Davis", "Rowan Ellis", "Skyler Grant", "Quinn Harper", "Emerson Cole",
    "Blake Santos", "Reese Warren", "Finley Ortiz", "Hayden Price", "Sage Bennett",
    "Dakota Ross", "Marley King", "Kendall Flores", "Micah Young", "Logan Shaw",
    "Sydney Bell", "Charlie West", "Ari Howard", "Robin Baker", "Devon Gray",
]
STAGES = [
    "new", "new", "new", "new", "new",
    "contacted", "contacted", "contacted", "contacted", "contacted",
    "qualified", "qualified", "qualified", "qualified", "qualified",
    "quote sent", "quote sent", "quote sent", "quote sent",
    "won", "won", "won", "lost", "lost", "closed", "closed", "closed", "new", "qualified", "contacted",
]
SERVICES = ["EV charger installation", "General electrical work", "Other project"]
AREAS = ["Mesa", "Chandler", "Tempe", "Gilbert", "Scottsdale", "Phoenix", "Queen Creek", "Apache Junction"]
URGENCY = ["urgent", "within a week", "flexible", "unspecified"]

def document_number(kind, position):
    return ("EST" if kind == "estimate" else "INV") + "-DEMO-" + str(position).zfill(3)

with app.app_context():
    created = 0
    appointments = 0
    documents = 0
    today = date.today()
    for position, (name, stage) in enumerate(zip(NAMES, STAGES), start=1):
        contact = "demo-%02d@surgeworkspace.invalid" % position
        inquiry = Inquiry.query.filter_by(contact=contact).first()
        if not inquiry:
            service = SERVICES[(position - 1) % len(SERVICES)]
            inquiry = Inquiry(
                name="DEMO — " + name,
                contact=contact,
                service=service,
                location=AREAS[(position - 1) % len(AREAS)],
                details="Demo workspace request %02d: planning support for %s." % (position, service.lower()),
                stage=stage,
                urgency=URGENCY[(position - 1) % len(URGENCY)],
                followup=today + timedelta(days=(position % 9) - 3) if stage not in ("lost", "closed") else None,
                created=datetime.now() - timedelta(days=position * 2),
            )
            db.session.add(inquiry)
            db.session.flush()
            created += 1
        if not Activity.query.filter_by(inquiry_id=inquiry.id).first():
            db.session.add(Activity(inquiry_id=inquiry.id, kind="note", body="Demo: intake details reviewed."))
            if stage not in ("new",):
                db.session.add(Activity(inquiry_id=inquiry.id, kind="call", body="Demo: discussed scope and next steps."))
            if stage in ("quote sent", "won", "lost", "closed"):
                db.session.add(Activity(inquiry_id=inquiry.id, kind="email", body="Demo: project summary sent for review."))
        if position <= 14 and not Appointment.query.filter_by(inquiry_id=inquiry.id).first():
            start = datetime.combine(today + timedelta(days=position - 5), datetime.min.time()) + timedelta(hours=8 + (position % 3) * 2)
            status = ["tentative", "confirmed", "en route", "in progress", "completed", "rescheduled", "cancelled"][position % 7]
            db.session.add(Appointment(
                inquiry_id=inquiry.id,
                start=start,
                end=start + timedelta(hours=1, minutes=30),
                status=status,
                notes="Demo visit %02d — sample scheduling note." % position,
            ))
            appointments += 1
        if position in (16, 17, 18, 20, 21, 22) and not Document.query.filter_by(inquiry_id=inquiry.id).first():
            kind = "estimate" if position in (16, 17, 18) else "invoice"
            amount = [125000, 187500, 95000, 220000, 145000, 78000][(16, 17, 18, 20, 21, 22).index(position)]
            status = "sent" if kind == "estimate" else ("paid" if position == 21 else "sent")
            doc = Document(
                number=document_number(kind, position),
                kind=kind,
                inquiry_id=inquiry.id,
                description="Demo %s for %s" % (kind, inquiry.service.lower()),
                amount_cents=amount,
                status=status,
                due=today + timedelta(days=14),
            )
            db.session.add(doc)
            db.session.flush()
            if position == 21:
                db.session.add(Payment(document_id=doc.id, amount_cents=amount, kind="payment", method="demo payment"))
            documents += 1
    db.session.commit()
    print("Added %d inquiries, %d appointments, and %d billing documents." % (created, appointments, documents))
