import csv, hashlib, hmac, html, io, os, secrets, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB = os.environ.get('SURGE_DB', 'surge.db')
PASSWORD = os.environ.get('SURGE_OWNER_PASSWORD', '')
SECRET = os.environ.get('SURGE_SECRET', '')
def db():
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS inquiries (id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT NOT NULL, service TEXT NOT NULL, location TEXT, details TEXT, stage TEXT NOT NULL DEFAULT "new", created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    return con
def esc(s): return html.escape(str(s), quote=True)
def token():
    stamp = str(int(time.time()) // 28800)
    return stamp + '.' + hmac.new(SECRET.encode(), stamp.encode(), hashlib.sha256).hexdigest()
def valid(cookie):
    if not SECRET: return False
    for n in (int(time.time()) // 28800, int(time.time()) // 28800 - 1):
        stamp = str(n); candidate = stamp + '.' + hmac.new(SECRET.encode(), stamp.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(cookie, candidate): return True
    return False
STYLE='''<style>*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f3ec;color:#16251f;font:16px/1.6 system-ui,sans-serif}a{color:inherit}header,section,footer{padding:25px max(6vw,24px)}header{display:flex;align-items:center;justify-content:space-between;gap:20px}nav{display:flex;gap:24px}nav a{text-decoration:none} .brand{font-weight:900;letter-spacing:-.06em;font-size:1.7rem}.brand span{color:#ad552e}.btn,button{display:inline-block;background:#e9b641;color:#14221c;padding:15px 22px;border:0;border-radius:4px;font-weight:700;text-decoration:none;cursor:pointer}.hero{background:#183c31;color:#faf9f2;padding-top:95px;padding-bottom:100px;display:grid;grid-template-columns:1.1fr .9fr;gap:6vw}.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:.75rem;font-weight:800;color:#cf8b54}h1,h2,h3,p{margin-top:0}h1{font-size:clamp(3.4rem,7vw,7rem);line-height:.95;letter-spacing:-.065em;margin:22px 0}h2{font-size:clamp(2.4rem,5vw,4.6rem);line-height:1;letter-spacing:-.05em}.lead{max-width:560px;font-size:1.15rem;color:#d8e5dc}.art{border:1px solid #759486;min-height:330px;display:grid;place-items:center;background:radial-gradient(circle at center,#426855,#183c31 68%);font-size:12rem;color:#e9b641}.section{padding-top:95px;padding-bottom:95px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}.card{border-top:1px solid #97a69b;padding:25px 10px 0 0}.card b{color:#ac5b32}.dark{background:#e7e6da}.contact{background:#e8b744;display:grid;grid-template-columns:1fr 1fr;gap:8vw}.contact h2{max-width:550px}label{display:block;font-weight:650;margin-bottom:16px}input,select,textarea{display:block;width:100%;padding:13px;border:1px solid #8f968a;background:#fafaf5;font:inherit;border-radius:3px}button{background:#17392e;color:white}footer{background:#14271f;color:#e9eee9;display:flex;justify-content:space-between;gap:20px}.wrap{max-width:1100px;margin:auto;padding:40px 24px}.table{width:100%;border-collapse:collapse}.table td,.table th{text-align:left;padding:12px;border-bottom:1px solid #ccc}@media(max-width:700px){nav{display:none}.hero,.contact,.grid{grid-template-columns:1fr}.hero{padding-top:65px}.art{min-height:220px;font-size:8rem}footer{display:block}}</style>'''
def page(body, title='Surge Power LLC'):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="EV charger installation and general electrical work throughout the Phoenix area."><title>'+esc(title)+'</title>'+STYLE+'</head><body>'+body+'</body></html>'
HOME='''<header><a class="brand" href="/">SURGE<span>⚡</span>POWER</a><nav aria-label="Main navigation"><a href="#services">Services</a><a href="#approach">Our approach</a><a href="#contact">Contact</a></nav><a class="btn" href="#contact">Request a quote ↗</a></header><main><section class="hero"><div><p class="eyebrow">East Valley roots · Phoenix metro reach</p><h1>Power up<br>what’s next.</h1><p class="lead">EV charger installation and electrical work for the places you live and work. Tell Surge Power what you’re planning, and let’s get the conversation started.</p><a class="btn" href="#contact">Start your project ↗</a></div><div class="art" aria-hidden="true">ϟ</div></section><section class="section" id="services"><p class="eyebrow">What we do</p><h2>Good energy starts here.</h2><div class="grid"><article class="card"><b>01 / CHARGE</b><h3>EV charger installation</h3><p>Get your charging project moving with an installation planned around your vehicle, property, and electrical needs.</p></article><article class="card"><b>02 / POWER</b><h3>General electrical work</h3><p>From new circuits to electrical updates, tell us what your space needs and we’ll discuss the right next step.</p></article><article class="card"><b>03 / PLAN</b><h3>Project guidance</h3><p>Have an electrical project in mind? Share the details and we can discuss its scope and requirements.</p></article></div></section><section class="section dark" id="approach"><p class="eyebrow">A straightforward process</p><h2>From idea to energized.</h2><div class="grid"><article class="card"><b>01</b><h3>Tell us the plan</h3><p>Share your location, project details, and the best way to reach you.</p></article><article class="card"><b>02</b><h3>Talk through the details</h3><p>We’ll discuss your needs and what the project may involve.</p></article><article class="card"><b>03</b><h3>Move forward</h3><p>Decide on the next steps with a clear understanding of the work.</p></article></div></section><section class="section"><p class="eyebrow">Where we work</p><h2>East Valley based.<br>Phoenix connected.</h2><p>Surge Power LLC serves customers throughout the Phoenix metro area.</p></section><section class="section contact" id="contact"><div><p class="eyebrow">Let’s get to work</p><h2>Tell us what you’re powering.</h2><p>Send a few details about your project and how to reach you.</p><a href="https://www.instagram.com/theazevguy/">Find us on Instagram ↗</a></div><form method="post" action="/inquiry"><label>Name<input name="name" maxlength="100" required></label><label>Phone or email<input name="contact" maxlength="200" required></label><label>Service<select name="service"><option>EV charger installation</option><option>General electrical work</option><option>Other project</option></select></label><label>City or area<input name="location" maxlength="100"></label><label>Project details<textarea name="details" rows="4" maxlength="3000"></textarea></label><button>Send request ↗</button></form></section></main><footer><div><strong>SURGE POWER LLC</strong><p>Electrical work for the Phoenix metro.</p></div><a href="https://www.instagram.com/theazevguy/">Instagram ↗</a></footer>'''
class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, headers=()):
        data=body.encode(); self.send_response(code); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','same-origin'); self.send_header('Cache-Control','no-store')
        for k,v in headers: self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def form(self):
        length=int(self.headers.get('Content-Length','0'))
        if length>10000: return {}
        return {k:v[0].strip() for k,v in parse_qs(self.rfile.read(length).decode('utf-8',errors='replace')).items()}
    def authorized(self):
        cookies=dict(part.strip().split('=',1) for part in self.headers.get('Cookie','').split(';') if '=' in part)
        return valid(cookies.get('session',''))
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/': return self.send(200,page(HOME))
        if path=='/health': return self.send(200,'ok')
        if path=='/owner/login': return self.send(200,page('<main class="wrap"><h1>Owner sign in</h1><form method="post"><label>Password<input type="password" name="password" required></label><button>Sign in</button></form></main>'))
        if path.startswith('/owner'):
            if not self.authorized(): return self.send(303,'', [('Location','/owner/login')])
            with db() as con: rows=con.execute('SELECT id,name,contact,service,location,details,stage,created FROM inquiries ORDER BY id DESC').fetchall()
            content='<main class="wrap"><p><a href="/">← Website</a></p><h1>Inquiries</h1><p>Requests are saved here. Update a stage as you follow up.</p><form method="post" action="/owner/logout"><button>Sign out</button></form>'
            for row in rows:
                i,name,contact,service,location,details,stage,created=row
                content+=f'<article class="card"><h3>{esc(name)} · {esc(service)}</h3><p>{esc(contact)} · {esc(location)} · {esc(created)}</p><p>{esc(details)}</p><form method="post" action="/owner/stage"><input type="hidden" name="csrf" value="{esc(token())}"><input type="hidden" name="id" value="{i}"><label>Stage<select name="stage">'+''.join(f'<option {"selected" if stage==s else ""}>{s}</option>' for s in ['new','contacted','qualified','quote sent','won','lost','closed'])+'</select></label><button>Save stage</button></form></article>'
            return self.send(200,page(content+'</main>','Owner workspace'))
        self.send(404,page('<main class="wrap"><h1>Page not found</h1><a href="/">Go home</a></main>'))
    def do_POST(self):
        path=urlparse(self.path).path; form=self.form()
        if path=='/inquiry':
            name=form.get('name',''); contact=form.get('contact',''); service=form.get('service','')
            if not name or not contact or len(name)>100 or len(contact)>200 or service not in ['EV charger installation','General electrical work','Other project'] or len(form.get('details',''))>3000 or len(form.get('location',''))>100: return self.send(400,page('<main class="wrap"><h1>Please check your details.</h1><a href="/#contact">Return to form</a></main>'))
            with db() as con: con.execute('INSERT INTO inquiries(name,contact,service,location,details) VALUES(?,?,?,?,?)',(name,contact,service,form.get('location',''),form.get('details','')))
            return self.send(200,page('<main class="wrap"><h1>Thanks for reaching out.</h1><p>Your request has been received.</p><a href="/">Back to home</a></main>'))
        if path=='/owner/login':
            if PASSWORD and SECRET and hmac.compare_digest(form.get('password',''),PASSWORD): return self.send(303,'',[('Location','/owner'),('Set-Cookie','session='+token()+'; HttpOnly; SameSite=Strict; Path=/; Secure')])
            return self.send(403,page('<main class="wrap"><h1>Unable to sign in.</h1><a href="/owner/login">Try again</a></main>'))
        if path=='/owner/logout': return self.send(303,'',[('Location','/owner/login'),('Set-Cookie','session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/; Secure')])
        if path=='/owner/stage' and self.authorized() and valid(form.get('csrf','')) and form.get('stage') in ['new','contacted','qualified','quote sent','won','lost','closed'] and form.get('id','').isdigit():
            with db() as con: con.execute('UPDATE inquiries SET stage=? WHERE id=?',(form['stage'],int(form['id'])))
            return self.send(303,'',[('Location','/owner')])
        self.send(403,'Forbidden')
if __name__=='__main__':
    db().close(); ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8000'))),Handler).serve_forever()
