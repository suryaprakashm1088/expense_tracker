import os
import re
import json
import uuid
import random
import string
import base64
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, Response, abort, session,
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

import database as db

# ── Config ────────────────────────────────────────────────────────────────────
TWILIO_SID          = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_NUMBER       = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
DASHBOARD_URL       = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:5001")

app = Flask(__name__)

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    print("WARNING: SECRET_KEY not set in .env — using a random key. Sessions will reset on restart.")
app.secret_key = _secret_key

# Initialise DB on startup
db.init_db()


# ── CSRF Protection ───────────────────────────────────────────────────────────

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = generate_csrf_token

# Endpoints that must NOT be CSRF-checked (third-party webhooks + login + health)
_CSRF_EXEMPT = {'whatsapp_webhook', 'static', 'login', 'health'}


@app.before_request
def csrf_protect():
    if request.method == "POST" and request.endpoint not in _CSRF_EXEMPT:
        token = session.get('_csrf_token')
        form_token = request.form.get('_csrf_token')
        if not token or not form_token or not secrets.compare_digest(token, form_token):
            abort(403)


_PUBLIC_ENDPOINTS = {'login', 'logout', 'whatsapp_webhook', 'static', 'health'}


@app.before_request
def require_login():
    if request.endpoint and request.endpoint not in _PUBLIC_ENDPOINTS:
        if not session.get('admin_logged_in'):
            return redirect(url_for('login', next=request.path))
        if session.get('must_change_password') and request.endpoint != 'change_credentials':
            flash("Please change your default username and password before continuing.", "warning")
            return redirect(url_for('change_credentials'))


# ── Security Headers ──────────────────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # CSP: allow CDN bundles and inline styles/scripts needed by Bootstrap + Chart.js
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


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    """Decorator that ensures the admin is logged in before accessing a route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login', next=request.url))
        # Force credential change on first login before going anywhere else
        if session.get('must_change_password') and request.endpoint != 'change_credentials':
            flash("Please change your default username and password before continuing.", "warning")
            return redirect(url_for('change_credentials'))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get('admin_logged_in'):
        return redirect(url_for('index'))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        creds = db.get_admin_credentials()
        if creds and username == creds["username"] and check_password_hash(creds["password_hash"], password):
            session['admin_logged_in'] = True
            session['admin_username'] = creds["username"]
            session['must_change_password'] = bool(creds["must_change_password"])
            if creds["must_change_password"]:
                flash("Welcome! Please set a new username and password to continue.", "info")
                return redirect(url_for('change_credentials'))
            next_url = request.args.get('next')
            return redirect(next_url if next_url and next_url.startswith('/') else url_for('index'))
        else:
            error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))


@app.route("/change-credentials", methods=["GET", "POST"])
@login_required
def change_credentials():
    if request.method == "POST":
        new_username = request.form.get("new_username", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        creds = db.get_admin_credentials()

        # Validations
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
            session['admin_username'] = new_username
            session['must_change_password'] = False
            flash("✅ Credentials updated successfully!", "success")
            return redirect(url_for('index'))

    return render_template("change_credentials.html")


# ── Lazy clients ──────────────────────────────────────────────────────────────

def get_twilio_client():
    if not TWILIO_SID or not TWILIO_AUTH_TOKEN:
        return None
    try:
        from twilio.rest import Client
        return Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
    except Exception:
        return None


def get_anthropic_client():
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        return None


# ── Month names ───────────────────────────────────────────────────────────────
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# ── Category choices for bot (short name → DB name) ───────────────────────────
CATEGORY_CHOICES = [
    ("Groceries",    "Food & Groceries"),
    ("Food",         "Outside Food"),
    ("Transport",    "Transport"),
    ("Personal Care","Personal Care"),
    ("Utilities",    "Bills & Utilities"),
    ("Shopping",     "Shopping"),
    ("Healthcare",   "Healthcare"),
    ("Education",    "Education"),
    ("Other",        "Other"),
]

# ── Keyword → DB category ─────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    # Food & Groceries
    "groceries":    "Food & Groceries",
    "grocery":      "Food & Groceries",
    "supermarket":  "Food & Groceries",
    "ntuc":         "Food & Groceries",
    "fairprice":    "Food & Groceries",
    "vegetables":   "Food & Groceries",
    "fruits":       "Food & Groceries",
    # Outside Food
    "food":         "Outside Food",
    "outside":      "Outside Food",
    "restaurant":   "Outside Food",
    "eating":       "Outside Food",
    "lunch":        "Outside Food",
    "dinner":       "Outside Food",
    "breakfast":    "Outside Food",
    "supper":       "Outside Food",
    "hawker":       "Outside Food",
    "kopitiam":     "Outside Food",
    "coffee":       "Outside Food",
    "tea":          "Outside Food",
    # Transport
    "transport":    "Transport",
    "taxi":         "Transport",
    "grab":         "Transport",
    "mrt":          "Transport",
    "bus":          "Transport",
    "train":        "Transport",
    "commute":      "Transport",
    "petrol":       "Transport",
    "fuel":         "Transport",
    "parking":      "Transport",
    "ezlink":       "Transport",
    "ez-link":      "Transport",
    # Personal Care
    "personal":     "Personal Care",
    "toiletries":   "Personal Care",
    "beauty":       "Personal Care",
    "skincare":     "Personal Care",
    "haircut":      "Personal Care",
    "salon":        "Personal Care",
    # Bills & Utilities
    "bills":        "Bills & Utilities",
    "bill":         "Bills & Utilities",
    "electricity":  "Bills & Utilities",
    "utilities":    "Bills & Utilities",
    "utility":      "Bills & Utilities",
    "internet":     "Bills & Utilities",
    "wifi":         "Bills & Utilities",
    "mobile":       "Bills & Utilities",
    "phone":        "Bills & Utilities",
    "singtel":      "Bills & Utilities",
    "starhub":      "Bills & Utilities",
    "rent":         "Bills & Utilities",
    "conservancy":  "Bills & Utilities",
    # Shopping
    "shopping":     "Shopping",
    "clothes":      "Shopping",
    "clothing":     "Shopping",
    "shopee":       "Shopping",
    "lazada":       "Shopping",
    "amazon":       "Shopping",
    "ikea":         "Shopping",
    # Healthcare
    "health":       "Healthcare",
    "healthcare":   "Healthcare",
    "doctor":       "Healthcare",
    "clinic":       "Healthcare",
    "hospital":     "Healthcare",
    "pharmacy":     "Healthcare",
    "medicine":     "Healthcare",
    "dental":       "Healthcare",
    "medical":      "Healthcare",
    # Education
    "education":    "Education",
    "school":       "Education",
    "tuition":      "Education",
    "course":       "Education",
    "books":        "Education",
    # Entertainment
    "entertainment":"Entertainment",
    "movie":        "Entertainment",
    "netflix":      "Entertainment",
    "spotify":      "Entertainment",
    "games":        "Entertainment",
    "game":         "Entertainment",
}


# ─────────────────────────────────────────────────────────────────────────────
# Invite Code Generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_code(length=8):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def parse_expiry(expiry_str):
    """Parse '1hr', '24hrs', '7days' into a datetime."""
    expiry_str = str(expiry_str).lower().strip()
    now = datetime.now()
    if "7day" in expiry_str or expiry_str == "7d":
        return now + timedelta(days=7)
    if "1hr" in expiry_str or expiry_str == "1h":
        return now + timedelta(hours=1)
    # default 24hrs
    return now + timedelta(hours=24)


# ─────────────────────────────────────────────────────────────────────────────
# Expense Parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_expense_message(body, family_id=None):
    """
    Parses a WhatsApp message into expense components.
    Returns dict with title, amount, category, shop_name, label — or None.

    Accepted patterns:
      "FairPrice 45.50"
      "grab 12"
      "spent 50 food"
      "kopitiam 4.50 lunch"
      "45.50 fairprice weekly groceries"
      "transport 8 mrt to work"
      "doctor 35 polyclinic"
      "200 shopping daiso stuff"
    """
    text = body.strip()

    # Strip leading 'add' keyword
    if text.lower().startswith("add "):
        text = text[4:].strip()

    # Strip S$ / $ prefixes anywhere
    text_clean = re.sub(r"S\$|s\$", "", text)
    text_clean = text_clean.replace("$", "")

    # 1. Extract amount
    amount = None
    amount_pattern = re.compile(r'\b(\d+(?:\.\d{1,2})?)\b')
    for match in amount_pattern.finditer(text_clean):
        val = float(match.group(1))
        if val > 0:
            amount = val
            # Remove the matched amount from text_clean for further parsing
            text_clean = (text_clean[:match.start()] + text_clean[match.end():]).strip()
            break

    if amount is None:
        return None

    # 2. Check shop_mappings
    shop_name, category = db.find_shop_in_text(text_clean, family_id=family_id)

    # 3. Check category keywords if no shop match
    if not category:
        for token in text_clean.lower().split():
            token_clean = token.strip(",.!?")
            if token_clean in CATEGORY_KEYWORDS:
                category = CATEGORY_KEYWORDS[token_clean]
                break

    # 4. Build label (remaining words that are not the shop / category keyword)
    remaining_words = []
    for word in text_clean.split():
        w = word.lower().strip(",.!?")
        if shop_name and w in shop_name.lower():
            continue
        if w in CATEGORY_KEYWORDS:
            continue
        if w in ("spent", "on", "at", "for", "the", "a", "an"):
            continue
        remaining_words.append(word)
    label = " ".join(remaining_words).strip() or None

    # 5. Title: prefer shop_name, else category, else first remaining word
    title = shop_name.title() if shop_name else (label or category or "Expense")

    return {
        "title":     title,
        "amount":    amount,
        "category":  category or "Other",
        "shop_name": shop_name,
        "label":     label,
    }


def get_category_from_ai(text):
    """Ask Claude Haiku to categorize the expense. Returns DB category name or None."""
    ai = get_anthropic_client()
    if not ai:
        return None
    categories = [c[1] for c in CATEGORY_CHOICES]
    try:
        response = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{
                "role": "user",
                "content": (
                    f"Given the expense description '{text}', which category fits best? "
                    f"Options: {', '.join(categories)}. "
                    "Reply with ONLY the exact category name from the list."
                ),
            }],
        )
        result = response.content[0].text.strip()
        if result in categories:
            return result
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp TwiML helper
# ─────────────────────────────────────────────────────────────────────────────

def twiml(msg):
    safe = (msg
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'
    return Response(xml, mimetype="text/xml")


GENERIC_ERROR = "Sorry, we are unable to process your message."
GENERIC_CODE_ERROR = "Sorry, we are unable to process your request."


# ─────────────────────────────────────────────────────────────────────────────
# Invite Code JOIN flow
# ─────────────────────────────────────────────────────────────────────────────

def handle_join_code(sender, sender_name, code):
    code = code.strip().upper()
    invite = db.get_invite_code(code)

    if not invite:
        db.log_unknown_contact(sender, f"JOIN {code}", "invalid_code", code)
        return GENERIC_CODE_ERROR

    now = datetime.now()

    # Check expiry
    if invite.get("expires_at"):
        try:
            expires = datetime.fromisoformat(invite["expires_at"])
            if expires < now:
                db.log_unknown_contact(sender, f"JOIN {code}", "expired_code", code)
                return GENERIC_CODE_ERROR
        except Exception:
            pass

    # Check usage
    if invite.get("is_used") and invite.get("max_uses", 1) <= 1:
        db.log_unknown_contact(sender, f"JOIN {code}", "used_code", code)
        return GENERIC_CODE_ERROR

    # Already a member?
    existing = db.get_member_by_number(sender)
    if existing:
        return GENERIC_CODE_ERROR

    # Create member
    nickname = invite.get("nickname") or sender_name
    db.add_member(
        name=nickname,
        whatsapp_number=sender,
        is_approved=1,
        family_id=invite.get("family_id"),
        is_admin=invite.get("is_admin", 0),
        nickname=nickname,
        joined_at=now.isoformat(),
        added_by=invite.get("created_by"),
    )
    db.use_invite_code(code, sender)

    family = db.get_family_by_id(invite.get("family_id"))
    family_name = family["name"] if family else "the expense tracker"

    # Notify admin
    admin_phone = invite.get("created_by")
    twilio_cl = get_twilio_client()
    if admin_phone and twilio_cl and TWILIO_NUMBER:
        try:
            twilio_cl.messages.create(
                from_=TWILIO_NUMBER,
                to=admin_phone,
                body=(
                    f"✅ {nickname} ({sender.replace('whatsapp:', '')}) "
                    f"has joined {family_name} using code {code}."
                ),
            )
        except Exception:
            pass

    return (
        f"👋 Welcome {nickname}!\n"
        f"You have joined {family_name} expense tracker.\n"
        f"Send 'help' to get started. 🎉"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Receipt Photo Handling
# ─────────────────────────────────────────────────────────────────────────────

def handle_receipt_photo(media_url, sender, member):
    """Download receipt image, send to Claude Vision, return bot reply."""
    import requests as http_req

    # Download image
    try:
        resp = http_req.get(media_url, auth=(TWILIO_SID, TWILIO_AUTH_TOKEN), timeout=15)
        resp.raise_for_status()
        image_b64 = base64.standard_b64encode(resp.content).decode("utf-8")
        media_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    except Exception:
        return "Could not download the image. Please try again."

    ai = get_anthropic_client()
    if not ai:
        return "AI service not configured. Please type your expense manually."

    prompt = (
        "Extract all expenses from this receipt. "
        "Return ONLY valid JSON, no other text:\n"
        '{"store": "string", "date": "YYYY-MM-DD or null", "receipt_total": 0.0, '
        '"subdivisions": [{"name": "string", "amount": 0.0, '
        '"category": "one of [Food & Groceries, Outside Food, Transport, '
        'Personal Care, Bills & Utilities, Shopping, Healthcare, Education, Other]", '
        '"label": "short description or null"}]}\n'
        'If not a receipt return: {"error": "not a receipt"}\n'
        'If unclear return: {"error": "unclear receipt"}'
    )

    try:
        response = ai.messages.create(
            model="claude-opus-4-6",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "Could not read receipt data. Please type your expense manually."
    except Exception:
        return "AI service error. Please type your expense manually."

    if "error" in data:
        if data["error"] == "not a receipt":
            return (
                "This does not look like a receipt. "
                "Please send a clearer photo or type your expense manually."
            )
        return (
            "Receipt is hard to read. Please retake in better lighting "
            "or type expenses manually."
        )

    subdivisions = data.get("subdivisions", [])
    if not subdivisions:
        return "No items found in receipt. Please type your expense manually."

    store = data.get("store", "Unknown Store")
    date = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    total = data.get("receipt_total") or sum(s.get("amount", 0) for s in subdivisions)

    # Save pending state
    pending_data = {
        "type": "receipt",
        "store": store,
        "date": date,
        "total": total,
        "subdivisions": subdivisions,
        "family_id": member.get("family_id"),
    }
    db.save_pending_state(sender, pending_data)

    # Format confirmation message
    lines = [f"🧾 {store}", f"📅 {date}", ""]
    for i, item in enumerate(subdivisions, 1):
        amt = item.get("amount", 0)
        name = item.get("name", "Item")
        cat = item.get("category", "Other")
        lines.append(f"{i}. {name:<22} S${amt:.2f}")
        lines.append(f"   📂 {cat}")
    lines.append("─" * 32)
    lines.append(f"💰 Total: S${total:.2f}")
    lines.append("")
    lines.append("Reply YES to save all")
    lines.append("Reply NO to cancel")
    lines.append("Reply EDIT to change categories")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Pending State Handling
# ─────────────────────────────────────────────────────────────────────────────

def handle_pending_response(body, sender, member):
    """Handle YES/NO/EDIT/number responses to pending bot states."""
    text = body.strip().lower()
    pending = db.get_pending_state(sender)
    if not pending:
        return None

    ptype = pending.get("type")

    # ── Pending receipt confirmation ──────────────────────────────────────────
    if ptype == "receipt":
        if text == "yes":
            store = pending.get("store", "Receipt")
            date = pending.get("date", datetime.now().strftime("%Y-%m-%d"))
            subdivisions = pending.get("subdivisions", [])
            family_id = pending.get("family_id")
            member_name = member.get("nickname") or member.get("name", "Member")
            receipt_id = str(uuid.uuid4())
            saved = 0
            receipt_items = []
            for item in subdivisions:
                amt = item.get("amount", 0)
                name = item.get("name", store)
                cat = item.get("category", "Other")
                label = item.get("label")
                eid = db.add_expense(
                    title=name,
                    amount=amt,
                    category=cat,
                    date=date,
                    note=f"Receipt from {store}",
                    added_by=member_name,
                    shop_name=store,
                    label=label,
                    receipt_id=receipt_id,
                    family_id=family_id,
                )
                receipt_items.append({"expense_id": eid, "name": name, "amount": amt, "category": cat, "label": label})
                saved += 1
            db.save_receipt_items(receipt_id, receipt_items, family_id=family_id)
            db.clear_pending_state(sender)
            total = sum(i.get("amount", 0) for i in subdivisions)
            return f"✅ Saved {saved} items from {store}\nTotal: S${total:.2f}"

        if text == "no":
            db.clear_pending_state(sender)
            return "❌ Receipt cancelled."

        if text == "edit":
            db.clear_pending_state(sender)
            return (
                "Send corrections like:\n"
                "'1 Transport' to change item 1 to Transport\n"
                "'3 delete' to remove item 3\n\n"
                "Or send the receipt photo again after correcting."
            )

        # Try to parse edit command like "1 Transport" or "2 Groceries"
        edit_match = re.match(r"^(\d+)\s+(.+)$", text.strip())
        if edit_match:
            idx = int(edit_match.group(1)) - 1
            new_cat_input = edit_match.group(2).strip()
            subdivisions = pending.get("subdivisions", [])
            if 0 <= idx < len(subdivisions):
                if new_cat_input == "delete":
                    subdivisions.pop(idx)
                    pending["subdivisions"] = subdivisions
                    db.save_pending_state(sender, pending)
                    return f"Removed item {idx+1}. Send YES to save remaining {len(subdivisions)} items."
                # Map short name to full category
                matched_cat = None
                for short, full in CATEGORY_CHOICES:
                    if short.lower() == new_cat_input.lower() or full.lower() == new_cat_input.lower():
                        matched_cat = full
                        break
                if matched_cat:
                    subdivisions[idx]["category"] = matched_cat
                    pending["subdivisions"] = subdivisions
                    db.save_pending_state(sender, pending)
                    return f"Updated item {idx+1} to {matched_cat}. Send YES to save."
        return "Send YES to save, NO to cancel, or EDIT to change categories."

    # ── Pending category ask ──────────────────────────────────────────────────
    if ptype == "category_ask":
        try:
            choice = int(text.strip())
            if 1 <= choice <= len(CATEGORY_CHOICES):
                short_name, full_cat = CATEGORY_CHOICES[choice - 1]
                parsed = pending.get("parsed", {})
                shop = pending.get("shop") or parsed.get("title")
                family_id = pending.get("family_id")
                # Save shop → category mapping for future
                if shop:
                    db.add_shop_mapping(shop.lower(), full_cat, family_id=family_id)
                # Save expense
                parsed["category"] = full_cat
                member_name = member.get("nickname") or member.get("name", "Member")
                today = datetime.now().strftime("%Y-%m-%d")
                db.add_expense(
                    title=parsed.get("title", shop or "Expense"),
                    amount=parsed.get("amount", 0),
                    category=full_cat,
                    date=today,
                    note=f"via WhatsApp by {member_name}",
                    added_by=member_name,
                    shop_name=parsed.get("shop_name"),
                    label=parsed.get("label"),
                    family_id=family_id,
                )
                db.clear_pending_state(sender)
                return (
                    f"✅ Saved!\n"
                    f"📝 {parsed.get('title', 'Expense')}\n"
                    f"💸 S${parsed.get('amount', 0):,.2f}\n"
                    f"🏷️ {full_cat}\n"
                    f"📅 {today}\n"
                    f"_(Also remembered: {shop} → {full_cat})_"
                )
        except ValueError:
            pass
        return (
            "Please reply with a number:\n"
            + "\n".join(f"{i+1}. {s}" for i, (s, _) in enumerate(CATEGORY_CHOICES))
        )

    # ── Pending duplicate confirm ─────────────────────────────────────────────
    if ptype == "duplicate_confirm":
        orig_msg = pending.get("original_message", "")
        if body.strip().lower() == orig_msg.lower():
            parsed = pending.get("parsed", {})
            member_name = member.get("nickname") or member.get("name", "Member")
            today = datetime.now().strftime("%Y-%m-%d")
            family_id = member.get("family_id")
            db.add_expense(
                title=parsed.get("title", "Expense"),
                amount=parsed.get("amount", 0),
                category=parsed.get("category", "Other"),
                date=today,
                note=f"via WhatsApp by {member_name}",
                added_by=member_name,
                shop_name=parsed.get("shop_name"),
                label=parsed.get("label"),
                family_id=family_id,
            )
            db.clear_pending_state(sender)
            return (
                f"✅ Saved (duplicate confirmed)!\n"
                f"💸 S${parsed.get('amount',0):,.2f} · {parsed.get('category','Other')}"
            )
        db.clear_pending_state(sender)
        return "Duplicate cancelled. Send a new expense to continue."

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main Bot Reply Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_whatsapp_reply(body, sender, member):
    text = body.strip().lower()
    now = datetime.now()
    family_id = member.get("family_id")
    is_admin = member.get("is_admin", 0)
    member_name = member.get("nickname") or member.get("name", "Member")
    today_str = now.strftime("%Y-%m-%d")

    # ── HELP ──────────────────────────────────────────────────────────────────
    if text in ("help", "hi", "hello", "start", "commands"):
        admin_section = ""
        if is_admin:
            admin_section = (
                "\n\n👑 *Admin Commands:*\n"
                "   `invite John` – generate invite code\n"
                "   `invite John 7days` – code valid 7 days\n"
                "   `codes` – list active codes\n"
                "   `revoke CODE` – invalidate a code\n"
                "   `members` – list family members\n"
                "   `remove +6591234567` – deactivate member\n"
                "   `map shop to category` – add shop mapping\n"
                "   `report` – full monthly report"
            )
        return (
            f"👋 Hi {member_name}! I'm your *Family Expense Bot*.\n\n"
            "💡 *Commands:*\n\n"
            "➕ *Add expense:*\n"
            "   `FairPrice 45.50`\n"
            "   `Grab 12 airport`\n"
            "   `spent 50 food lunch`\n\n"
            "📸 *Receipt:* Send any receipt photo\n\n"
            "📊 *Summaries:*\n"
            "   `today` `monthly` `mine` `week`\n\n"
            "↩️ *Undo last:* `undo`\n"
            "📋 *Last 5:* `last`"
            + admin_section
        )

    # ── UNDO ──────────────────────────────────────────────────────────────────
    if text == "undo":
        last = db.get_last_expense_by_member(member_name)
        if last:
            db.delete_expense(last["id"])
            return (
                f"↩️ Deleted last entry:\n"
                f"  {last['title']} — S${last['amount']:,.2f}\n"
                f"  [{last['category']}] · {last['date']}"
            )
        return "Nothing to undo."

    # ── LAST ──────────────────────────────────────────────────────────────────
    if text in ("last", "recent", "list"):
        exps = db.get_expenses_by_member(member_name, limit=5)
        if not exps:
            return "📋 No recent expenses found."
        lines = ["📋 *Your last 5 expenses:*\n"]
        for e in exps:
            shop = f" · {e['shop_name']}" if e.get("shop_name") else ""
            lines.append(f"• {e['date']} {e['title']}{shop} — S${e['amount']:,.2f} [{e['category']}]")
        return "\n".join(lines)

    # ── TODAY / SUMMARY ───────────────────────────────────────────────────────
    if text in ("today", "summary"):
        if family_id:
            exps = db.get_expenses_by_family_and_date(family_id, today_str)
        else:
            exps = [e for e in db.get_all_expenses(month=now.month, year=now.year)
                    if e["date"] == today_str]
        if not exps:
            return f"📅 No expenses logged today ({today_str})."

        family = db.get_family_by_id(family_id)
        fam_name = family["name"] if family else "Family"
        total = sum(e["amount"] for e in exps)

        # By shop
        shop_totals = {}
        for e in exps:
            s = e.get("shop_name") or e.get("title") or "Other"
            shop_totals[s] = shop_totals.get(s, 0) + e["amount"]

        # By category
        cat_totals = {}
        for e in exps:
            c = e["category"]
            cat_totals[c] = cat_totals.get(c, 0) + e["amount"]

        # My share
        my_total = sum(e["amount"] for e in exps if e.get("added_by") == member_name)
        member_count = len({e.get("added_by") for e in exps if e.get("added_by")}) or 1

        lines = [f"📊 *{fam_name} — {today_str}*\n"]
        if shop_totals:
            lines.append("🏪 *By Shop:*")
            for s, amt in sorted(shop_totals.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  {s:<20} S${amt:,.2f}")
            lines.append("")
        lines.append("📂 *By Category:*")
        for c, amt in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = round(amt / total * 100) if total else 0
            lines.append(f"  {c:<18} S${amt:,.2f} ({pct}%)")
        lines.append(f"\n💰 Total: S${total:,.2f}")
        lines.append(f"👤 Your spend: S${my_total:,.2f}")
        return "\n".join(lines)

    # ── MONTHLY ───────────────────────────────────────────────────────────────
    if text in ("monthly", "month"):
        data = db.get_monthly_summary(now.month, now.year, family_id=family_id)
        total = sum(r["total"] for r in data)
        if not data:
            return f"📊 No expenses for {now.strftime('%B %Y')} yet."

        # Compare with last month
        last_month = now.month - 1 or 12
        last_year = now.year if now.month > 1 else now.year - 1
        last_data = db.get_monthly_summary(last_month, last_year, family_id=family_id)
        last_total = sum(r["total"] for r in last_data)
        diff = total - last_total
        diff_str = f"↑ S${diff:,.0f} vs last month" if diff > 0 else f"↓ S${abs(diff):,.0f} vs last month"

        lines = [f"📊 *{now.strftime('%B %Y')} Summary*\n"]
        for r in data:
            pct = round(r["total"] / total * 100) if total else 0
            lines.append(f"  {r['category']:<18} S${r['total']:,.0f} ({pct}%)")
        lines.append(f"\n💰 *Total: S${total:,.0f}*")
        lines.append(f"📈 {diff_str}")
        return "\n".join(lines)

    # ── MINE / MY ─────────────────────────────────────────────────────────────
    if text in ("my", "mine", "me"):
        exps = db.get_expenses_by_member(member_name, limit=10)
        today_exps = [e for e in exps if e["date"] == today_str]
        if not today_exps:
            return f"📋 No expenses by you today ({today_str})."
        total = sum(e["amount"] for e in today_exps)
        lines = [f"📋 *Your expenses today:*\n"]
        for e in today_exps:
            lines.append(f"• {e['title']} — S${e['amount']:,.2f} [{e['category']}]")
        lines.append(f"\n💰 Your total: S${total:,.2f}")
        return "\n".join(lines)

    # ── WEEK ──────────────────────────────────────────────────────────────────
    if text == "week":
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        conn_rows = db.get_all_expenses(family_id=family_id)
        week_exps = [e for e in conn_rows if e["date"] >= week_ago]
        if not week_exps:
            return "📅 No expenses in the last 7 days."
        total = sum(e["amount"] for e in week_exps)
        cat_totals = {}
        for e in week_exps:
            cat_totals[e["category"]] = cat_totals.get(e["category"], 0) + e["amount"]
        lines = ["📊 *Last 7 Days*\n"]
        for c, amt in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = round(amt / total * 100) if total else 0
            lines.append(f"  {c:<18} S${amt:,.0f} ({pct}%)")
        lines.append(f"\n💰 Total: S${total:,.0f}")
        return "\n".join(lines)

    # ── TOTAL ─────────────────────────────────────────────────────────────────
    if text in ("total", "balance", "spent"):
        data = db.get_monthly_summary(now.month, now.year, family_id=family_id)
        total = sum(r["total"] for r in data)
        return f"💰 Total spent in *{now.strftime('%B %Y')}*: S${total:,.0f}"

    # ── ADMIN COMMANDS ────────────────────────────────────────────────────────
    if is_admin:
        # invite John / invite John 7days
        if text.startswith("invite "):
            parts = body.strip().split()
            nickname = parts[1] if len(parts) > 1 else "Member"
            expiry_str = parts[2] if len(parts) > 2 else "24hrs"
            expires_at = parse_expiry(expiry_str)
            code = generate_code()
            while db.get_invite_code(code):
                code = generate_code()
            db.add_invite_code(
                code=code,
                family_id=family_id,
                created_by=sender,
                expires_at=expires_at,
                nickname=nickname,
                is_admin=0,
            )
            family = db.get_family_by_id(family_id)
            fam_name = family["name"] if family else "Family"
            exp_label = expiry_str if expiry_str != "24hrs" else "24 hours"
            return (
                f"Code for {nickname}: *{code}*\n"
                f"Family: {fam_name}\n"
                f"Expires: {exp_label}\n\n"
                f"Tell {nickname} to send:\n"
                f"*JOIN {code}*"
            )

        # codes
        if text == "codes":
            codes = db.get_active_invite_codes(family_id=family_id)
            active = [c for c in codes if not c.get("is_used")]
            if not active:
                return "No active unused invite codes."
            lines = ["📋 *Active Invite Codes:*\n"]
            for c in active[:10]:
                lines.append(f"• {c['code']} → {c.get('nickname','?')} (expires: {c.get('expires_at','N/A')[:10]})")
            return "\n".join(lines)

        # revoke CODE
        if text.startswith("revoke "):
            code_to_revoke = body.strip().split()[-1].upper()
            db.revoke_invite_code(code_to_revoke)
            return f"✅ Code {code_to_revoke} has been revoked."

        # members
        if text == "members":
            members_list = db.get_all_members()
            if family_id:
                members_list = [m for m in members_list if m.get("family_id") == family_id]
            if not members_list:
                return "No members found."
            lines = [f"👥 *Family Members ({len(members_list)}):*\n"]
            for m in members_list:
                status = "✅" if m["is_approved"] else "🚫"
                admin_tag = " 👑" if m.get("is_admin") else ""
                lines.append(f"{status} {m.get('nickname') or m['name']}{admin_tag} — {m['whatsapp_number'].replace('whatsapp:','')}")
            return "\n".join(lines)

        # remove +6591234567
        if text.startswith("remove "):
            phone_raw = body.strip().split()[-1]
            if not phone_raw.startswith("whatsapp:"):
                phone_raw = "whatsapp:+" + phone_raw.lstrip("+")
            db.deactivate_member_by_phone(phone_raw)
            return f"✅ Member {phone_raw.replace('whatsapp:','')} deactivated."

        # map shop to category
        map_match = re.match(r"^map\s+(.+?)\s+to\s+(.+)$", text.strip())
        if map_match:
            shop_n = map_match.group(1).strip()
            cat_n = map_match.group(2).strip().title()
            db.add_shop_mapping(shop_n, cat_n, family_id=family_id)
            return f"✅ Mapped '{shop_n}' → {cat_n}"

        # report
        if text == "report":
            data = db.get_monthly_summary(now.month, now.year, family_id=family_id)
            total = sum(r["total"] for r in data)
            shop_data = db.get_shop_summary(now.month, now.year, family_id=family_id)
            if not data:
                return f"📊 No data for {now.strftime('%B %Y')}."
            lines = [f"📊 *{now.strftime('%B %Y')} Family Report*\n"]
            lines.append(f"💰 Total: S${total:,.2f}\n")
            lines.append("📂 *Categories:*")
            for r in data:
                pct = round(r["total"] / total * 100) if total else 0
                lines.append(f"  {r['category']:<18} S${r['total']:,.2f} ({pct}%)")
            if shop_data:
                lines.append("\n🏪 *Top Shops:*")
                for s in shop_data[:5]:
                    if s.get("shop_name"):
                        lines.append(f"  {s['shop_name']:<20} S${s['total']:,.2f}")
            return "\n".join(lines)

    # ── ADD EXPENSE ───────────────────────────────────────────────────────────
    parsed = parse_expense_message(body, family_id=family_id)
    if parsed:
        today = now.strftime("%Y-%m-%d")

        # Duplicate detection
        if db.check_recent_duplicate(member_name, parsed["amount"], parsed["category"]):
            pending_data = {
                "type": "duplicate_confirm",
                "original_message": body.strip().lower(),
                "parsed": parsed,
                "family_id": family_id,
            }
            db.save_pending_state(sender, pending_data)
            return (
                f"⚠️ Looks like a duplicate of your last entry "
                f"(S${parsed['amount']:,.2f} {parsed['category']}).\n"
                f"Send the same message again to confirm."
            )

        # Category unknown → ask AI first, then user
        if parsed["category"] == "Other" and not parsed.get("shop_name"):
            ai_cat = get_category_from_ai(body)
            if ai_cat and ai_cat != "Other":
                parsed["category"] = ai_cat
            else:
                # Ask user
                pending_data = {
                    "type": "category_ask",
                    "shop": parsed.get("title") or body.strip(),
                    "parsed": parsed,
                    "family_id": family_id,
                }
                db.save_pending_state(sender, pending_data)
                cat_lines = "\n".join(
                    f"{i+1}. {s}" for i, (s, _) in enumerate(CATEGORY_CHOICES)
                )
                return (
                    f"What category for '{parsed.get('title') or body.strip()}'?\n\n"
                    f"{cat_lines}\n\n"
                    "Reply with number."
                )

        db.add_expense(
            title=parsed["title"],
            amount=parsed["amount"],
            category=parsed["category"],
            date=today,
            note=f"via WhatsApp by {member_name}",
            added_by=member_name,
            shop_name=parsed.get("shop_name"),
            label=parsed.get("label"),
            family_id=family_id,
        )
        shop_line = f"\n🏪 {parsed['shop_name']}" if parsed.get("shop_name") else ""
        label_line = f"\n📝 {parsed['label']}" if parsed.get("label") else ""
        return (
            f"✅ *Expense Added!*\n\n"
            f"💸 S${parsed['amount']:,.2f}\n"
            f"🏷️ {parsed['category']}"
            f"{shop_line}"
            f"{label_line}\n"
            f"📅 {today}\n"
            f"_Added by {member_name}_"
        )

    # ── UNKNOWN ───────────────────────────────────────────────────────────────
    return (
        "❓ I didn't understand that.\n\n"
        "Send *help* to see all commands.\n"
        "Quick example: `FairPrice 45.50`"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Daily AI Summary (APScheduler)
# ─────────────────────────────────────────────────────────────────────────────

def send_daily_summary():
    """Sends AI-generated daily summary to all family members. Runs at 20:00 SGT."""
    ai = get_anthropic_client()
    twilio_cl = get_twilio_client()
    if not ai or not twilio_cl or not TWILIO_NUMBER:
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    families = db.get_all_families()

    for family in families:
        fid = family["id"]
        exps = db.get_expenses_by_family_and_date(fid, today_str)
        if not exps:
            continue

        total = sum(e["amount"] for e in exps)
        expenses_text = "\n".join(
            f"- {e['title']} S${e['amount']:.2f} ({e['category']})"
            for e in exps
        )

        try:
            response = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Here is today's expense data for a Singapore family in SGD:\n"
                        f"Family: {family['name']}\n"
                        f"Date: {today_str}\n"
                        f"Total: S${total:.2f}\n\n"
                        f"Expenses:\n{expenses_text}\n\n"
                        "Write a friendly WhatsApp summary:\n"
                        "- Total spent in SGD\n"
                        "- Top 3 spending categories\n"
                        "- Notable shops visited\n"
                        "- One practical money saving tip relevant to Singapore context\n"
                        "- Under 10 lines\n"
                        "- Use emojis\n"
                        "- End with encouragement"
                    ),
                }],
            )
            summary = response.content[0].text.strip()
        except Exception:
            continue

        # Send to all approved members
        members = [m for m in db.get_all_members()
                   if m.get("family_id") == fid and m.get("is_approved")]
        for m in members:
            try:
                twilio_cl.messages.create(
                    from_=TWILIO_NUMBER,
                    to=m["whatsapp_number"],
                    body=f"📊 *Daily Summary — {family['name']}*\n\n{summary}",
                )
            except Exception:
                pass


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        # 12:00 UTC = 20:00 SGT (UTC+8)
        scheduler.add_job(send_daily_summary, "cron", hour=12, minute=0)
        scheduler.start()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp Webhook
# ─────────────────────────────────────────────────────────────────────────────

def _validate_twilio_signature():
    """Returns True if request has a valid Twilio signature, or if no auth token is configured."""
    if not TWILIO_AUTH_TOKEN:
        return True  # Can't validate without token; skip for local dev
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(TWILIO_AUTH_TOKEN)
        # Rebuild URL — handle HTTPS termination by ngrok/proxy
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        url = request.url.replace('http://', f'{proto}://', 1) if proto == 'https' else request.url
        signature = request.headers.get('X-Twilio-Signature', '')
        return validator.validate(url, request.form.to_dict(), signature)
    except Exception:
        return False


@app.route("/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        return (
            "<h2>✅ WhatsApp Webhook is active.</h2>"
            "<p>This endpoint receives messages from Twilio.</p>"
        ), 200

    # Verify request is genuinely from Twilio
    if not _validate_twilio_signature():
        return Response("Forbidden", status=403)

    sender    = request.form.get("From", "")
    body      = request.form.get("Body", "").strip()
    name      = request.form.get("ProfileName", "Member")
    media_url = request.form.get("MediaUrl0", "")

    if not sender:
        return twiml(GENERIC_ERROR)

    # ── JOIN code flow (open to unknown numbers) ─────────────────────────────
    if body.upper().startswith("JOIN "):
        code = body.strip()[5:].strip()
        return twiml(handle_join_code(sender, name, code))

    # ── Verify member is registered and approved ──────────────────────────────
    member = db.get_member_by_number(sender)
    if not member or not member.get("is_approved"):
        attempt_type = "no_code" if not member else "pending"
        db.log_unknown_contact(sender, body or "[photo]", attempt_type)
        return twiml(GENERIC_ERROR)

    # ── Receipt photo ─────────────────────────────────────────────────────────
    if media_url and not body:
        return twiml(handle_receipt_photo(media_url, sender, member))

    if not body:
        return twiml(GENERIC_ERROR)

    # ── Pending state check ───────────────────────────────────────────────────
    pending_reply = handle_pending_response(body, sender, member)
    if pending_reply is not None:
        return twiml(pending_reply)

    # ── Also handle receipt photo WITH text ──────────────────────────────────
    if media_url:
        return twiml(handle_receipt_photo(media_url, sender, member))

    reply = build_whatsapp_reply(body, sender, member)
    return twiml(reply)


# ─────────────────────────────────────────────────────────────────────────────
# Health Check  (public — used by Docker HEALTHCHECK + AWS ALB + monitoring)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    """Public health endpoint. Returns 200 if app + DB are responsive."""
    try:
        db.get_all_categories()   # lightweight DB round-trip
        return jsonify({"status": "ok", "service": "expense-tracker"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@app.route("/")
def index():
    now = datetime.now()
    stats = db.get_dashboard_stats()
    monthly_data = db.get_monthly_summary(now.month, now.year)
    pie_labels = [r["category"] for r in monthly_data]
    pie_values = [r["total"] for r in monthly_data]
    monthly_totals = db.get_monthly_totals(now.year)
    bar_labels = [MONTH_NAMES[int(r["month"])] for r in monthly_totals]
    bar_values = [r["total"] for r in monthly_totals]
    recent = db.get_all_expenses(month=now.month, year=now.year)[:5]

    return render_template(
        "index.html",
        stats=stats,
        pie_labels=json.dumps(pie_labels),
        pie_values=json.dumps(pie_values),
        bar_labels=json.dumps(bar_labels),
        bar_values=json.dumps(bar_values),
        recent=recent,
        current_month=MONTH_NAMES[now.month],
        current_year=now.year,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Add / Edit / Delete Expenses
# ─────────────────────────────────────────────────────────────────────────────

def _validate_expense_form(title, amount_str, category, date_str, note, shop, label):
    """Validate expense form fields. Returns (amount_float, errors_list)."""
    errors = []
    allowed_categories = db.get_all_categories()

    if not title:
        errors.append("Title is required.")
    elif len(title) > 200:
        errors.append("Title must be 200 characters or fewer.")

    amount_val = None
    try:
        amount_val = float(amount_str)
        if amount_val <= 0:
            errors.append("Amount must be greater than 0.")
        elif amount_val > 1_000_000:
            errors.append("Amount seems too large (max S$1,000,000).")
    except (ValueError, TypeError):
        errors.append("Amount must be a valid number.")

    if category not in allowed_categories:
        errors.append("Invalid category selected.")

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        errors.append("Date must be a valid date (YYYY-MM-DD).")

    if note and len(note) > 500:
        errors.append("Note must be 500 characters or fewer.")
    if shop and len(shop) > 100:
        errors.append("Shop name must be 100 characters or fewer.")
    if label and len(label) > 100:
        errors.append("Label must be 100 characters or fewer.")

    return amount_val, errors


@login_required
@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        title    = request.form.get("title", "").strip()
        amount   = request.form.get("amount", "0").strip()
        category = request.form.get("category", "Other")
        date     = request.form.get("date", datetime.now().strftime("%Y-%m-%d"))
        note     = request.form.get("note", "").strip()
        shop     = request.form.get("shop_name", "").strip() or None
        label    = request.form.get("label", "").strip() or None

        amount_val, errors = _validate_expense_form(title, amount, category, date, note, shop, label)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "add.html",
                categories=db.get_all_categories(),
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
            )

        db.add_expense(title, amount_val, category, date, note,
                       added_by="Web", shop_name=shop, label=label)
        flash(f"✅ Expense '{title}' of S${amount_val:,.2f} added successfully!", "success")
        return redirect(url_for("index"))

    return render_template(
        "add.html",
        categories=db.get_all_categories(),
        today=datetime.now().strftime("%Y-%m-%d"),
        form={},
    )


@login_required
@app.route("/expenses")
def expenses():
    now      = datetime.now()
    month    = request.args.get("month", now.month)
    year     = request.args.get("year", now.year)
    category = request.args.get("category", "All")

    rows  = db.get_all_expenses(month=month, year=year, category=category)
    total = sum(r["amount"] for r in rows)
    available_months = db.get_available_months()

    return render_template(
        "expenses.html",
        expenses=rows,
        total=total,
        categories=["All"] + db.get_all_categories(),
        selected_month=int(month),
        selected_year=int(year),
        selected_category=category,
        month_names=MONTH_NAMES,
        available_months=available_months,
        current_year=now.year,
    )


@login_required
@app.route("/edit/<int:expense_id>", methods=["GET", "POST"])
def edit(expense_id):
    expense = db.get_expense_by_id(expense_id)
    if not expense:
        flash("Expense not found.", "danger")
        return redirect(url_for("expenses"))

    if request.method == "POST":
        title    = request.form.get("title", "").strip()
        amount   = request.form.get("amount", "0").strip()
        category = request.form.get("category", "Other")
        date     = request.form.get("date", "")
        note     = request.form.get("note", "").strip()
        shop     = request.form.get("shop_name", "").strip() or None
        label    = request.form.get("label", "").strip() or None

        amount_val, errors = _validate_expense_form(title, amount, category, date, note, shop, label)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("edit.html", expense=expense, categories=db.get_all_categories())

        db.update_expense(expense_id, title, amount_val, category, date, note,
                          shop_name=shop, label=label)
        flash("✅ Expense updated successfully!", "success")
        return redirect(url_for("expenses"))

    return render_template("edit.html", expense=expense, categories=db.get_all_categories())


@login_required
@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete(expense_id):
    db.delete_expense(expense_id)
    flash("🗑️ Expense deleted.", "info")
    return redirect(url_for("expenses"))


# ─────────────────────────────────────────────────────────────────────────────
# Monthly Summary
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@app.route("/summary")
def summary():
    now   = datetime.now()
    month = int(request.args.get("month", now.month))
    year  = int(request.args.get("year", now.year))

    category_data = db.get_monthly_summary(month, year)
    all_expenses  = db.get_all_expenses(month=month, year=year)
    grand_total   = sum(r["total"] for r in category_data)

    for row in category_data:
        row["pct"] = round(row["total"] / grand_total * 100, 1) if grand_total else 0

    pie_labels = json.dumps([r["category"] for r in category_data])
    pie_values = json.dumps([r["total"] for r in category_data])

    day_map = {}
    for exp in all_expenses:
        d = exp["date"]
        day_map[d] = day_map.get(d, 0) + exp["amount"]
    sorted_days = sorted(day_map.keys())
    line_labels = json.dumps(sorted_days)
    line_values = json.dumps([round(day_map[d], 2) for d in sorted_days])

    available = db.get_available_months()

    return render_template(
        "summary.html",
        category_data=category_data,
        grand_total=grand_total,
        selected_month=month,
        selected_year=year,
        month_name=MONTH_NAMES[month],
        pie_labels=pie_labels,
        pie_values=pie_values,
        line_labels=line_labels,
        line_values=line_values,
        available=available,
        month_names=MONTH_NAMES,
    )


@login_required
@app.route("/api/monthly-data")
def api_monthly_data():
    month = int(request.args.get("month", datetime.now().month))
    year  = int(request.args.get("year", datetime.now().year))
    data  = db.get_monthly_summary(month, year)
    return jsonify(data)


# ─────────────────────────────────────────────────────────────────────────────
# Categories
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@app.route("/members")
def members():
    all_members = db.get_all_members()
    families = db.get_all_families()
    return render_template("members.html", members=all_members, families=families)


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


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding (Family Setup + Invite Codes)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    families = db.get_all_families()
    active_codes = db.get_active_invite_codes()
    generated = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_family":
            fname = request.form.get("family_name", "").strip()
            admin_name = request.form.get("admin_name", "").strip()
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
                family = db.get_family_by_id(int(family_id))
                fam_name = family["name"] if family else "Family"
                generated = {
                    "code": code,
                    "nickname": nickname,
                    "family": fam_name,
                    "expiry": expiry,
                    "is_admin": is_admin,
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


# ─────────────────────────────────────────────────────────────────────────────
# Shop Mappings
# ─────────────────────────────────────────────────────────────────────────────

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

    mappings  = db.get_all_shop_mappings()
    families  = db.get_all_families()
    cats      = db.get_all_categories()
    return render_template(
        "shop_mappings.html",
        mappings=mappings,
        families=families,
        categories=cats,
    )


@login_required
@app.route("/shop-mappings/delete/<int:mapping_id>", methods=["POST"])
def delete_shop_mapping(mapping_id):
    db.delete_shop_mapping(mapping_id)
    flash("Mapping deleted.", "info")
    return redirect(url_for("shop_mappings"))


# ─────────────────────────────────────────────────────────────────────────────
# Receipts
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@app.route("/receipts")
def receipts():
    receipts_list = db.get_receipts_summary()
    return render_template("receipts.html", receipts=receipts_list)


# ─────────────────────────────────────────────────────────────────────────────
# Unknown Contacts
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@app.route("/unknown-contacts")
def unknown_contacts():
    contacts = db.get_unknown_contacts()
    alerts   = db.get_security_alerts()
    return render_template(
        "unknown_contacts.html",
        contacts=contacts,
        alerts=alerts,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket
    start_scheduler()
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print("\n🚀  Expense Tracker is running!")
    print(f"   Local:   http://127.0.0.1:5001")
    print(f"   Network: http://{local_ip}:5001")
    print(f"   Dashboard URL: {DASHBOARD_URL}\n")
    app.run(host="0.0.0.0", debug=False, port=5001)
