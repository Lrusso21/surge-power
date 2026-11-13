"""Single-use email account recovery; tokens are stored only as hashes."""
import hashlib
import os
import secrets
from datetime import timedelta
from urllib.parse import urlparse
from flask import flash, redirect, request
from flask_login import logout_user
from backend import db, User, ph, render, utc_now
from workspace_phase_two import send_message


class PasswordRecovery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    digest = db.Column(db.String(64), unique=True, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)


def install(app):
    if app.config.get('AUTO_CREATE_SCHEMA'):
        with app.app_context():
            db.create_all()

    @app.route('/owner/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'POST':
            if not app.extensions['surge_take_rate_limit']('password-reset', 5, 900):
                return 'Too many recovery requests. Try again later.', 429
            user = User.query.filter_by(email=request.form.get('email', '').strip().lower()[:254]).first()
            base = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
            if user and urlparse(base).scheme == 'https' and os.environ.get('SURGE_SMTP_HOST') and os.environ.get('SURGE_SMTP_FROM'):
                token = secrets.token_urlsafe(32)
                record = PasswordRecovery(user_id=user.id, digest=hashlib.sha256(token.encode()).hexdigest(), expires=utc_now()+timedelta(minutes=30))
                # Do not attach recovery emails to customer message history.
                from types import SimpleNamespace
                message = SimpleNamespace(recipient=user.email, subject='Reset your Surge Power password', body='Use this link within 30 minutes to reset your password: ' + base + '/owner/reset-password?token=' + token + '\nIf you did not request this, ignore this email.', status='draft', sent=None)
                try:
                    if send_message(message):
                        db.session.add(record); db.session.commit()
                except Exception:
                    db.session.rollback()
            flash('If this account is eligible and email is configured, a recovery link will be sent.')
            return redirect('/owner/forgot-password')
        return render('Password recovery', '''<h1>Password recovery</h1><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>Email<input type="email" name="email" required maxlength="254" autocomplete="username"></label><button>Request recovery link</button></form><p><a href="/owner/login">Back to sign in</a></p>''')

    @app.route('/owner/reset-password', methods=['GET', 'POST'])
    def reset_password():
        token = request.args.get('token', '')[:200]
        record = PasswordRecovery.query.filter_by(digest=hashlib.sha256(token.encode()).hexdigest(), used=False).first()
        if not record or record.expires < utc_now():
            return render('Recovery link expired', '<h1>This recovery link is invalid or expired.</h1><a href="/owner/forgot-password">Request another link</a>'), 400
        if request.method == 'POST':
            password = request.form.get('password', '')
            if len(password) < 16 or len(password) > 256 or password != request.form.get('confirm'):
                flash('Use 16–256 characters and matching passwords.')
            else:
                user = db.session.get(User, record.user_id)
                user.password_hash = ph.hash(password)
                PasswordRecovery.query.filter_by(user_id=user.id).update({'used': True})
                db.session.commit(); logout_user(); flash('Password updated. Sign in with your new password.')
                return redirect('/owner/login')
        response = app.make_response(render('Reset password', '''<h1>Reset password</h1><form method="post"><input type="hidden" name="csrf_token" value="{{csrf_token()}}"><label>New password<input name="password" type="password" minlength="16" maxlength="256" autocomplete="new-password" required></label><label>Confirm password<input name="confirm" type="password" minlength="16" maxlength="256" autocomplete="new-password" required></label><button>Set password</button></form>'''))
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.after_request
    def recovery_link(response):
        if request.path == '/owner/login' and response.mimetype == 'text/html':
            response.set_data(response.get_data(as_text=True).replace('</main>', '<p><a href="/owner/forgot-password">Forgot password?</a></p></main>'))
        return response
