"""
routes/whatsapp.py — Twilio WhatsApp webhook and health-check endpoints.

Routes registered:
  GET/POST  /whatsapp
  GET       /health
"""
from flask import request, jsonify, Response

import database as db
from extensions import app
from config import TWILIO_AUTH_TOKEN, DASHBOARD_URL
from services.whatsapp_bot import (
    twiml, handle_pending_response, build_whatsapp_reply,
    GENERIC_ERROR, MSG_PENDING, MSG_REGISTERED_PENDING,
)
from services.receipt import handle_receipt_photo
from services.invite import handle_join_code


def _validate_twilio_signature():
    """Validate the Twilio request signature against DASHBOARD_URL.

    Cloudflare Tunnel terminates TLS before Flask sees the request, so
    request.url is always http://... internally.  We rebuild the URL using
    DASHBOARD_URL (the real public domain) which matches what Twilio signed.
    Returns True when no AUTH_TOKEN is configured (local development).
    """
    if not TWILIO_AUTH_TOKEN:
        return True
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(TWILIO_AUTH_TOKEN)

        base = DASHBOARD_URL.rstrip('/')
        url  = f"{base}{request.path}"
        if request.query_string:
            url += f"?{request.query_string.decode('utf-8')}"

        signature = request.headers.get('X-Twilio-Signature', '')
        result    = validator.validate(url, request.form.to_dict(), signature)

        if not result:
            app.logger.warning(
                "Twilio signature validation FAILED. "
                f"Validated against URL: {url} | "
                f"Signature header: {signature[:20]}..."
            )
        return result
    except Exception as e:
        app.logger.error(f"Twilio signature validation error: {e}")
        return False


def _notify_admin_new_registration(member_name, member_phone):
    """Send a WhatsApp notification to admin(s) when a new member self-registers."""
    from services.ai_clients import get_twilio_client
    from config import TWILIO_NUMBER
    twilio_cl = get_twilio_client()
    if not twilio_cl or not TWILIO_NUMBER:
        return
    try:
        all_members   = db.get_all_members()
        admins        = [m for m in all_members if m.get("is_admin") and m.get("whatsapp_number")]
        phone_display = member_phone.replace("whatsapp:", "")
        msg = (
            f"🔔 *New registration request!*\n"
            f"*Name:* {member_name}\n"
            f"*Phone:* {phone_display}\n\n"
            f"Log in to the dashboard to approve and assign a family:\n"
            f"{DASHBOARD_URL}/members"
        )
        for admin in admins:
            try:
                twilio_cl.messages.create(from_=TWILIO_NUMBER, to=admin["whatsapp_number"], body=msg)
            except Exception:
                pass
    except Exception:
        pass


@app.route("/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        return (
            "<h2>✅ WhatsApp Webhook is active.</h2>"
            "<p>This endpoint receives messages from Twilio.</p>"
        ), 200

    sender_preview = request.form.get("From", "unknown")
    body_preview   = (request.form.get("Body", "") or "[media]")[:60]
    app.logger.info(f"📩 Webhook from {sender_preview}: {body_preview!r}")

    if not _validate_twilio_signature():
        app.logger.warning(f"❌ Twilio signature REJECTED for request from {sender_preview}")
        return Response("Forbidden", status=403)

    sender    = request.form.get("From", "")
    body      = request.form.get("Body", "").strip()
    name      = request.form.get("ProfileName", "Member")
    media_url = request.form.get("MediaUrl0", "")

    if not sender:
        return twiml(GENERIC_ERROR)

    # JOIN code flow (open to unknown numbers)
    if body.upper().startswith("JOIN "):
        code = body.strip()[5:].strip()
        return twiml(handle_join_code(sender, name, code))

    # Verify member is registered and approved
    member = db.get_member_by_number(sender)

    if not member:
        display_name = name or sender.replace("whatsapp:", "")
        db.add_member(
            name=display_name,
            whatsapp_number=sender,
            is_approved=0,
            nickname=display_name,
            added_by="WhatsApp (self-registered)",
        )
        db.log_unknown_contact(sender, body or "[photo]", "self_registered")
        _notify_admin_new_registration(display_name, sender)
        return twiml(MSG_REGISTERED_PENDING.format(name=display_name))

    if not member.get("is_approved"):
        db.log_unknown_contact(sender, body or "[photo]", "pending")
        return twiml(MSG_PENDING)

    # Receipt photo (no text)
    if media_url and not body:
        return twiml(handle_receipt_photo(media_url, sender, member))

    if not body:
        return twiml(GENERIC_ERROR)

    # Pending state check
    pending_reply = handle_pending_response(body, sender, member)
    if pending_reply is not None:
        return twiml(pending_reply)

    # Receipt photo WITH text caption
    if media_url:
        return twiml(handle_receipt_photo(media_url, sender, member))

    reply = build_whatsapp_reply(body, sender, member)
    return twiml(reply)


@app.route("/health")
def health():
    """Public health endpoint — used by Docker HEALTHCHECK, AWS ALB, and monitoring."""
    try:
        db.get_all_categories()  # lightweight DB round-trip
        return jsonify({"status": "ok", "service": "expense-tracker"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
