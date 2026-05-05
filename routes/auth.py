"""
routes/auth.py — Login, logout, change-credentials, and member OTP self-service.

Routes registered:
  GET/POST  /login
  GET       /logout
  GET/POST  /change-credentials
  GET/POST  /member/request-otp    — member requests a WhatsApp OTP (public)
  GET/POST  /member/verify-otp     — member verifies OTP (public)
  GET/POST  /member/set-password   — member sets own password after OTP verify (public)
"""
import secrets
import string
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

import database as db
from extensions import app, login_required


@app.route("/login", methods=["GET", "POST"])
def login():
    from extensions import _is_logged_in
    if _is_logged_in():
        return redirect(url_for('index'))

    error = None
    otp   = None  # displayed only on first-time admin login

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # 1. Try admin credentials
        creds = db.get_admin_credentials()
        if creds and username == creds["username"] and \
                check_password_hash(creds["password_hash"], password):
            session['admin_logged_in']      = True
            session['admin_username']       = creds["username"]
            session['must_change_password'] = bool(creds["must_change_password"])
            if creds["must_change_password"]:
                flash("Welcome! Please set a new username and password to continue.", "info")
                return redirect(url_for('change_credentials'))
            next_url = request.args.get('next')
            return redirect(next_url if next_url and next_url.startswith('/') else url_for('index'))

        # 2. Try member credentials (username = WhatsApp number)
        member = db.get_member_for_login(username)
        if member and member.get("password_hash") and \
                check_password_hash(member["password_hash"], password):
            session['member_logged_in'] = True
            session['member_id']        = member["id"]
            session['member_name']      = member["name"]
            next_url = request.args.get('next')
            return redirect(next_url if next_url and next_url.startswith('/') else url_for('index'))

        error = "Invalid username or password."

    # Show initial OTP only when admin hasn't changed the default password yet
    if request.method == "GET":
        creds = db.get_admin_credentials()
        if creds and creds.get("must_change_password") and creds.get("initial_otp"):
            otp = creds["initial_otp"]

    return render_template("login.html", error=error, otp=otp)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))


@app.route("/change-credentials", methods=["GET", "POST"])
@login_required
def change_credentials():
    if request.method == "POST":
        new_username     = request.form.get("new_username", "").strip()
        current_password = request.form.get("current_password", "")
        new_password     = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        creds = db.get_admin_credentials()

        if not new_username:
            flash("Username cannot be empty.", "danger")
        elif len(new_username) < 3:
            flash("Username must be at least 3 characters.", "danger")
        elif not check_password_hash(creds["password_hash"], current_password):
            flash("Current password is incorrect.", "danger")
        elif len(new_password) < 8:
            flash("New password must be at least 8 characters.", "danger")
        elif new_password != confirm_password:
            flash("New passwords do not match.", "danger")
        elif new_password == current_password:
            flash("New password must be different from the current password.", "danger")
        else:
            new_hash = generate_password_hash(new_password)
            db.update_admin_credentials(new_username, new_hash)
            session['admin_username']       = new_username
            session['must_change_password'] = False
            flash("✅ Credentials updated successfully!", "success")
            return redirect(url_for('index'))

    return render_template("change_credentials.html")


# ─────────────────────────────────────────────────────────────────────────────
# Member self-service: WhatsApp OTP → set own password
# All three routes are PUBLIC (no login required) — listed in PUBLIC_ENDPOINTS.
# ─────────────────────────────────────────────────────────────────────────────

def _generate_otp(length=6):
    """Return a random numeric OTP string."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _send_otp_whatsapp(member, otp):
    """Send OTP to the member's WhatsApp number. Returns True on success."""
    from config import TWILIO_NUMBER
    from services.ai_clients import get_twilio_client
    twilio_cl = get_twilio_client()
    if not twilio_cl or not TWILIO_NUMBER:
        return False
    try:
        twilio_cl.messages.create(
            from_=TWILIO_NUMBER,
            to=member["whatsapp_number"],
            body=(
                f"🔐 Your Expense Tracker login code is: *{otp}*\n\n"
                f"Enter this code on the login page to set your password.\n"
                f"Valid for *10 minutes*. Do not share this code."
            ),
        )
        return True
    except Exception:
        return False


@app.route("/member/request-otp", methods=["GET", "POST"])
def member_request_otp():
    """Step 1 — member enters their WhatsApp number to receive an OTP."""
    from extensions import _is_logged_in
    if _is_logged_in():
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        raw_number = request.form.get("whatsapp_number", "").strip()
        # Normalise: strip spaces/dashes, ensure it starts with +
        digits = "".join(c for c in raw_number if c.isdigit() or c == "+")
        if not digits.startswith("+"):
            digits = "+" + digits

        member = db.get_approved_member_by_number(digits)
        if not member:
            error = "No approved member found with that WhatsApp number. Contact your admin."
        else:
            otp      = _generate_otp()
            otp_hash = generate_password_hash(otp)
            expires  = (datetime.now() + timedelta(minutes=10)).isoformat()
            db.set_member_otp(member["id"], otp_hash, expires)

            sent = _send_otp_whatsapp(member, otp)
            if sent:
                # Store member id in session so verify step knows who to check
                session["otp_pending_member_id"] = member["id"]
                flash(
                    f"✅ OTP sent to {digits} via WhatsApp. "
                    "Check your messages and enter the code below.",
                    "success",
                )
                return redirect(url_for("member_verify_otp"))
            else:
                # Twilio not configured — show OTP on screen (dev/local mode only)
                session["otp_pending_member_id"] = member["id"]
                flash(
                    f"⚠️ WhatsApp not configured — your OTP is: {otp} "
                    "(visible because Twilio is not set up)",
                    "warning",
                )
                return redirect(url_for("member_verify_otp"))

    return render_template("member_otp.html", step="request", error=error)


@app.route("/member/verify-otp", methods=["GET", "POST"])
def member_verify_otp():
    """Step 2 — member enters the OTP they received."""
    from extensions import _is_logged_in
    if _is_logged_in():
        return redirect(url_for("index"))

    member_id = session.get("otp_pending_member_id")
    if not member_id:
        flash("Session expired. Please request a new OTP.", "warning")
        return redirect(url_for("member_request_otp"))

    error = None
    if request.method == "POST":
        otp_entered = request.form.get("otp", "").strip()
        member = db.get_member_by_id(member_id)
        if not member:
            flash("Member not found.", "danger")
            return redirect(url_for("member_request_otp"))

        otp_hash    = member.get("login_otp_hash")
        otp_expires = member.get("login_otp_expires_at")

        if not otp_hash or not otp_expires:
            error = "No OTP found. Please request a new one."
        elif datetime.fromisoformat(otp_expires) < datetime.now():
            db.clear_member_otp(member_id)
            error = "OTP has expired (10 minutes). Please request a new one."
        elif not check_password_hash(otp_hash, otp_entered):
            error = "Incorrect OTP. Check your WhatsApp message and try again."
        else:
            # OTP correct — mark verified, clear OTP, send to set-password
            db.clear_member_otp(member_id)
            session.pop("otp_pending_member_id", None)
            session["otp_verified_member_id"] = member_id
            flash("✅ OTP verified! Now set your password.", "success")
            return redirect(url_for("member_set_password"))

    return render_template("member_otp.html", step="verify", error=error)


@app.route("/member/set-password", methods=["GET", "POST"])
def member_set_password():
    """Step 3 — member sets their own web-login password after OTP verification."""
    from extensions import _is_logged_in
    if _is_logged_in():
        return redirect(url_for("index"))

    member_id = session.get("otp_verified_member_id")
    if not member_id:
        flash("Session expired. Please start again.", "warning")
        return redirect(url_for("member_request_otp"))

    member = db.get_member_by_id(member_id)
    if not member:
        flash("Member not found.", "danger")
        return redirect(url_for("member_request_otp"))

    error = None
    if request.method == "POST":
        new_password     = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            error = "Password must be at least 8 characters."
        elif new_password != confirm_password:
            error = "Passwords do not match."
        else:
            db.set_member_password(member_id, generate_password_hash(new_password))
            session.pop("otp_verified_member_id", None)
            # Log them straight in
            session["member_logged_in"] = True
            session["member_id"]        = member_id
            session["member_name"]      = member.get("nickname") or member.get("name", "")
            flash(
                "🎉 Password set! You're now logged in. "
                "Use your WhatsApp number to log in next time.",
                "success",
            )
            return redirect(url_for("index"))

    return render_template("member_otp.html", step="set_password",
                           member=member, error=error)
