"""
routes/admin.py — Admin-only pages: categories, members, onboarding, shop mappings,
                   unknown contacts, and temp image serving.

Routes registered:
  GET         /categories
  POST        /categories/add
  GET/POST    /categories/edit/<id>
  POST        /categories/delete/<id>
  GET         /members
  POST        /members/approve/<id>
  POST        /members/assign-family/<id>
  POST        /members/toggle/<id>
  POST        /members/delete/<id>
  POST        /members/toggle-admin/<id>
  POST        /members/set-password/<id>
  POST        /members/revoke-login/<id>
  POST        /members/toggle-login/<id>   — enable/disable web login (keeps password)
  POST        /members/send-otp/<id>       — admin sends WhatsApp OTP so member can set own password
  GET/POST    /onboarding
  POST        /onboarding/revoke/<code>
  GET/POST    /shop-mappings
  POST        /shop-mappings/delete/<id>
  GET         /unknown-contacts
  GET         /img/<uid>         (public — used by Docker Model Runner)
"""
import os
import glob as _glob

from flask import render_template, request, redirect, url_for, flash, Response
from werkzeug.security import generate_password_hash

import database as db
from extensions import app, login_required, admin_required
from config import TWILIO_NUMBER, DASHBOARD_URL
from services.ai_clients import get_twilio_client
from services.invite import generate_code, parse_expiry


# ── Categories ────────────────────────────────────────────────────────────────

@login_required
@app.route("/categories")
def categories():
    cats = db.get_categories_full()
    return render_template("categories.html", categories=cats)


@login_required
@app.route("/categories/add", methods=["POST"])
def add_category():
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "📦").strip()
    if not name:
        flash("Category name is required.", "danger")
        return redirect(url_for("categories"))
    db.add_category(name, icon)
    flash(f"✅ Category '{name}' added!", "success")
    return redirect(url_for("categories"))


@login_required
@app.route("/categories/edit/<int:cat_id>", methods=["GET", "POST"])
def edit_category(cat_id):
    cat = db.get_category_by_id(cat_id)
    if not cat:
        flash("Category not found.", "danger")
        return redirect(url_for("categories"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        icon = request.form.get("icon", "📦").strip()
        if not name:
            flash("Category name is required.", "danger")
            return render_template("edit_category.html", cat=cat)
        db.update_category(cat_id, name, icon)
        flash(f"✅ Category updated to '{name}'.", "success")
        return redirect(url_for("categories"))
    return render_template("edit_category.html", cat=cat)


@login_required
@app.route("/categories/delete/<int:cat_id>", methods=["POST"])
def delete_category(cat_id):
    cat = db.get_category_by_id(cat_id)
    if cat:
        db.delete_category(cat_id)
        flash(f"🗑️ Category '{cat['name']}' deleted.", "info")
    return redirect(url_for("categories"))


# ── Members ───────────────────────────────────────────────────────────────────

@login_required
@app.route("/members")
def members():
    all_members = db.get_all_members()
    families    = db.get_all_families()
    return render_template("members.html", members=all_members, families=families)


@admin_required
@login_required
@app.route("/members/approve/<int:member_id>", methods=["POST"])
def approve_member(member_id):
    """Approve a pending member, optionally assign a family, and notify via WhatsApp."""
    family_id = request.form.get("family_id") or None
    if family_id:
        family_id = int(family_id)
    db.approve_member(member_id, family_id=family_id)

    member = db.get_member_by_id(member_id)
    if member:
        name      = member.get("nickname") or member.get("name", "Member")
        twilio_cl = get_twilio_client()
        if twilio_cl and TWILIO_NUMBER and member.get("whatsapp_number"):
            family      = db.get_family_by_id(family_id) if family_id else None
            family_name = family["name"] if family else "the expense tracker"
            try:
                twilio_cl.messages.create(
                    from_=TWILIO_NUMBER,
                    to=member["whatsapp_number"],
                    body=(
                        f"✅ Great news, {name}! Your registration has been *approved*.\n\n"
                        f"You've been added to *{family_name}*.\n"
                        f"Send *help* to see all available commands. Welcome! 🎉"
                    ),
                )
            except Exception:
                pass
        flash(f"✅ {name} approved and notified via WhatsApp.", "success")
    return redirect(url_for("members"))


@admin_required
@login_required
@app.route("/members/assign-family/<int:member_id>", methods=["POST"])
def assign_family(member_id):
    """Change (or clear) a member's family assignment."""
    family_id = request.form.get("family_id") or None
    if family_id:
        family_id = int(family_id)
    db.update_member_family(member_id, family_id)
    member = db.get_member_by_id(member_id)
    name   = member.get("nickname") or member.get("name", "Member") if member else "Member"
    flash(f"Family updated for {name}.", "success")
    return redirect(url_for("members"))


@login_required
@app.route("/members/toggle/<int:member_id>", methods=["POST"])
def toggle_member(member_id):
    db.toggle_member(member_id)
    flash("Member status updated.", "info")
    return redirect(url_for("members"))


@login_required
@app.route("/members/delete/<int:member_id>", methods=["POST"])
def delete_member(member_id):
    db.delete_member(member_id)
    flash("Member removed.", "info")
    return redirect(url_for("members"))


@login_required
@app.route("/members/toggle-admin/<int:member_id>", methods=["POST"])
def toggle_admin(member_id):
    m = db.get_member_by_id(member_id)
    if m:
        db.update_member_admin(member_id, 0 if m.get("is_admin") else 1)
        flash("Admin status updated.", "info")
    return redirect(url_for("members"))


@admin_required
@login_required
@app.route("/members/set-password/<int:member_id>", methods=["POST"])
def set_member_password_route(member_id):
    """Admin sets a web-login password for a member."""
    password = request.form.get("member_password", "").strip()
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "danger")
    else:
        db.set_member_password(member_id, generate_password_hash(password))
        flash("✅ Web login password set. Member can now log in with their WhatsApp number.", "success")
    return redirect(url_for("members"))


@admin_required
@login_required
@app.route("/members/revoke-login/<int:member_id>", methods=["POST"])
def revoke_member_login_route(member_id):
    """Admin revokes web-login access and wipes the password for a member."""
    db.revoke_member_login(member_id)
    flash("Web login access removed for this member.", "info")
    return redirect(url_for("members"))


@admin_required
@login_required
@app.route("/members/toggle-login/<int:member_id>", methods=["POST"])
def toggle_member_login(member_id):
    """Toggle can_login on/off for a member (keeps their password hash intact)."""
    m = db.get_member_by_id(member_id)
    if m:
        db.toggle_member_web_login(member_id)
        state = "disabled" if m.get("can_login") else "enabled"
        name  = m.get("nickname") or m.get("name", "Member")
        flash(f"Web login {state} for {name}.", "info")
    return redirect(url_for("members"))


@admin_required
@login_required
@app.route("/members/send-otp/<int:member_id>", methods=["POST"])
def send_member_otp(member_id):
    """Admin sends a WhatsApp OTP to the member so they can set their own password."""
    import secrets, string
    from datetime import datetime, timedelta
    from werkzeug.security import generate_password_hash as gph
    from config import TWILIO_NUMBER
    from services.ai_clients import get_twilio_client

    m = db.get_member_by_id(member_id)
    if not m:
        flash("Member not found.", "danger")
        return redirect(url_for("members"))

    otp      = "".join(secrets.choice(string.digits) for _ in range(6))
    otp_hash = gph(otp)
    expires  = (datetime.now() + timedelta(minutes=10)).isoformat()
    db.set_member_otp(member_id, otp_hash, expires)

    # Ensure web login is enabled so the member can actually use it
    if not m.get("can_login"):
        db.toggle_member_web_login(member_id)

    twilio_cl = get_twilio_client()
    name      = m.get("nickname") or m.get("name", "Member")
    sent      = False
    if twilio_cl and TWILIO_NUMBER and m.get("whatsapp_number"):
        try:
            twilio_cl.messages.create(
                from_=TWILIO_NUMBER,
                to=m["whatsapp_number"],
                body=(
                    f"👋 Hi {name}! Your admin has set up web login for you.\n\n"
                    f"🔐 Your one-time login code is: *{otp}*\n\n"
                    f"Go to {DASHBOARD_URL}/member/request-otp — enter your WhatsApp number, "
                    f"then enter this code to set your own password.\n"
                    f"Valid for *10 minutes*."
                ),
            )
            sent = True
        except Exception as exc:
            app.logger.warning("send_member_otp: Twilio error: %s", exc)

    if sent:
        flash(f"✅ OTP sent to {name} via WhatsApp. They can now set their own password.", "success")
    else:
        flash(
            f"⚠️ WhatsApp not configured — OTP for {name} is: {otp} "
            "(share this manually; Twilio is not set up)",
            "warning",
        )
    return redirect(url_for("members"))


# ── Onboarding (family setup + invite codes) ──────────────────────────────────

@login_required
@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    families     = db.get_all_families()
    active_codes = db.get_active_invite_codes()
    generated    = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_family":
            fname       = request.form.get("family_name", "").strip()
            admin_name  = request.form.get("admin_name", "").strip()
            admin_phone = request.form.get("admin_phone", "").strip()
            if not fname:
                flash("Family name is required.", "danger")
            else:
                fid = db.add_family(fname, created_by=admin_phone or None)
                if admin_phone and admin_name:
                    if not admin_phone.startswith("whatsapp:"):
                        admin_phone = "whatsapp:+" + admin_phone.lstrip("+")
                    db.add_member(
                        name=admin_name,
                        whatsapp_number=admin_phone,
                        is_approved=1,
                        family_id=fid,
                        is_admin=1,
                        nickname=admin_name,
                    )
                flash(f"✅ Family '{fname}' created!", "success")
                families = db.get_all_families()

        elif action == "generate_code":
            nickname  = request.form.get("nickname", "Member").strip()
            family_id = request.form.get("family_id", "")
            is_admin  = 1 if request.form.get("is_admin") else 0
            expiry    = request.form.get("expiry", "24hrs")
            max_uses  = int(request.form.get("max_uses", 1))
            expires_at = parse_expiry(expiry)

            if not family_id:
                flash("Select a family first.", "danger")
            else:
                code = generate_code()
                while db.get_invite_code(code):
                    code = generate_code()
                db.add_invite_code(
                    code=code,
                    family_id=int(family_id),
                    created_by="Web Admin",
                    expires_at=expires_at,
                    nickname=nickname,
                    is_admin=is_admin,
                    max_uses=max_uses,
                )
                family   = db.get_family_by_id(int(family_id))
                fam_name = family["name"] if family else "Family"
                generated = {
                    "code":         code,
                    "nickname":     nickname,
                    "family":       fam_name,
                    "expiry":       expiry,
                    "is_admin":     is_admin,
                    "twilio_number": TWILIO_NUMBER.replace("whatsapp:", "") if TWILIO_NUMBER else "+65XXXXXXXXX",
                }
                active_codes = db.get_active_invite_codes()
                flash(f"✅ Invite code {code} generated for {nickname}!", "success")

    return render_template(
        "onboarding.html",
        families=families,
        active_codes=active_codes,
        generated=generated,
    )


@login_required
@app.route("/onboarding/revoke/<code>", methods=["POST"])
def revoke_code(code):
    db.revoke_invite_code(code)
    flash(f"Code {code} revoked.", "info")
    return redirect(url_for("onboarding"))


# ── Shop Mappings ─────────────────────────────────────────────────────────────

@login_required
@app.route("/shop-mappings", methods=["GET", "POST"])
def shop_mappings():
    if request.method == "POST":
        shop = request.form.get("shop_name", "").strip()
        cat  = request.form.get("category", "Other")
        fid  = request.form.get("family_id") or None
        if fid:
            fid = int(fid)
        if shop:
            db.add_shop_mapping(shop, cat, family_id=fid)
            flash(f"✅ Mapped '{shop}' → {cat}", "success")
        return redirect(url_for("shop_mappings"))

    mappings = db.get_all_shop_mappings()
    families = db.get_all_families()
    cats     = db.get_all_categories()
    return render_template("shop_mappings.html", mappings=mappings,
                           families=families, categories=cats)


@login_required
@app.route("/shop-mappings/delete/<int:mapping_id>", methods=["POST"])
def delete_shop_mapping(mapping_id):
    db.delete_shop_mapping(mapping_id)
    flash("Mapping deleted.", "info")
    return redirect(url_for("shop_mappings"))


# ── Unknown Contacts ──────────────────────────────────────────────────────────

@login_required
@app.route("/unknown-contacts")
def unknown_contacts():
    contacts = db.get_unknown_contacts()
    alerts   = db.get_security_alerts()
    return render_template("unknown_contacts.html", contacts=contacts, alerts=alerts)


# ── Temp image serving (public) ───────────────────────────────────────────────

_TEMP_IMG_DIR = "/tmp"


@app.route("/img/<uid>")
def serve_temp_image(uid):
    """
    Serve a temporarily stored receipt image over plain HTTP.

    Docker Model Runner fetches this URL from the Mac host because its
    llama.cpp build has no SSL and cannot handle data: URIs.
    Files are cleaned up after the vision call. The UID is a UUID4, so it
    cannot be guessed.
    """
    matches = _glob.glob(os.path.join(_TEMP_IMG_DIR, f"receipt_{uid}.*"))
    if not matches:
        return "Not found", 404
    path = matches[0]
    ext  = os.path.splitext(path)[1].lower()
    ct   = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    with open(path, "rb") as f:
        data = f.read()
    return Response(data, content_type=ct, headers={"Cache-Control": "no-store"})
