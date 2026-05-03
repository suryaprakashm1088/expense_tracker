"""
routes/auth.py — Login, logout, and change-credentials pages.

Routes registered:
  GET/POST  /login
  GET       /logout
  GET/POST  /change-credentials
"""
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
