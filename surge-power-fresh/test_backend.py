import pytest
from backend import create_app, db, User, Inquiry, Document, Payment, ph, local_secret
from workspace_upgrade import install_workspace_upgrade
from workspace_phase_two import install_phase_two, AccountAccess, InquiryArchive, InquiryAssignment

@pytest.fixture
def client(tmp_path):
    app=create_app({'TESTING':True,'SECRET_KEY':'test-secret','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'test.db'),'WTF_CSRF_ENABLED':False})
    install_workspace_upgrade(app)
    install_phase_two(app)
    with app.app_context():
        db.create_all(); owner=User(email='owner@example.invalid',password_hash=ph.hash('test-password-123')); db.session.add(owner); db.session.flush(); db.session.add(AccountAccess(user_id=owner.id,role='owner',active=True)); db.session.commit()
        yield app.test_client()
        db.session.remove(); db.drop_all()

def sign_in(client):
    return client.post('/owner/login',data={'email':'owner@example.invalid','password':'test-password-123'})

def inquiry(client):
    return client.post('/inquiry',data={'name':'Demo','contact':'demo@example.invalid','service':'EV charger installation','location':'Mesa','details':'Example','consent':'yes','preferred_contact':'email','best_time':'morning','property_type':'home'},follow_redirects=True)

def test_public_and_private_crm(client):
    assert client.get('/').status_code==200
    assert client.get('/owner/inquiries').status_code==302
    assert inquiry(client).status_code==200
    assert b'Check the required fields' in client.post('/inquiry',data={'name':'bad'},follow_redirects=True).data
    assert sign_in(client).status_code==302
    assert b'Demo' in client.get('/owner/inquiries?q=Demo').data
    assert client.post('/owner/inquiries/1',data={'action':'activity','kind':'call','body':'Called'}).status_code==302
    assert db.session.get(Inquiry,1).stage=='contacted'
    assert b'Called' in client.get('/owner/inquiries/1').data

def test_calendar_conflict(client):
    inquiry(client); sign_in(client)
    data={'inquiry_id':'1','service_date':'2026-12-01','start_time':'09:00','end_time':'10:00','status':'confirmed'}
    assert client.post('/owner/calendar',data=data).status_code==302
    assert b'This overlaps an active visit.' in client.post('/owner/calendar',data=data,follow_redirects=True).data
    page=client.get('/owner/calendar?month=2026-12')
    assert page.status_code==200
    assert b'December 2026' in page.data
    assert b'calendar-grid' in page.data

def test_invalid_calendar_input_returns_helpful_message(client):
    inquiry(client); sign_in(client)
    response=client.post('/owner/calendar?inquiry=1',data={'inquiry_id':'1','service_date':'2026-12-01','start_time':'11:00','end_time':'09:00','status':'confirmed','month':'2026-12'},follow_redirects=True)
    assert response.status_code==200
    assert b'End time must be after the start time.' in response.data

def test_calendar_accepts_one_date_and_two_times(client):
    inquiry(client); sign_in(client)
    response=client.post('/owner/calendar',data={'inquiry_id':'1','service_date':'2026-12-04','start_time':'09:00','end_time':'10:30','status':'confirmed'})
    assert response.status_code == 302

def test_invoice_limits_conversion_pdf_and_csv(client):
    inquiry(client); sign_in(client)
    assert client.post('/owner/billing',data={'inquiry_id':'1','kind':'estimate','summary':'Charger','line_description_1':'Installation','line_quantity_1':'1','line_price_1':'100.00'}).status_code==302
    assert client.post('/owner/billing/1',data={'action':'convert'}).status_code==302
    assert client.post('/owner/billing/1',data={'action':'convert'}).status_code==302
    assert Document.query.count()==2
    assert client.post('/owner/billing/2',data={'action':'meta','delivery_status':'sent','approval_status':'not_applicable'}).status_code==302
    client.post('/owner/billing/2',data={'action':'payment','amount':'120','method':'cash'})
    assert Payment.query.count()==0
    client.post('/owner/billing/2',data={'action':'payment','amount':'100','method':'cash'})
    assert Payment.query.count()==1
    assert client.post('/owner/billing/2',data={'action':'meta','delivery_status':'sent','approval_status':'not_applicable'}).status_code==302
    assert client.get('/owner/billing/2/pdf').data.startswith(b'%PDF')
    assert b'Demo' in client.get('/owner/export.csv').data

def test_public_metadata_and_private_headers(client):
    homepage=client.get('/')
    assert b'<title>Surge Power LLC | EV Charger Installation &amp; Electrical Work</title>' in homepage.data
    assert b'<meta property="og:title"' in homepage.data
    assert b'<link rel="stylesheet" href="/static/refresh.css' in homepage.data
    assert b'<style>' not in homepage.data
    assert client.get('/privacy').status_code == 200
    assert b'Disallow: /owner/' in client.get('/robots.txt').data
    assert client.get('/sitemap.xml').status_code == 200
    sign_in(client)
    response=client.get('/owner/inquiries')
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert response.headers['Cache-Control'] == 'no-store'

def test_inquiry_pagination_preserves_filter(client):
    for n in range(30):
        db.session.add(Inquiry(name=f'Example {n}',contact='demo@example.invalid',service='EV charger installation',stage='new'))
    db.session.commit(); sign_in(client)
    first=client.get('/owner/inquiries?stage=new')
    assert b'Next' in first.data and b'Page 1 of 2' in first.data
    second=client.get('/owner/inquiries?stage=new&page=2')
    assert b'Previous' in second.data and b'Page 2 of 2' in second.data

def test_login_throttles_repeated_failures(client):
    for _ in range(10):
        assert client.post('/owner/login',data={'email':'missing@example.invalid','password':'bad'},environ_base={'REMOTE_ADDR':'192.0.2.44'}).status_code == 200
    assert client.post('/owner/login',data={'email':'missing@example.invalid','password':'bad'},environ_base={'REMOTE_ADDR':'192.0.2.44'}).status_code == 429

def test_public_intake_persists_preferences_and_customer_job(client):
    response=inquiry(client)
    assert b'Request #1 is in' in response.data
    from workspace_phase_two import InquiryIntake, Customer, Job
    intake=InquiryIntake.query.filter_by(inquiry_id=1).one()
    assert (intake.preferred_contact,intake.best_time,intake.property_type)==('email','morning','home')
    assert Customer.query.count()==1 and Job.query.filter_by(inquiry_id=1,source='website').count()==1
    client.post('/owner/logout')
    rejected=client.post('/inquiry',data={'name':'No consent','contact':'no@example.invalid','service':'EV charger installation'},follow_redirects=True)
    assert b'confirm how we may use your details' in rejected.data
    assert Inquiry.query.count()==1

def test_assignment_archive_restore_and_unassigned_queue(client):
    inquiry(client); sign_in(client)
    owner=User.query.filter_by(email='owner@example.invalid').one()
    detail=client.get('/owner/inquiries/1')
    assert b'Assigned owner' in detail.data and b'Call customer' not in detail.data
    response=client.post('/owner/inquiries/1',data={'action':'update','name':'Demo','contact':'demo@example.invalid','service':'EV charger installation','job_title':'Charger','address':'Mesa','job_status':'lead','stage':'new','urgency':'flexible','assigned_to':str(owner.id)})
    assert response.status_code==302
    assert db.session.get(InquiryAssignment,1).user_id==owner.id
    client.post('/owner/inquiries/1',data={'action':'archive'})
    assert db.session.get(InquiryArchive,1) is not None
    assert b'Demo' not in client.get('/owner/inquiries').data
    client.post('/owner/archive',data={'inquiry_id':'1'})
    assert db.session.get(InquiryArchive,1) is None
    assert b'Demo' in client.get('/owner/inquiries?assigned='+str(owner.id)).data

def test_billing_filters_and_summary_render(client):
    inquiry(client); sign_in(client)
    client.post('/owner/billing',data={'inquiry_id':'1','kind':'invoice','summary':'Panel work','line_description_1':'Labor','line_quantity_1':'2','line_price_1':'125.00','tax_rate':'8.1','due':'2026-11-09'})
    page=client.get('/owner/billing?kind=invoice&sort=balance')
    assert page.status_code==200
    assert b'overdue' in page.data and b'Largest balance' in page.data
    assert Document.query.one().amount_cents==27025
    overdue=client.get('/owner/billing?kind=invoice&due=overdue')
    assert overdue.status_code==200 and b'INV-' in overdue.data and b'$270.25' in overdue.data

def test_staff_and_manager_permissions_match_navigation(client):
    manager=User(email='manager@example.invalid',password_hash=ph.hash('manager-password-123'))
    staff=User(email='staff@example.invalid',password_hash=ph.hash('staff-password-123'))
    db.session.add_all([manager,staff]); db.session.flush()
    db.session.add_all([AccountAccess(user_id=manager.id,role='manager',active=True),AccountAccess(user_id=staff.id,role='staff',active=True)]); db.session.commit()
    sign_in(client); client.post('/owner/logout')
    assert client.post('/owner/login',data={'email':'staff@example.invalid','password':'staff-password-123'}).status_code==302
    page=client.get('/owner/inquiries')
    assert b'Billing' not in page.data and b'Export this view' not in page.data
    assert client.get('/owner/billing').status_code==403
    assert client.get('/owner/audit').status_code==403
    client.post('/owner/logout')
    assert client.post('/owner/login',data={'email':'manager@example.invalid','password':'manager-password-123'}).status_code==302
    page=client.get('/owner/audit')
    assert page.status_code==200 and b'Business settings' not in page.data
    assert client.get('/owner/billing').status_code==200
    assert client.get('/owner/settings').status_code==403

def test_production_requires_persistent_secret_and_disables_auto_schema(monkeypatch,tmp_path):
    monkeypatch.setenv('SURGE_ENV','production')
    monkeypatch.delenv('SURGE_SECRET',raising=False)
    with pytest.raises(RuntimeError,match='at least 32 characters'):
        create_app({'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'prod.db')})
    monkeypatch.setenv('SURGE_SECRET','x'*48)
    app=create_app({'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'prod.db')})
    assert app.config['AUTO_CREATE_SCHEMA'] is False
    assert app.config['SESSION_COOKIE_SECURE'] is True

def test_local_session_key_has_private_permissions(tmp_path):
    import stat
    secret=local_secret(tmp_path/'instance')
    assert len(secret)>=64
    assert stat.S_IMODE((tmp_path/'instance'/'surge-session.key').stat().st_mode)==0o600
    assert stat.S_IMODE((tmp_path/'instance').stat().st_mode)==0o700
