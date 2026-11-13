"""Service information and bounded workspace search."""
from flask import request, url_for
from flask_login import login_required
from markupsafe import escape
from sqlalchemy import or_


def install(app):
    from backend import Inquiry, Document, render
    from workspace_phase_two import Customer
    from public_shell import page

    services = {
        'ev-charging': ('EV charger installation', 'Charging planned around your home and vehicle.',
            'Tell us your vehicle, charger model if selected, parking location, and city. Panel capacity and the circuit route need to be assessed before an installation scope can be confirmed.',
            'Do I need to choose a charger first?', 'No. Share what you drive and where you park so the equipment and installation requirements can be discussed.'),
        'electrical': ('General electrical work', 'Power for the way you use your space.',
            'Share the equipment, outlets, circuits, or electrical updates you have in mind. Include the property location and any existing issues so the next assessment can be planned.',
            'Can I get a price from a description?', 'Your details help start the conversation. A final scope may require a site assessment and confirmation of existing electrical conditions.'),
        'garage-lighting': ('Garage lighting', 'A brighter space for work and hobbies.',
            'Describe the garage size, current lighting, and how you use the space. Surge Power’s featured garage project shows a bordered hex-lighting installation; your project will be scoped for your property.',
            'Can the lighting be tailored to my garage?', 'Discuss the layout, brightness, equipment, and existing wiring with Surge Power before selecting an installation plan.'),
    }

    @app.get('/services/<slug>')
    def service_information(slug):
        from flask import abort
        if slug not in services:
            abort(404)
        title, heading, details, question, answer = services[slug]
        body = f'''<header><a href="/">Surge Power LLC</a><a class="btn" href="/#contact">Request a quote ↗</a></header>
        <main class="wrap"><p class="eyebrow">East Valley · Phoenix metro</p><h1>{title}</h1>
        <h2>{heading}</h2><p>{details}</p><h3>{question}</h3><p>{answer}</p>
        <p><a class="btn" href="/#contact">Tell us about your project ↗</a></p>
        <p><a href="/#work">See recent projects</a> · <a href="/">Back to home</a></p></main>'''
        return page(body, title + ' | Surge Power LLC')

    @app.get('/owner/search')
    @login_required
    def workspace_search():
        query = request.args.get('q', '').strip()[:100]
        groups = []
        if query:
            term = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            groups = [
                ('Inquiries', [(x.name, url_for('phase_two_inquiry', ident=x.id)) for x in Inquiry.query.filter(or_(Inquiry.name.ilike(term, escape='\\'), Inquiry.contact.ilike(term, escape='\\'), Inquiry.location.ilike(term, escape='\\'))).limit(30)]),
                ('Customers', [(x.name, '/owner/customers/' + str(x.id)) for x in Customer.query.filter(or_(Customer.name.ilike(term, escape='\\'), Customer.contact.ilike(term, escape='\\'))).limit(30)]),
                ('Documents', [(x.number, '/owner/billing/' + str(x.id)) for x in Document.query.filter(Document.number.ilike(term, escape='\\')).limit(30)]),
            ]
        return render('Search', '''<h1>Search workspace</h1><form method="get"><label>Name, contact, city, or document number<input name="q" value="{{q}}" maxlength="100" required></label><button>Search</button></form>{% for title, rows in groups %}<section class="panel"><h2>{{title}}</h2>{% for label, href in rows %}<p><a href="{{href}}">{{label}}</a></p>{% else %}<p>No matches.</p>{% endfor %}</section>{% endfor %}''', q=query, groups=groups)

    @app.after_request
    def discoverability(response):
        if response.mimetype == 'text/html' and response.status_code == 200:
            html = response.get_data(as_text=True)
            html = html.replace('</head>', '<link rel="stylesheet" href="/static/final-polish.css?v=1"><script src="/static/final-polish.js?v=1" defer></script></head>')
            if request.path == '/':
                links = ' · '.join(f'<a href="/services/{slug}">{escape(data[0])}</a>' for slug, data in services.items())
                html = html.replace('</footer>', '<nav aria-label="Service information">' + links + '</nav></footer>')
            elif request.path.startswith('/owner/') and request.path != '/owner/login':
                html = html.replace('</nav>', '<a href="/owner/search">Search workspace</a></nav>', 1)
            response.set_data(html)
        return response
