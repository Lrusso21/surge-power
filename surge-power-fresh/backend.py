"""Flask owner workspace and public inquiry backend."""
import csv, io, os, secrets, time, hmac, hashlib, sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from flask import Flask, abort, flash, redirect, render_template_string, request, send_file, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from reportlab.pdfgen import canvas
from sqlalchemy import event, text, func
from sqlalchemy.engine import Engine

db=SQLAlchemy(); login=LoginManager(); csrf=CSRFProtect(); migrate=Migrate(); ph=PasswordHasher()
STAGES=['new','contacted','qualified','quote sent','won','lost','closed']
SERVICES=['EV charger installation','General electrical work','Other project']

def utc_now():
    """Return a naive UTC datetime for the existing SQLAlchemy DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

@event.listens_for(Engine, 'connect')
def sqlite_foreign_keys(connection, record):
    if connection.__class__.__module__.startswith('sqlite3'):
        connection.execute('PRAGMA foreign_keys=ON')

class User(UserMixin, db.Model):
    id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(254),unique=True,nullable=False); password_hash=db.Column(db.String(255),nullable=False)
class Inquiry(db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(100),nullable=False); contact=db.Column(db.String(200),nullable=False); service=db.Column(db.String(100),nullable=False); location=db.Column(db.String(100),default=''); details=db.Column(db.Text,default=''); stage=db.Column(db.String(30),default='new',index=True); urgency=db.Column(db.String(30),default='unspecified',index=True); followup=db.Column(db.Date,index=True); created=db.Column(db.DateTime,default=utc_now,index=True)
class Activity(db.Model):
    id=db.Column(db.Integer,primary_key=True); inquiry_id=db.Column(db.Integer,db.ForeignKey('inquiry.id'),nullable=False,index=True); kind=db.Column(db.String(30),nullable=False); body=db.Column(db.Text,nullable=False); created=db.Column(db.DateTime,default=utc_now)
class Appointment(db.Model):
    id=db.Column(db.Integer,primary_key=True); inquiry_id=db.Column(db.Integer,db.ForeignKey('inquiry.id'),nullable=False,index=True); start=db.Column(db.DateTime,nullable=False,index=True); end=db.Column(db.DateTime,nullable=False); status=db.Column(db.String(30),default='tentative'); notes=db.Column(db.Text,default='')
class Document(db.Model):
    id=db.Column(db.Integer,primary_key=True); number=db.Column(db.String(30),unique=True,nullable=False); kind=db.Column(db.String(20),nullable=False); inquiry_id=db.Column(db.Integer,db.ForeignKey('inquiry.id'),nullable=False,index=True); description=db.Column(db.String(300),nullable=False); amount_cents=db.Column(db.Integer,nullable=False); status=db.Column(db.String(30),default='draft',index=True); due=db.Column(db.Date); converted_from=db.Column(db.Integer,db.ForeignKey('document.id'),unique=True); created=db.Column(db.DateTime,default=utc_now)
class Payment(db.Model):
    id=db.Column(db.Integer,primary_key=True); document_id=db.Column(db.Integer,db.ForeignKey('document.id'),nullable=False,index=True); amount_cents=db.Column(db.Integer,nullable=False); kind=db.Column(db.String(10),nullable=False); method=db.Column(db.String(50),nullable=False); created=db.Column(db.DateTime,default=utc_now)

class RequestAttempt(db.Model):
    __tablename__='request_attempt'
    id=db.Column(db.Integer,primary_key=True); bucket=db.Column(db.String(24),nullable=False,index=True); subject_hash=db.Column(db.String(64),nullable=False,index=True); created=db.Column(db.DateTime,nullable=False,default=utc_now,index=True)

BASE='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{{ title }} | Surge Power</title><style>body{margin:0;background:#f5f3ec;color:#172b22;font:16px/1.5 system-ui}header{background:#173b30;color:white;padding:20px 5%;display:flex;gap:24px;align-items:center;flex-wrap:wrap}header a{color:white}main{max-width:1100px;margin:auto;padding:32px 20px}a{color:#165c46}button,.button{background:#173b30;color:white;border:0;padding:12px 16px;border-radius:4px;cursor:pointer}input,select,textarea{font:inherit;padding:10px;border:1px solid #9ba99e;border-radius:4px;max-width:100%;box-sizing:border-box}label{display:block;margin:12px 0}label input,label select,label textarea{display:block;width:100%}.panel{background:white;border:1px solid #d5ded6;border-radius:8px;padding:20px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.filters{display:flex;gap:8px;flex-wrap:wrap}.badge{padding:4px 8px;background:#e2eee5;border-radius:4px}.error{padding:12px;background:#ffeadc}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}.scroll{overflow:auto}small{color:#53685b}details{margin:14px 0}form.inline{display:inline}h1{font-size:2.3rem}nav{display:flex;gap:16px;flex-wrap:wrap}@media(max-width:600px){header{display:block}nav{margin-top:12px}.filters>*{width:100%}}</style></head><body><header><strong>SURGE ⚡ POWER <small style="color:#d6e2da">Owner workspace</small></strong>{% if current_user.is_authenticated %}<nav><a href="{{url_for('inquiries')}}">Inquiries</a><a href="{{url_for('calendar_view')}}">Calendar</a><a href="{{url_for('billing')}}">Billing</a><a href="/">Website</a></nav><form method="post" action="{{url_for('logout')}}"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><button>Sign out</button></form>{% endif %}</header><main>{% for message in get_flashed_messages() %}<p class="error" role="status">{{message}}</p>{% endfor %}{{ body|safe }}</main></body></html>'''
def render(title, content, **kwargs):
    inner=render_template_string(content, **kwargs)
    design='''<style>:root{--ink:#132d24;--muted:#62776a;--line:#dce4dd;--gold:#e9b641}body{background:#eef2ed;color:var(--ink)}header{background:#102e24;box-shadow:0 8px 24px #102e2420;padding-top:18px;padding-bottom:18px}header strong{font-size:1.12rem;letter-spacing:.04em}header nav{margin-left:auto}header nav a{text-decoration:none;color:#e7eee8;padding:8px;border-radius:5px}header nav a:hover{background:#ffffff1a}header button{background:#e9b641;color:#122b21}main{max-width:1180px;padding-top:44px}h1{font-size:clamp(2rem,4vw,3.2rem);letter-spacing:-.045em;line-height:1.05;margin-bottom:12px}h2{letter-spacing:-.025em}.panel{border-color:var(--line);box-shadow:0 6px 24px #173b300a;padding:24px}.grid .panel{margin:0}.badge{text-transform:capitalize;font-size:.85rem;font-weight:700;background:#e4f0e7;color:#205c3e}.filters{background:white;border:1px solid var(--line);padding:14px;border-radius:8px;margin:24px 0;align-items:center}.filters input,.filters select{flex:1;min-width:150px}button,.button{font-weight:700;min-height:44px}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #bd7624;outline-offset:3px}small{color:var(--muted)}@media(max-width:600px){main{padding:28px 16px}header nav{margin:12px 0}.grid{grid-template-columns:1fr 1fr}.filters>*{width:100%}}</style>'''
    shell=BASE.replace('</head>',design+'<link rel="stylesheet" href="/static/refresh.css?v=3"></head>').replace('<body>','<body class="owner">')
    shell=shell.replace('<strong>SURGE ⚡ POWER <small style="color:#d6e2da">Owner workspace</small></strong>','<a class="owner-brand" href="/"><img src="/static/surge-power-logo.png" alt="Surge Power LLC"><small>Owner workspace</small></a>')
    shell=shell.replace('<a href="/">Website</a>', '')
    result=render_template_string(shell,title=title,body=inner)
    for section in ['inquiries','calendar','billing']:
        if request.path.startswith('/owner/'+section): result=result.replace('href="/owner/'+section+'"','aria-current="page" href="/owner/'+section+'"',1)
    return result
def cents(value):
    try:
        amount=Decimal(value)
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2 or amount > Decimal('10000000'): raise ValueError()
        return int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation,ValueError): raise ValueError('Enter a valid positive amount with at most two decimal places.')
def parsed_date(value):
    return date.fromisoformat(value) if value else None
def local_today():
    return datetime.now(ZoneInfo(os.environ.get('SURGE_TIMEZONE','America/Phoenix'))).date()
def balance(doc):
    return doc.amount_cents-sum((p.amount_cents if p.kind=='payment' else -p.amount_cents) for p in Payment.query.filter_by(document_id=doc.id))

def local_secret(instance_path):
    path=Path(instance_path)/'surge-session.key'
    Path(instance_path).mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(instance_path,0o700)
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        os.chmod(path,0o600)
        value=path.read_text().strip()
        if len(value)<64: raise RuntimeError('The local session key is incomplete. Restore it from a secure backup before starting the app.')
        return value
    value=secrets.token_hex(48)
    with os.fdopen(fd,'w') as handle: handle.write(value)
    return value
def create_app(config=None):
    app=Flask(__name__)
    production=os.environ.get('SURGE_ENV')=='production'
    if production and len(os.environ.get('SURGE_SECRET',''))<32:
        raise RuntimeError('SURGE_SECRET must contain at least 32 characters when SURGE_ENV=production.')
    app.config.update(SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL','sqlite:///surge-flask.db'), SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE','').lower()=='true' or production, PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=16000, AUTO_CREATE_SCHEMA=os.environ.get('SURGE_AUTO_CREATE_SCHEMA','true').lower()=='true' and not production)
    app.config['SECRET_KEY']=os.environ.get('SURGE_SECRET') or local_secret(app.instance_path)
    if config: app.config.update(config)
    db.init_app(app); login.init_app(app); csrf.init_app(app); migrate.init_app(app,db); login.login_view='signin'
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if request.path == '/owner/calendar':
            flash('Your form session expired. Please review the visit details and submit again.')
            return redirect(url_for('calendar_view', inquiry=request.form.get('inquiry_id', ''), month=request.form.get('month', '')))
        return 'Your form session expired. Reload the page and try again.', 400
    @login.user_loader
    def load_user(uid): return db.session.get(User,int(uid)) if uid.isdigit() else None
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'; response.headers['X-Frame-Options']='DENY'; response.headers['Referrer-Policy']='strict-origin-when-cross-origin'; response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; form-action 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'"
        if request.is_secure: response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        if request.path.startswith('/owner'): response.headers['Cache-Control']='no-store'; response.headers['X-Robots-Tag']='noindex, nofollow'
        if request.path=='/' and response.mimetype=='text/html':
            markup=response.get_data(as_text=True).replace('<body>','<body class="public">').replace('</head>','<link rel="stylesheet" href="/static/refresh.css?v=3"></head>')
            markup=markup.replace('<div class="art" aria-hidden="true">ϟ</div>','<div class="charge-scene" role="img" aria-label="Illustration of an electric vehicle charging station"><div class="cable"></div><div class="charger"></div><div class="scene-caption">A better way to power your day<span>EV charging · General electrical work</span></div></div>')
            response.set_data(markup)
        return response

    def take_rate_limit(bucket, limit, window_seconds):
        identity=request.remote_addr or 'unknown'
        fingerprint=hmac.new(app.config['SECRET_KEY'].encode(),(bucket+':'+identity).encode(),hashlib.sha256).hexdigest()
        cutoff=utc_now()-timedelta(seconds=window_seconds)
        db.session.query(RequestAttempt).filter(RequestAttempt.created<cutoff).delete(synchronize_session=False)
        count=RequestAttempt.query.filter_by(bucket=bucket,subject_hash=fingerprint).filter(RequestAttempt.created>=cutoff).count()
        if count>=limit:
            db.session.rollback(); return False
        db.session.add(RequestAttempt(bucket=bucket,subject_hash=fingerprint)); db.session.commit(); return True
    app.extensions['surge_take_rate_limit']=take_rate_limit
    @app.route('/')
    def home():
        from app import HOME
        from public_shell import page
        body=HOME.replace('<form method="post" action="/inquiry">','<form method="post" action="/inquiry"><input type="hidden" name="csrf_token" value="'+__import__('flask_wtf.csrf',fromlist=['generate_csrf']).generate_csrf()+'">')
        body=body.replace('<a class="brand" href="#top" aria-label="Surge Power home"><img src="/images/surge-logo.jpg" alt="Surge Power LLC" /></a>','<a class="brand" href="#top" aria-label="Surge Power home"><img src="/static/surge-power-logo.png" alt="Surge Power LLC"></a>')
        body=body.replace('<a class="brand" href="/">SURGE<span>⚡</span>POWER</a>','<a class="brand" href="/"><img src="/static/surge-power-logo.png" alt="Surge Power LLC"></a>')
        body=body.replace('<nav aria-label="Main navigation">','<nav class="desktop-nav" aria-label="Main navigation"><a href="#services">Services</a><a href="#approach">Our approach</a><a href="#contact">Contact</a></nav><details class="mobile-menu"><summary>Menu</summary><nav aria-label="Mobile navigation">').replace('</nav><a class="btn" href="#contact">','</nav></details><a class="btn" href="#contact">',1)
        body=body.replace('<a href="https://www.instagram.com/theazevguy/">Instagram ↗</a></footer>','<a href="/privacy">Privacy</a><a href="https://www.instagram.com/theazevguy/">Instagram ↗</a></footer>')
        return page(body).replace('</style>','header{max-width:1500px;margin:auto}.hero{background:#153b2f;position:relative;overflow:hidden}.hero-copy{position:relative}.hero h1{max-width:850px}.hero .art{border-radius:12px;background:radial-gradient(circle at 50% 40%,#507763,#214c3c 56%,#173b30);box-shadow:inset 0 0 0 1px #ffffff1f}.section{max-width:1500px;margin:auto}.card h3{font-size:1.35rem;letter-spacing:-.025em}.card p{max-width:38ch;color:#455a4e}.contact{max-width:none}.contact form{background:#fbfaf3;padding:clamp(24px,4vw,48px);border-radius:10px;box-shadow:0 14px 35px #60480f24}.contact input,.contact textarea,.contact select{border-color:#bdc9bf}.btn,button{transition:transform .15s ease,box-shadow .15s ease}.btn:hover,button:hover{transform:translateY(-2px);box-shadow:0 6px 16px #0002}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}@media(min-width:701px){.mobile-menu{display:none}}@media(max-width:700px){.mobile-menu{position:relative}.mobile-menu nav{display:flex;position:absolute;z-index:2;right:0;min-width:180px;flex-direction:column;background:#fff;padding:16px;box-shadow:0 4px 15px #0003}.mobile-menu summary{cursor:pointer;padding:12px}.hero{gap:32px}.contact form{padding:24px}}:focus-visible{outline:3px solid #ad552e;outline-offset:3px}</style>')
    @app.post('/inquiry')
    def submit_inquiry():
        if not take_rate_limit('public-inquiry',5,900): return 'Too many quote requests from this connection. Please try again later or call Surge Power.',429
        if request.form.get('website','').strip(): return 'Thank you. Your request has been received.'
        name=request.form.get('name','').strip(); contact=request.form.get('contact','').strip(); service=request.form.get('service',''); location=request.form.get('location','').strip(); details=request.form.get('details','').strip()
        if not name or not contact or len(name)>100 or len(contact)>200 or service not in SERVICES or len(location)>100 or len(details)>3000: return 'Please check your details.',400
        db.session.add(Inquiry(name=name,contact=contact,service=service,location=location,details=details)); db.session.commit()
        return '<p>Thank you. Your request has been received.</p><a href="/">Back to home</a>'
    @app.route('/health')
    def health(): return 'ok'
    @app.route('/privacy')
    def privacy():
        from app import page
        from workspace_phase_two import get_business_profile
        from markupsafe import escape
        profile=get_business_profile(); contact='<a href="tel:'+''.join(c for c in profile.phone if c.isdigit() or c=='+')+'">'+str(escape(profile.phone))+'</a>'
        if profile.email: contact+=' · <a href="mailto:'+str(escape(profile.email))+'">'+str(escape(profile.email))+'</a>'
        body='<main class="wrap"><h1>Privacy</h1><p>When you send a quote request, we collect the contact and project details you choose to provide, including your preferred contact time and optional vehicle or equipment details.</p><p>We use this information to respond to your request and manage the related customer, project, appointment, estimate, and invoice records. We do not use inquiry details for advertising or send them to analytics in this build.</p><p>Records are stored in Surge Power’s owner workspace. The current application does not yet have an automated retention schedule or self-service deletion. To ask a question or request correction or deletion, contact Surge Power at '+contact+' or through <a href="https://www.instagram.com/theazevguy/">Instagram</a>.</p><p>Do not include payment-card or bank-account numbers in this form. Online payment processing is not enabled.</p><a href="/">Back to home</a></main>'
        return page(body, 'Privacy | Surge Power LLC')
    @app.route('/robots.txt')
    def robots(): return app.response_class('User-agent: *\nDisallow: /owner/\n',mimetype='text/plain')
    @app.route('/sitemap.xml')
    def sitemap():
        base=os.environ.get('PUBLIC_BASE_URL','').rstrip('/')
        if not base.startswith(('https://','http://')): return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',mimetype='application/xml')
        from xml.sax.saxutils import escape
        return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+escape(base+'/')+'</loc></url><url><loc>'+escape(base+'/privacy')+'</loc></url></urlset>',mimetype='application/xml')
    @app.route('/owner/login',methods=['GET','POST'])
    def signin():
        if request.method=='POST':
            if not take_rate_limit('owner-login',10,900): return 'Too many sign-in attempts. Try again later.',429
            user=User.query.filter_by(email=request.form.get('email','').strip().lower()).first()
            try: good=bool(user and ph.verify(user.password_hash,request.form.get('password','')))
            except (VerifyMismatchError,InvalidHashError): good=False
            if good:
                identity=request.remote_addr or 'unknown'; fingerprint=hmac.new(app.config['SECRET_KEY'].encode(),('owner-login:'+identity).encode(),hashlib.sha256).hexdigest()
                RequestAttempt.query.filter_by(bucket='owner-login',subject_hash=fingerprint).delete(); db.session.commit()
                session.clear(); login_user(user); session.permanent=True; return redirect(url_for('inquiries'))
            flash('Invalid email or password.')
        return render('Sign in','''<h1>Owner sign in</h1><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Email<input type="email" name="email" required></label><label>Password<input type="password" name="password" required></label><button>Sign in</button></form>''')
    @app.post('/owner/logout')
    @login_required
    def logout(): logout_user(); session.clear(); return redirect(url_for('signin'))
    @app.route('/owner')
    @app.route('/owner/inquiries')
    @login_required
    def inquiries():
        q=Inquiry.query; search=request.args.get('q','').strip(); stage=request.args.get('stage',''); urgency=request.args.get('urgency','')
        if search: q=q.filter(db.or_(Inquiry.name.ilike('%'+search+'%'),Inquiry.contact.ilike('%'+search+'%'),Inquiry.location.ilike('%'+search+'%')))
        if stage in STAGES: q=q.filter_by(stage=stage)
        if urgency in ['urgent','within a week','flexible','unspecified']: q=q.filter_by(urgency=urgency)
        page_number=request.args.get('page',1,type=int); pagination=q.order_by(Inquiry.created.desc(),Inquiry.id.desc()).paginate(page=max(1,page_number),per_page=25,error_out=False); records=pagination.items; totals=dict(db.session.query(Inquiry.stage,func.count(Inquiry.id)).group_by(Inquiry.stage).all()); counts={s:totals.get(s,0) for s in STAGES}
        return render('Inquiries','''<h1>Inquiries</h1><p>Track requests and follow-ups.</p><div class="grid">{% for s,n in counts.items() %}<div class="panel"><strong>{{n}}</strong> <span class="badge">{{s}}</span></div>{% endfor %}</div><form class="filters"><input name="q" aria-label="Search inquiries" value="{{request.args.get('q','')}}" placeholder="Search name, contact, area"><select name="stage" aria-label="Filter by stage"><option value="">All stages</option>{% for s in stages %}<option {{'selected' if request.args.get('stage')==s}}>{{s}}</option>{% endfor %}</select><select name="urgency" aria-label="Filter by urgency"><option value="">All urgency</option>{% for u in ['urgent','within a week','flexible','unspecified'] %}<option {{'selected' if request.args.get('urgency')==u}}>{{u}}</option>{% endfor %}</select><button>Filter</button><a href="{{url_for('inquiries')}}">Clear</a></form><p><a href="{{url_for('export_inquiries')}}">Export CSV</a></p>{% for i in records %}<article class="panel"><h2><a href="{{url_for('inquiry_detail',ident=i.id)}}">{{i.name}}</a></h2><p>{{i.service}} · {{i.location}} · <span class="badge">{{i.stage}}</span> · {{i.urgency}}</p><small>{{i.created.strftime('%Y-%m-%d')}}{% if i.followup %} · Follow up {{i.followup}}{% endif %}</small></article>{% else %}<p>No matching inquiries.</p>{% endfor %}<nav aria-label="Inquiry pages">{% if pagination.has_prev %}<a href="{{url_for('inquiries',page=pagination.prev_num,q=request.args.get('q',''),stage=request.args.get('stage',''),urgency=request.args.get('urgency',''))}}">← Previous</a>{% endif %} <span>Page {{pagination.page}} of {{[pagination.pages,1]|max}}</span> {% if pagination.has_next %}<a href="{{url_for('inquiries',page=pagination.next_num,q=request.args.get('q',''),stage=request.args.get('stage',''),urgency=request.args.get('urgency',''))}}">Next →</a>{% endif %}</nav>''',records=records,counts=counts,stages=STAGES,pagination=pagination)
    @app.route('/owner/inquiries/<int:ident>',methods=['GET','POST'])
    @login_required
    def inquiry_detail(ident):
        item=db.get_or_404(Inquiry,ident)
        if request.method=='POST':
            action=request.form.get('action')
            if action=='update':
                stage=request.form.get('stage'); urgency=request.form.get('urgency')
                if stage not in STAGES or urgency not in ['urgent','within a week','flexible','unspecified']: abort(400)
                try: item.followup=parsed_date(request.form.get('followup'))
                except ValueError: abort(400)
                item.stage=stage; item.urgency=urgency
            elif action=='activity':
                body=request.form.get('body','').strip(); kind=request.form.get('kind')
                if not body or len(body)>3000 or kind not in ['note','call','email','meeting','other']: abort(400)
                db.session.add(Activity(inquiry_id=ident,kind=kind,body=body))
                if item.stage=='new': item.stage='contacted'
            else: abort(400)
            db.session.commit(); return redirect(url_for('inquiry_detail',ident=ident))
        activities=Activity.query.filter_by(inquiry_id=ident).order_by(Activity.created.desc()).limit(100).all()
        return render('Inquiry','''<p><a href="{{url_for('inquiries')}}">← Inquiries</a></p><h1>{{i.name}}</h1><div class="grid"><section class="panel"><h2>Project</h2><p>{{i.contact}}<br>{{i.service}}<br>{{i.location}}</p><p>{{i.details}}</p><p><a href="{{url_for('billing', inquiry=i.id)}}">Create estimate or invoice →</a></p><p><a href="{{url_for('calendar_view', inquiry=i.id)}}">Schedule a visit →</a></p></section><section class="panel"><h2>Follow-up</h2><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="update"><label>Stage<select name="stage">{% for s in stages %}<option {{'selected' if i.stage==s}}>{{s}}</option>{% endfor %}</select></label><label>Urgency<select name="urgency">{% for u in ['urgent','within a week','flexible','unspecified'] %}<option {{'selected' if i.urgency==u}}>{{u}}</option>{% endfor %}</select></label><label>Follow-up date<input type="date" name="followup" value="{{i.followup or ''}}"></label><button>Save</button></form></section></div><section class="panel"><h2>Activity</h2><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="activity"><label>Type<select name="kind">{% for k in ['note','call','email','meeting','other'] %}<option>{{k}}</option>{% endfor %}</select></label><label>Details<textarea name="body" required></textarea></label><button>Add activity</button></form>{% for a in activities %}<p><strong>{{a.kind}}</strong> · {{a.created.strftime('%Y-%m-%d %H:%M')}}<br>{{a.body}}</p>{% endfor %}</section>''',i=item,stages=STAGES,activities=activities)
    @app.route('/owner/calendar',methods=['GET','POST'])
    @login_required
    def calendar_view():
        if request.method=='POST':
            try:
                ident=int(request.form['inquiry_id']); status=request.form['status']
                if request.form.get('service_date'):
                    start=datetime.fromisoformat(request.form['service_date']+'T'+request.form['start_time'])
                    end=datetime.fromisoformat(request.form['service_date']+'T'+request.form['end_time'])
                else:
                    start=datetime.fromisoformat(request.form['start']); end=datetime.fromisoformat(request.form['end'])
                if not db.session.get(Inquiry,ident) or end<=start or status not in ['tentative','confirmed','en route','in progress','completed','rescheduled','cancelled','no access']: raise ValueError()
                db.session.rollback(); db.session.execute(text('BEGIN IMMEDIATE'))
                if status not in ['cancelled','rescheduled'] and Appointment.query.filter(Appointment.start<end,Appointment.end>start,Appointment.status.notin_(['cancelled','rescheduled'])).first(): db.session.rollback(); flash('That time overlaps another appointment.'); return redirect(url_for('calendar_view'))
                db.session.add(Appointment(inquiry_id=ident,start=start,end=end,status=status,notes=request.form.get('notes','')[:2000])); db.session.commit(); return redirect(url_for('calendar_view'))
            except (ValueError,KeyError):
                db.session.rollback()
                flash('Enter a valid customer, start and end time, and appointment status. The end time must be after the start time.')
                return redirect(url_for('calendar_view', inquiry=request.form.get('inquiry_id', ''), month=request.form.get('month', '')))
        month_value=request.args.get('month','')
        try:
            shown_month=datetime.strptime(month_value, '%Y-%m').date().replace(day=1) if month_value else local_today().replace(day=1)
        except ValueError:
            flash('Choose a valid month from the calendar controls.')
            return redirect(url_for('calendar_view'))
        next_month = (shown_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        previous_month = (shown_month - timedelta(days=1)).replace(day=1)
        month_end = next_month
        rows=Appointment.query.filter(Appointment.start >= datetime.combine(shown_month, datetime.min.time()), Appointment.start < datetime.combine(month_end, datetime.min.time())).order_by(Appointment.start).all()
        people=Inquiry.query.order_by(Inquiry.name).all(); names={p.id:p.name for p in people}
        by_day={}
        for appointment in rows: by_day.setdefault(appointment.start.date(), []).append(appointment)
        first_weekday, days_in_month=monthrange(shown_month.year,shown_month.month)
        grid_start=shown_month-timedelta(days=first_weekday)
        cells=[grid_start+timedelta(days=offset) for offset in range(42)]
        return render('Calendar','''<div class="calendar-heading"><div><h1>Calendar</h1><p>Plan visits and review scheduled work at a glance.</p></div><div class="calendar-controls"><a class="calendar-arrow" href="{{url_for('calendar_view',month=previous_month.strftime('%Y-%m'))}}" aria-label="Previous month">←</a><strong>{{shown_month.strftime('%B %Y')}}</strong><a class="calendar-arrow" href="{{url_for('calendar_view',month=next_month.strftime('%Y-%m'))}}" aria-label="Next month">→</a><a class="today-link" href="{{url_for('calendar_view')}}">Today</a></div></div><details class="panel schedule-panel" {{'open' if request.args.get('inquiry')}}><summary>Schedule a visit</summary><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="month" value="{{shown_month.strftime('%Y-%m')}}"><label>Inquiry<select name="inquiry_id" required>{% for p in people %}<option value="{{p.id}}" {{'selected' if request.args.get('inquiry')==p.id|string}}>{{p.name}} — {{p.service}}</option>{% endfor %}</select></label><label>Service date<input type="date" name="service_date" required></label><fieldset class="time-range"><legend>Visit time</legend><label>Start<input type="time" name="start_time" required></label><span aria-hidden="true">to</span><label>End<input type="time" name="end_time" required></label></fieldset><label>Status<select name="status"><option>tentative</option><option>confirmed</option><option>en route</option><option>in progress</option><option>completed</option><option>rescheduled</option><option>cancelled</option><option>no access</option></select></label><label>Notes<textarea name="notes"></textarea></label><button>Schedule visit</button></form></details><section class="calendar-grid" aria-label="{{shown_month.strftime('%B %Y')}} appointments"><div class="weekday">Mon</div><div class="weekday">Tue</div><div class="weekday">Wed</div><div class="weekday">Thu</div><div class="weekday">Fri</div><div class="weekday">Sat</div><div class="weekday">Sun</div>{% for day in cells %}<article class="calendar-day {{'outside-month' if day.month != shown_month.month}} {{'today' if day == today}}"><time datetime="{{day.isoformat()}}">{{day.day}}</time>{% for appointment in by_day.get(day,[]) %}<a class="calendar-event event-{{appointment.status.replace(' ','-')}}" href="{{url_for('inquiry_detail',ident=appointment.inquiry_id)}}"><span>{{appointment.start.strftime('%-I:%M %p')}}</span><strong>{{names.get(appointment.inquiry_id,'Inquiry')}}</strong><em>{{appointment.status}}</em></a>{% endfor %}</article>{% endfor %}</section><section class="calendar-agenda panel"><h2>This month</h2>{% for appointment in rows %}<article><time>{{appointment.start.strftime('%b %d · %-I:%M %p')}}</time><a href="{{url_for('inquiry_detail',ident=appointment.inquiry_id)}}">{{names.get(appointment.inquiry_id,'Inquiry')}}</a><span class="badge">{{appointment.status}}</span></article>{% else %}<p>No visits scheduled for this month.</p>{% endfor %}</section>''',rows=rows,people=people,names=names,shown_month=shown_month,previous_month=previous_month,next_month=next_month,cells=cells,by_day=by_day,today=local_today())
    @app.route('/owner/billing',methods=['GET','POST'])
    @login_required
    def billing():
        if request.method=='POST':
            try:
                ident=int(request.form['inquiry_id']); kind=request.form['kind']; description=request.form['description'].strip(); amount=cents(request.form['amount']); due=parsed_date(request.form.get('due'))
                if not db.session.get(Inquiry,ident) or kind not in ['estimate','invoice'] or not description or len(description)>300: raise ValueError()
                # SQLite serializes document-number allocation and insertion.
                db.session.execute(text('BEGIN IMMEDIATE')); number=db.session.execute(text('SELECT COALESCE(MAX(id),0)+1 FROM document')).scalar_one(); doc=Document(number=('EST' if kind=='estimate' else 'INV')+'-'+str(number).zfill(5),kind=kind,inquiry_id=ident,description=description,amount_cents=amount,due=due); db.session.add(doc); db.session.commit(); return redirect(url_for('document_view',ident=doc.id))
            except (ValueError,KeyError): db.session.rollback(); flash('Check the customer, description, amount, and due date.'); return redirect(url_for('billing'))
        q=Document.query; kind=request.args.get('kind',''); status=request.args.get('status',''); search=request.args.get('q','').strip()
        if kind in ['estimate','invoice']: q=q.filter_by(kind=kind)
        if status in ['draft','sent','paid','void']: q=q.filter_by(status=status)
        if search: q=q.join(Inquiry,Inquiry.id==Document.inquiry_id).filter(db.or_(Document.number.ilike('%'+search+'%'),Inquiry.name.ilike('%'+search+'%')))
        docs=q.order_by(Document.id.desc()).limit(100).all(); people=Inquiry.query.order_by(Inquiry.name).all()
        return render('Billing','''<h1>Billing</h1><p>Create and track estimates and invoices. Payments are recorded manually.</p><details class="panel"><summary>Create a document</summary><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Customer<select name="inquiry_id">{% for p in people %}<option value="{{p.id}}" {{'selected' if request.args.get('inquiry')==p.id|string}}>{{p.name}}</option>{% endfor %}</select></label><label>Type<select name="kind"><option>estimate</option><option>invoice</option></select></label><label>Work description<input name="description" maxlength="300" required></label><label>Amount in USD<input name="amount" inputmode="decimal" required></label><label>Due date<input type="date" name="due"></label><button>Create document</button></form></details><form class="filters"><input name="q" placeholder="Search name or number" value="{{request.args.get('q','')}}"><select name="kind"><option value="">All types</option>{% for k in ['estimate','invoice'] %}<option {{'selected' if request.args.get('kind')==k}}>{{k}}</option>{% endfor %}</select><select name="status"><option value="">All statuses</option>{% for s in ['draft','sent','paid','void'] %}<option {{'selected' if request.args.get('status')==s}}>{{s}}</option>{% endfor %}</select><button>Filter</button></form>{% for d in docs %}<article class="panel"><h2><a href="{{url_for('document_view',ident=d.id)}}">{{d.number}} · {{names.get(d.inquiry_id)}}</a></h2><p>{{d.kind}} · <span class="badge">{{d.status}}</span> · ${{'%.2f'|format(d.amount_cents / 100)}}</p></article>{% else %}<p>No matching documents.</p>{% endfor %}''',docs=docs,people=people,names={p.id:p.name for p in people})
    @app.route('/owner/billing/<int:ident>',methods=['GET','POST'])
    @login_required
    def document_view(ident):
        doc=db.get_or_404(Document,ident); person=db.get_or_404(Inquiry,doc.inquiry_id)
        if request.method=='POST':
            action=request.form.get('action')
            if action in ['payment','refund']:
                try:
                    amount=cents(request.form.get('amount','')); method=request.form.get('method','').strip()
                    if doc.kind!='invoice' or doc.status in ['void','draft'] or not method or len(method)>50: raise ValueError()
                    db.session.rollback(); db.session.execute(text('BEGIN IMMEDIATE')); doc=db.session.get(Document,ident)
                    if not doc or doc.kind!='invoice' or doc.status in ['void','draft']: raise ValueError()
                    remaining=balance(doc); net=doc.amount_cents-remaining
                    if (action=='payment' and amount>remaining) or (action=='refund' and amount>net): raise ValueError()
                    db.session.add(Payment(document_id=ident,amount_cents=amount,kind=action,method=method)); doc.status='paid' if action=='payment' and amount==remaining else 'sent'; db.session.commit()
                except ValueError: db.session.rollback(); flash('Amount exceeds the available balance, or the document is not payable.')
            elif action=='status':
                status=request.form.get('status'); db.session.rollback(); db.session.execute(text('BEGIN IMMEDIATE')); doc=db.session.get(Document,ident); net=doc.amount_cents-balance(doc)
                if status not in ['draft','sent','void'] or (net and status in ['draft','void']): db.session.rollback(); abort(400)
                doc.status=status; db.session.commit()
            elif action=='convert' and doc.kind=='estimate':
                try:
                    db.session.rollback(); db.session.execute(text('BEGIN IMMEDIATE')); existing=Document.query.filter_by(converted_from=ident).first()
                    if not existing:
                        original=db.session.get(Document,ident); number=db.session.execute(text('SELECT COALESCE(MAX(id),0)+1 FROM document')).scalar_one(); existing=Document(number='INV-'+str(number).zfill(5),kind='invoice',inquiry_id=original.inquiry_id,description=original.description,amount_cents=original.amount_cents,converted_from=ident); db.session.add(existing); db.session.commit()
                    return redirect(url_for('document_view',ident=existing.id))
                except Exception: db.session.rollback(); raise
            else: abort(400)
            return redirect(url_for('document_view',ident=ident))
        payments=Payment.query.filter_by(document_id=ident).order_by(Payment.id.desc()).all()
        return render('Document','''<p><a href="{{url_for('billing')}}">← Billing</a></p><h1>{{d.number}}</h1><div class="panel"><p>{{d.kind|title}} · <span class="badge">{{d.status}}</span></p><h2>{{p.name}}</h2><p>{{p.contact}}<br>{{d.description}}</p><p>Total: ${{'%.2f'|format(d.amount_cents/100)}}<br>Balance: ${{'%.2f'|format(remaining/100)}}{% if d.due %}<br>Due: {{d.due}}{% endif %}</p><p><a href="{{url_for('document_pdf',ident=d.id)}}">Download PDF</a></p></div><div class="grid"><section class="panel"><h2>Update status</h2><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="status"><label>Status<select name="status"><option>draft</option><option>sent</option><option>void</option></select></label><button>Update</button></form>{% if d.kind=='estimate' %}<form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><input type="hidden" name="action" value="convert"><button>Convert to invoice</button></form>{% endif %}</section>{% if d.kind=='invoice' %}<section class="panel"><h2>Record payment or refund</h2><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Action<select name="action"><option>payment</option><option>refund</option></select></label><label>Amount in USD<input name="amount" required></label><label>Method<input name="method" required></label><button>Record</button></form>{% for x in payments %}<p>{{x.kind}} · ${{'%.2f'|format(x.amount_cents/100)}} · {{x.method}} · {{x.created.strftime('%Y-%m-%d')}}</p>{% endfor %}</section>{% endif %}</div>''',d=doc,p=person,payments=payments,remaining=balance(doc))
    @app.get('/owner/billing/<int:ident>/pdf')
    @login_required
    def document_pdf(ident):
        doc=db.get_or_404(Document,ident); person=db.get_or_404(Inquiry,doc.inquiry_id); buffer=io.BytesIO(); pdf=canvas.Canvas(buffer); pdf.setFont('Helvetica-Bold',20); pdf.drawString(50,790,'Surge Power LLC'); pdf.setFont('Helvetica',12)
        for n,line in enumerate([doc.kind.title()+' '+doc.number, 'Customer: '+person.name, 'Contact: '+person.contact, 'Project: '+doc.description, 'Total: $'+format(doc.amount_cents/100,'.2f'), 'Balance: $'+format(balance(doc)/100,'.2f'), 'Due: '+str(doc.due or 'Not specified')]): pdf.drawString(50,750-n*25,line[:110])
        pdf.showPage(); pdf.save(); buffer.seek(0); return send_file(buffer,mimetype='application/pdf',as_attachment=True,download_name=doc.number+'.pdf')
    @app.get('/owner/export.csv')
    @login_required
    def export_inquiries():
        output=io.StringIO(); writer=csv.writer(output); writer.writerow(['Name','Contact','Service','Location','Details','Stage','Urgency','Follow-up'])
        def safe(v):
            v=str(v or ''); return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
        for i in Inquiry.query.order_by(Inquiry.id): writer.writerow([safe(x) for x in [i.name,i.contact,i.service,i.location,i.details,i.stage,i.urgency,i.followup]])
        return send_file(io.BytesIO(output.getvalue().encode('utf-8')),mimetype='text/csv',as_attachment=True,download_name='inquiries.csv')
    @app.cli.command('init-db')
    def init_db():
        if not app.config.get('AUTO_CREATE_SCHEMA'): raise SystemExit('Schema auto-creation is disabled. Apply database migrations with flask db upgrade.')
        db.create_all(); print('Database initialized. For ongoing schema changes, use flask db upgrade.')
    @app.cli.command('backup-db')
    def backup_db():
        url=db.engine.url
        if url.get_backend_name()!='sqlite': raise SystemExit('Use the managed database provider’s encrypted backup and restore workflow for non-SQLite databases.')
        source=Path(url.database)
        if not source.is_absolute(): source=Path(app.instance_path)/source
        if not source.exists(): raise SystemExit(f'Database file not found: {source}')
        folder=Path(os.environ.get('SURGE_BACKUP_DIR',Path(app.instance_path)/'backups')); folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=folder/('surge-'+utc_now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst: src.backup(dst)
        os.chmod(target,0o600); print(f'SQLite backup created at {target}. Store the backups directory on encrypted, access-controlled storage.')
    @app.cli.command('create-owner')
    def create_owner():
        email=os.environ.get('OWNER_EMAIL','').strip().lower(); password=os.environ.get('OWNER_PASSWORD','')
        if not email or len(password)<16: raise SystemExit('Set OWNER_EMAIL and OWNER_PASSWORD (at least 16 characters).')
        if User.query.filter_by(email=email).first(): raise SystemExit('Owner already exists.')
        user=User(email=email,password_hash=ph.hash(password)); db.session.add(user); db.session.flush()
        from workspace_phase_two import AccountAccess
        db.session.add(AccountAccess(user_id=user.id,role='owner',active=True)); db.session.commit(); print('Owner created.')
    @app.cli.command('create-user')
    def create_user():
        email=os.environ.get('OWNER_EMAIL','').strip().lower(); password=os.environ.get('OWNER_PASSWORD',''); role=os.environ.get('USER_ROLE','staff').strip().lower()
        if not email or len(password)<16 or role not in ['owner','manager','staff']:
            raise SystemExit('Set OWNER_EMAIL, OWNER_PASSWORD (at least 16 characters), and USER_ROLE (owner, manager, or staff).')
        if User.query.filter_by(email=email).first(): raise SystemExit('That account already exists.')
        from workspace_phase_two import AccountAccess
        user=User(email=email,password_hash=ph.hash(password)); db.session.add(user); db.session.flush()
        db.session.add(AccountAccess(user_id=user.id,role=role,active=True)); db.session.commit(); print('Workspace account created.')
    @app.cli.command('reset-owner-password')
    def reset_owner_password():
        email=os.environ.get('OWNER_EMAIL','').strip().lower(); password=os.environ.get('OWNER_PASSWORD','')
        user=User.query.filter_by(email=email).first()
        if not user or len(password)<16: raise SystemExit('Set OWNER_EMAIL for an existing account and OWNER_PASSWORD (at least 16 characters).')
        user.password_hash=ph.hash(password); db.session.commit(); print('Password reset for the selected account.')
    @app.cli.command('seed-demo')
    def seed_demo():
        for name,contact,service,location,details,stage in [('DEMO — Jordan Example','jordan@example.invalid',SERVICES[0],'Mesa','Demo: home EV charging.','new'),('DEMO — Avery Example','avery@example.invalid',SERVICES[1],'Chandler','Demo: additional circuit.','contacted'),('DEMO — Taylor Example','taylor@example.invalid',SERVICES[0],'Phoenix','Demo: charger planning.','qualified')]:
            if not Inquiry.query.filter_by(contact=contact).first(): db.session.add(Inquiry(name=name,contact=contact,service=service,location=location,details=details,stage=stage))
        db.session.commit(); print('Demo inquiries ready.')
    return app

app=create_app()

@app.get('/health/live')
def health_live():
    return {'status': 'ok'}, 200, {'Cache-Control': 'no-store'}

@app.get('/health/ready')
def health_ready():
    try:
        # Query an application table to detect missing migrations as well as outages.
        db.session.query(User.id).limit(1).all()
        return {'status': 'ready'}, 200, {'Cache-Control': 'no-store'}
    except Exception:
        db.session.rollback()
        return {'status': 'unavailable'}, 503, {'Cache-Control': 'no-store'}

# The workflow layer keeps the original inquiry data intact while adding the
# connected owner experience (dashboard, tasks, itemized documents and
# editable appointments) in a focused module.
from workspace_upgrade import install_workspace_upgrade
install_workspace_upgrade(app)
from workspace_phase_two import install_phase_two
install_phase_two(app)
