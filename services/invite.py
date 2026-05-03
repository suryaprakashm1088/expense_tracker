"""
services/invite.py — Invite code generation, expiry parsing, and JOIN flow.

  generate_code(length)              → random uppercase+digit string
  parse_expiry(expiry_str)           → datetime
  handle_join_code(sender, name, code) → reply string
"""
import random
import string
from datetime import datetime, timedelta

import database as db
from config import TWILIO_NUMBER, DASHBOARD_URL
from services.ai_clients import get_twilio_client

GENERIC_CODE_ERROR = (
    "❌ This invite code is invalid, expired, or already used.\n"
    "Please ask your admin for a new invite code."
)


def generate_code(length=8):
    """Return a random uppercase-alphanumeric invite code."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def parse_expiry(expiry_str):
    """Convert a human-readable expiry string to a datetime.

    Accepts: '1hr', '24hrs', '7days', '7d', '1h'  — defaults to 24 hours.
    """
    expiry_str = str(expiry_str).lower().strip()
    now = datetime.now()
    if "7day" in expiry_str or expiry_str == "7d":
        return now + timedelta(days=7)
    if "1hr" in expiry_str or expiry_str == "1h":
        return now + timedelta(hours=1)
    return now + timedelta(hours=24)


def handle_join_code(sender, sender_name, code):
    """Process a JOIN <code> WhatsApp message.

    Validates the invite code, creates a member record, notifies the admin,
    and returns a reply string.
    """
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

    # Check max usage
    if invite.get("is_used") and invite.get("max_uses", 1) <= 1:
        db.log_unknown_contact(sender, f"JOIN {code}", "used_code", code)
        return GENERIC_CODE_ERROR

    # Already a member?
    if db.get_member_by_number(sender):
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

    # Notify the admin who created the code
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
        f"🎉 Welcome {nickname}!\n"
        f"You have successfully joined *{family_name}* expense tracker.\n\n"
        f"Send *help* to see all available commands and get started. 💪"
    )
