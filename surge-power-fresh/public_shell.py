"""Minimal document shell for the public site, independent from the legacy prototype."""
from html import escape


def page(body: str, title: str = "Surge Power LLC") -> str:
    safe_title = escape(title, quote=True)
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="description" content="EV charger installation and general electrical work in the Phoenix metro. Contact Surge Power LLC to discuss your project.">'
        '<meta name="theme-color" content="#0a0a09">'
        '<link rel="icon" type="image/png" href="/static/surge-power-logo.png">'
        '<link rel="stylesheet" href="/static/public-base.css?v=1">'
        f'<title>{safe_title}</title></head><body>{body}</body></html>'
    )
