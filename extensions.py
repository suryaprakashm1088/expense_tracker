"""
extensions.py — Flask app factory, CSRF, security headers, login middleware,
                and auth decorators.

Import `app`, `login_required`, `admin_required` from here in all route modules.

Dependency order: config → database → extensions → services/* → routes/*
"""
import secrets
from functools import wraps

from flask import Flask, session, abort, request, redirect, url_for, flash
import database as db
from config import PUBLIC_ENDPOINTS, MEMBER_ALLOWED, ADMIN_ONLY, CSRF_EXEMPT

# ── Create app ────────────────────────────────────────────────────────────────
app = Flask(__name__)

_secret_key = __import__("os").environ.get("SECRET_KEY")
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    print("WARNING: SECRET_KEY not set in .env — using a random key. Sessions will reset on restart.")
app.secret_key = _secret_key

# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from prometheus_flask_exporter import PrometheusMetrics
    _prom = PrometheusMetrics(
        app,
        default_labels={"app": "expense_tracker"},
        excluded_paths=["/health", "/metrics"],   # don't track these in histograms
    )
    _prom.info("expense_tracker_flask", "Flask app info", version="2.0")
except ImportError:
    pass  # prometheus-flask-exporter not installed — /metrics won't be available


# ── CSRF ──────────────────────────────────────────────────────────────────────

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = generate_csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST" and request.endpoint not in CSRF_EXEMPT:
        token = session.get('_csrf_token')
        # Accept CSRF token from form field (HTML forms) OR X-CSRFToken header (AJAX/JSON)
        form_token = request.form.get('_csrf_token') or request.headers.get('X-CSRFToken')
        if not token or not form_token or not secrets.compare_digest(token, form_token):
            abort(403)


# ── Context processor — pending_count badge ──────────────────────────────────

@app.context_processor
def inject_pending_count():
    """Make pending_count available in every template for the sidebar badge."""
    if session.get('admin_logged_in'):
        try:
            count = len(db.get_pending_members())
        except Exception:
            count = 0
    else:
        count = 0
    return {"pending_count": count}


# ── Login / access-control middleware ─────────────────────────────────────────

def _is_logged_in():
    return session.get('admin_logged_in') or session.get('member_logged_in')


@app.before_request
def require_login():
    if request.endpoint and request.endpoint not in PUBLIC_ENDPOINTS:
        if not _is_logged_in():
            return redirect(url_for('login', next=request.path))
        # Force admin to change default password
        if session.get('admin_logged_in') and session.get('must_change_password') \
                and request.endpoint != 'change_credentials':
            flash("Please change your default username and password before continuing.", "warning")
            return redirect(url_for('change_credentials'))
        # Members may only access their allowed routes
        if session.get('member_logged_in') and request.endpoint in ADMIN_ONLY:
            flash("You don't have permission to access that page.", "danger")
            return redirect(url_for('index'))


# ── Security headers ──────────────────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src https://cdn.jsdelivr.net https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    response.headers['Content-Security-Policy'] = csp
    return response


# ── Auth decorators (importable by route modules) ─────────────────────────────

def login_required(f):
    """Ensure the user (admin or member) is logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _is_logged_in():
            return redirect(url_for('login', next=request.url))
        if session.get('admin_logged_in') and session.get('must_change_password') \
                and request.endpoint != 'change_credentials':
            flash("Please change your default username and password before continuing.", "warning")
            return redirect(url_for('change_credentials'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Restrict a route to admin users only."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash("Administrator access required.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated
