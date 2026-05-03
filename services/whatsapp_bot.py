"""
services/whatsapp_bot.py — Core WhatsApp bot logic.

Public API:
  twiml(msg)                                    → Flask Response (TwiML XML)
  handle_pending_response(body, sender, member) → reply str or None
  build_whatsapp_reply(body, sender, member)    → reply str

Constants:
  GENERIC_ERROR, GENERIC_CODE_ERROR, MSG_PENDING, MSG_REGISTERED_PENDING
"""
import re
import time
import uuid
from datetime import datetime, timedelta

from flask import Response

import database as db
import local_ai as ollama_cl
from extensions import app
from config import (
    TWILIO_NUMBER, DASHBOARD_URL,
    CATEGORY_CHOICES, CATEGORY_KEYWORDS,
    SG_CC_BANKS,
)
from services.ai_clients import get_anthropic_client, get_category_from_ai, get_twilio_client
from services.expense_parser import parse_expense_message
from services.cc_parser import parse_cc_bill_message
from services.invite import generate_code, parse_expiry
try:
    from app_metrics import (
        EXPENSE_ADDED, EXPENSE_AMOUNT, DUPLICATE_DETECTED,
        WHATSAPP_MESSAGE, WHATSAPP_REPLY_DURATION,
    )
    _METRICS = True
except Exception:
    _METRICS = False

# ── Bot reply string constants ─────────────────────────────────────────────────
GENERIC_ERROR = "Sorry, we are unable to process your message."
GENERIC_CODE_ERROR = (
    "❌ This invite code is invalid, expired, or already used.\n"
    "Please ask your admin for a new invite code."
)
MSG_PENDING = (
    "⏳ Your registration is pending admin approval.\n"
    "You will receive a message here once you're approved. Please wait!"
)
MSG_REGISTERED_PENDING = (
    "👋 Hi {name}! Your registration request has been received.\n\n"
    "An admin will review and approve your access shortly. "
    "You'll get a message here as soon as you're approved. 🙏"
)


# ── TwiML helper ──────────────────────────────────────────────────────────────

def twiml(msg):
    """Wrap a plain-text reply in a TwiML XML envelope."""
    safe = (msg
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'
    return Response(xml, mimetype="text/xml")


# ── Pending-state handler ─────────────────────────────────────────────────────

def handle_pending_response(body, sender, member):
    """Handle YES/NO/EDIT/number responses to active pending bot states.

    Returns a reply string, or None if there is no pending state for the sender.
    """
    text    = body.strip().lower()
    pending = db.get_pending_state(sender)
    if not pending:
        return None

    ptype = pending.get("type")

    # ── Receipt confirmation ──────────────────────────────────────────────────
    if ptype == "receipt":
        if text == "yes":
            store       = pending.get("store", "Receipt")
            date        = pending.get("date", datetime.now().strftime("%Y-%m-%d"))
            subdivisions = pending.get("subdivisions", [])
            family_id   = pending.get("family_id")
            member_name = member.get("nickname") or member.get("name", "Member")
            receipt_id  = str(uuid.uuid4())
            saved       = 0
            receipt_items = []
            for item in subdivisions:
                amt  = item.get("amount", 0)
                name = item.get("name", store)
                cat  = item.get("category", "Other")
                label = item.get("label")
                eid  = db.add_expense(
                    title=name, amount=amt, category=cat, date=date,
                    note=f"Receipt from {store}", added_by=member_name,
                    shop_name=store, label=label,
                    receipt_id=receipt_id, family_id=family_id,
                )
                receipt_items.append({"expense_id": eid, "name": name, "amount": amt,
                                      "category": cat, "label": label})
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

        # Inline edit: "1 Transport" or "2 delete"
        edit_match = re.match(r"^(\d+)\s+(.+)$", text.strip())
        if edit_match:
            idx       = int(edit_match.group(1)) - 1
            new_input = edit_match.group(2).strip()
            subdivisions = pending.get("subdivisions", [])
            if 0 <= idx < len(subdivisions):
                if new_input == "delete":
                    subdivisions.pop(idx)
                    pending["subdivisions"] = subdivisions
                    db.save_pending_state(sender, pending)
                    return f"Removed item {idx+1}. Send YES to save remaining {len(subdivisions)} items."
                matched_cat = None
                for short, full in CATEGORY_CHOICES:
                    if short.lower() == new_input.lower() or full.lower() == new_input.lower():
                        matched_cat = full
                        break
                if matched_cat:
                    subdivisions[idx]["category"] = matched_cat
                    pending["subdivisions"] = subdivisions
                    db.save_pending_state(sender, pending)
                    return f"Updated item {idx+1} to {matched_cat}. Send YES to save."

        return "Send YES to save, NO to cancel, or EDIT to change categories."

    # ── Category ask ──────────────────────────────────────────────────────────
    if ptype == "category_ask":
        try:
            choice = int(text.strip())
            if 1 <= choice <= len(CATEGORY_CHOICES):
                short_name, full_cat = CATEGORY_CHOICES[choice - 1]
                parsed    = pending.get("parsed", {})
                shop      = pending.get("shop") or parsed.get("title")
                family_id = pending.get("family_id")
                if shop:
                    db.add_shop_mapping(shop.lower(), full_cat, family_id=family_id)
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

    # ── Self-duplicate confirm ────────────────────────────────────────────────
    if ptype == "duplicate_confirm":
        orig_msg  = pending.get("original_message", "")
        if body.strip().lower() == orig_msg.lower():
            parsed    = pending.get("parsed", {})
            member_name = member.get("nickname") or member.get("name", "Member")
            today     = datetime.now().strftime("%Y-%m-%d")
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
                f"💸 S${parsed.get('amount', 0):,.2f} · {parsed.get('category', 'Other')}"
            )
        db.clear_pending_state(sender)
        return "Duplicate cancelled. Send a new expense to continue."

    # ── Group duplicate confirm ───────────────────────────────────────────────
    if ptype == "group_dup_confirm":
        parsed    = pending.get("parsed", {})
        member_name = member.get("nickname") or member.get("name", "Member")
        today     = datetime.now().strftime("%Y-%m-%d")
        family_id = member.get("family_id")
        if text in ("yes", "y", "confirm", "ok"):
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
                f"✅ Added!\n"
                f"💸 S${parsed.get('amount', 0):,.2f} · {parsed.get('category', 'Other')}\n"
                f"📅 {today}"
            )
        db.clear_pending_state(sender)
        return "❌ Cancelled. Expense not added."

    return None


# ── Main reply builder ────────────────────────────────────────────────────────

def build_whatsapp_reply(body, sender, member):
    """Dispatch incoming WhatsApp text to the appropriate handler.

    Returns a plain-text reply string.
    """
    _t0 = time.time()
    text        = body.strip().lower()
    now         = datetime.now()
    family_id   = member.get("family_id")
    is_admin    = member.get("is_admin", 0)
    member_name = member.get("nickname") or member.get("name", "Member")
    today_str   = now.strftime("%Y-%m-%d")
    _msg_type   = "unknown"  # will be overwritten below

    def _finish(reply, msg_type="unknown"):
        # Persist to DB — survives container restarts, used for Twilio cost tracking
        try:
            db.log_whatsapp_message(
                from_number=sender,
                message_type=msg_type,
                family_id=family_id,
            )
        except Exception:
            pass  # never let logging break the bot reply
        if _METRICS:
            WHATSAPP_MESSAGE.labels(message_type=msg_type).inc()
            WHATSAPP_REPLY_DURATION.observe(time.time() - _t0)
        return reply

    # ── HELP ─────────────────────────────────────────────────────────────────
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
            "💳 *Log CC bill:*\n"
            "   `DBS CC BILL 500`\n"
            "   `OCBC cc 300`\n"
            "   `UOB credit card 450`\n"
            "   `cc` — view your CC bills\n\n"
            "📸 *Receipt:* Send any receipt photo\n\n"
            "📊 *Summaries:*\n"
            "   `today` `monthly` `mine` `week`\n\n"
            "🔍 *Category drill-down:*\n"
            "   `report food` — top spends in Outside Food\n"
            "   `details groceries` — top spends by category\n\n"
            "🤖 *AI insight:* `ai summary`\n\n"
            "↩️ *Undo last:* `undo`\n"
            "📋 *Last 5:* `last`"
            + admin_section
        )

    # ── UNDO ─────────────────────────────────────────────────────────────────
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

    # ── LAST ─────────────────────────────────────────────────────────────────
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

        family   = db.get_family_by_id(family_id)
        fam_name = family["name"] if family else "Family"
        total    = sum(e["amount"] for e in exps)

        shop_totals = {}
        for e in exps:
            s = e.get("shop_name") or e.get("title") or "Other"
            shop_totals[s] = shop_totals.get(s, 0) + e["amount"]

        cat_totals = {}
        for e in exps:
            c = e["category"]
            cat_totals[c] = cat_totals.get(c, 0) + e["amount"]

        my_total = sum(e["amount"] for e in exps if e.get("added_by") == member_name)

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
        data  = db.get_monthly_summary(now.month, now.year, family_id=family_id)
        total = sum(r["total"] for r in data)
        if not data:
            return f"📊 No expenses for {now.strftime('%B %Y')} yet."

        last_month = now.month - 1 or 12
        last_year  = now.year if now.month > 1 else now.year - 1
        last_data  = db.get_monthly_summary(last_month, last_year, family_id=family_id)
        last_total = sum(r["total"] for r in last_data)
        diff       = total - last_total
        diff_str   = (f"↑ S${diff:,.0f} vs last month" if diff > 0
                      else f"↓ S${abs(diff):,.0f} vs last month")

        lines = [f"📊 *{now.strftime('%B %Y')} Summary*\n"]
        for r in data:
            pct = round(r["total"] / total * 100) if total else 0
            lines.append(f"  {r['category']:<18} S${r['total']:,.0f} ({pct}%)")
        lines.append(f"\n💰 *Total: S${total:,.0f}*")
        lines.append(f"📈 {diff_str}")
        return "\n".join(lines)

    # ── MINE ─────────────────────────────────────────────────────────────────
    if text in ("my", "mine", "me"):
        exps       = db.get_expenses_by_member(member_name, limit=10)
        today_exps = [e for e in exps if e["date"] == today_str]
        if not today_exps:
            return f"📋 No expenses by you today ({today_str})."
        total = sum(e["amount"] for e in today_exps)
        lines = ["📋 *Your expenses today:*\n"]
        for e in today_exps:
            lines.append(f"• {e['title']} — S${e['amount']:,.2f} [{e['category']}]")
        lines.append(f"\n💰 Your total: S${total:,.2f}")
        return "\n".join(lines)

    # ── WEEK ──────────────────────────────────────────────────────────────────
    if text == "week":
        week_ago  = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        conn_rows = db.get_all_expenses(family_id=family_id)
        week_exps = [e for e in conn_rows if e["date"] >= week_ago]
        if not week_exps:
            return "📅 No expenses in the last 7 days."
        total     = sum(e["amount"] for e in week_exps)
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
        data  = db.get_monthly_summary(now.month, now.year, family_id=family_id)
        total = sum(r["total"] for r in data)
        return f"💰 Total spent in *{now.strftime('%B %Y')}*: S${total:,.0f}"

    # ── AI SUMMARY ────────────────────────────────────────────────────────────
    if text in ("ai summary", "ai report", "smart summary", "insight"):
        if not ollama_cl.is_available():
            return (
                "🤖 Local AI (Docker Model Runner) is not available.\n"
                "Make sure Docker Desktop is running and the model is pulled:\n"
                "  docker model pull ai/llama3.2"
            )
        category_data = db.get_monthly_summary(now.month, now.year, family_id=family_id)
        all_expenses  = db.get_all_expenses(month=now.month, year=now.year, family_id=family_id)
        grand_total   = sum(r["total"] for r in category_data)
        if grand_total == 0:
            return f"📊 No expenses found for {now.strftime('%B %Y')} yet."
        for r in category_data:
            r["pct"] = round(r["total"] / grand_total * 100, 1) if grand_total else 0
        try:
            summary_text = ollama_cl.summarise_expenses_with_ollama(
                expenses=all_expenses,
                month_name=now.strftime("%B"),
                year=now.year,
                grand_total=grand_total,
                category_data=category_data,
            )
            return f"🤖 *AI Summary — {now.strftime('%B %Y')}*\n\n{summary_text}"
        except Exception as e:
            app.logger.error(f"AI summary WhatsApp error: {e}")
            return "🤖 AI summary failed. Please try again in a moment."

    # ── ADMIN COMMANDS ────────────────────────────────────────────────────────
    if is_admin:
        if text.startswith("invite "):
            parts      = body.strip().split()
            nickname   = parts[1] if len(parts) > 1 else "Member"
            expiry_str = parts[2] if len(parts) > 2 else "24hrs"
            expires_at = parse_expiry(expiry_str)
            code       = generate_code()
            while db.get_invite_code(code):
                code = generate_code()
            db.add_invite_code(
                code=code, family_id=family_id, created_by=sender,
                expires_at=expires_at, nickname=nickname, is_admin=0,
            )
            family   = db.get_family_by_id(family_id)
            fam_name = family["name"] if family else "Family"
            exp_label = expiry_str if expiry_str != "24hrs" else "24 hours"
            return (
                f"Code for {nickname}: *{code}*\n"
                f"Family: {fam_name}\n"
                f"Expires: {exp_label}\n\n"
                f"Tell {nickname} to send:\n"
                f"*JOIN {code}*"
            )

        if text == "codes":
            codes  = db.get_active_invite_codes(family_id=family_id)
            active = [c for c in codes if not c.get("is_used")]
            if not active:
                return "No active unused invite codes."
            lines = ["📋 *Active Invite Codes:*\n"]
            for c in active[:10]:
                lines.append(
                    f"• {c['code']} → {c.get('nickname','?')} "
                    f"(expires: {c.get('expires_at','N/A')[:10]})"
                )
            return "\n".join(lines)

        if text.startswith("revoke "):
            code_to_revoke = body.strip().split()[-1].upper()
            db.revoke_invite_code(code_to_revoke)
            return f"✅ Code {code_to_revoke} has been revoked."

        if text == "members":
            members_list = db.get_all_members()
            if family_id:
                members_list = [m for m in members_list if m.get("family_id") == family_id]
            if not members_list:
                return "No members found."
            lines = [f"👥 *Family Members ({len(members_list)}):*\n"]
            for m in members_list:
                status    = "✅" if m["is_approved"] else "🚫"
                admin_tag = " 👑" if m.get("is_admin") else ""
                lines.append(
                    f"{status} {m.get('nickname') or m['name']}{admin_tag} — "
                    f"{m['whatsapp_number'].replace('whatsapp:','')}"
                )
            return "\n".join(lines)

        if text.startswith("remove "):
            phone_raw = body.strip().split()[-1]
            if not phone_raw.startswith("whatsapp:"):
                phone_raw = "whatsapp:+" + phone_raw.lstrip("+")
            db.deactivate_member_by_phone(phone_raw)
            return f"✅ Member {phone_raw.replace('whatsapp:','')} deactivated."

        map_match = re.match(r"^map\s+(.+?)\s+to\s+(.+)$", text.strip())
        if map_match:
            shop_n = map_match.group(1).strip()
            cat_n  = map_match.group(2).strip().title()
            db.add_shop_mapping(shop_n, cat_n, family_id=family_id)
            return f"✅ Mapped '{shop_n}' → {cat_n}"

        if text == "report":
            data       = db.get_monthly_summary(now.month, now.year, family_id=family_id)
            total      = sum(r["total"] for r in data)
            shop_data  = db.get_shop_summary(now.month, now.year, family_id=family_id)
            cc_summary = db.get_cc_summary(now.month, now.year, family_id=family_id)
            if not data:
                return f"📊 No data for {now.strftime('%B %Y')}."
            lines = [f"📊 *{now.strftime('%B %Y')} Family Report*\n",
                     f"💰 Variable Total: S${total:,.2f}\n",
                     "📂 *Categories (variable):*"]
            for r in data:
                pct = round(r["total"] / total * 100) if total else 0
                lines.append(f"  {r['category']:<18} S${r['total']:,.2f} ({pct}%)")
            if shop_data:
                lines.append("\n🏪 *Top Shops:*")
                for s in shop_data[:5]:
                    if s.get("shop_name"):
                        lines.append(f"  {s['shop_name']:<20} S${s['total']:,.2f}")
            if cc_summary:
                cc_total = sum(r["total"] for r in cc_summary)
                lines.append(f"\n💳 *CC Bills: S${cc_total:,.2f}*")
                for r in cc_summary:
                    lines.append(f"  {r['member_name']:<12} {r['bank_name']:<6} S${r['total']:,.2f}")
            lines.append("\n💡 Send `report <category>` for top spends drill-down.")
            return "\n".join(lines)

    # ── CREDIT CARD BILL ──────────────────────────────────────────────────────
    cc_parsed = parse_cc_bill_message(body)
    if cc_parsed:
        db.add_cc_bill(
            bank_name=cc_parsed["bank_name"],
            amount=cc_parsed["amount"],
            member_name=member_name,
            date_str=today_str,
            note=f"via WhatsApp by {member_name}",
            family_id=family_id,
        )
        month_total = db.get_cc_member_total(now.month, now.year, member_name, family_id=family_id)
        return (
            f"💳 *CC Bill Logged!*\n\n"
            f"🏦 Bank: {cc_parsed['bank_name']}\n"
            f"💸 Amount: S${cc_parsed['amount']:,.2f}\n"
            f"📅 Date: {today_str}\n"
            f"👤 Member: {member_name}\n\n"
            f"📊 Your total CC bills this month: S${month_total:,.2f}"
        )

    # ── CC BILLS SUMMARY ─────────────────────────────────────────────────────
    if text in ("cc", "cc bills", "credit card", "my cc", "cc summary"):
        bills = db.get_cc_bills(month=now.month, year=now.year,
                                member_name=member_name, family_id=family_id)
        if not bills:
            return (
                f"💳 No CC bills logged for {now.strftime('%B %Y')} yet.\n"
                f"Send: `DBS CC BILL 500` to add one."
            )
        total = sum(b["amount"] for b in bills)
        lines = [f"💳 *Your CC Bills — {now.strftime('%B %Y')}*\n"]
        for b in bills:
            lines.append(f"  🏦 {b['bank_name']:<8} S${b['amount']:,.2f}  ({b['date']})")
        lines.append(f"\n💰 Total: S${total:,.2f}")
        return "\n".join(lines)

    # ── REPORT <category> — drill-down ────────────────────────────────────────
    report_cat_match = re.match(r"^(?:report|details?)\s+(.+)$", text.strip())
    if report_cat_match:
        cat_query   = report_cat_match.group(1).strip().lower()
        all_cats    = db.get_all_categories()
        matched_cat = None
        for c in all_cats:
            if cat_query in c.lower() or c.lower() in cat_query:
                matched_cat = c
                break
        if not matched_cat:
            matched_cat = CATEGORY_KEYWORDS.get(cat_query)
        if not matched_cat:
            return (
                f"❓ Category '{cat_query}' not found.\n"
                f"Available: {', '.join(all_cats)}"
            )
        month_top  = db.get_top_expenses_by_category(matched_cat, now.month, now.year,
                                                      limit=5, family_id=family_id)
        week_top   = db.get_top_expenses_this_week_by_category(matched_cat, limit=5,
                                                                family_id=family_id)
        month_total = sum(e["amount"] for e in month_top) if month_top else 0
        lines = [f"📊 *{matched_cat} — {now.strftime('%B %Y')}*\n"]
        if month_top:
            lines.append(f"🗓️ *Top spends this month* (S${month_total:,.2f} total):")
            for e in month_top:
                shop = f" · {e['shop_name']}" if e.get("shop_name") else ""
                lines.append(f"  • {e['date']} {e['title']}{shop} — S${e['amount']:,.2f}")
        else:
            lines.append("No spends this month.")
        lines.append("")
        if week_top:
            lines.append("📅 *Top spends this week:*")
            for e in week_top:
                shop = f" · {e['shop_name']}" if e.get("shop_name") else ""
                lines.append(f"  • {e['date']} {e['title']}{shop} — S${e['amount']:,.2f}")
        else:
            lines.append("No spends this week.")
        return "\n".join(lines)

    # ── ADD EXPENSE ───────────────────────────────────────────────────────────
    parsed = parse_expense_message(body, family_id=family_id)
    if parsed:
        today = now.strftime("%Y-%m-%d")

        # Self-duplicate detection
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

        # Group duplicate detection
        group_dup = db.check_group_duplicate(
            amount=parsed["amount"],
            date_str=today,
            family_id=family_id,
            shop_name=parsed.get("shop_name"),
            title=parsed.get("title"),
            excluded_added_by=member_name,
        )
        if group_dup:
            other_member = group_dup.get("added_by", "another member")
            pending_data = {
                "type": "group_dup_confirm",
                "original_message": body.strip().lower(),
                "parsed": parsed,
                "family_id": family_id,
                "other_member": other_member,
            }
            db.save_pending_state(sender, pending_data)
            return (
                f"⚠️ *Heads up!* {other_member} already logged "
                f"S${group_dup['amount']:,.2f} at "
                f"{group_dup.get('shop_name') or group_dup.get('title','the same place')} today.\n\n"
                f"Is this a separate expense?\n"
                f"Reply *YES* to confirm and add it, or *NO* to cancel."
            )

        # Unknown category → try AI, then ask
        if parsed["category"] == "Other" and not parsed.get("shop_name"):
            ai_cat = get_category_from_ai(body)
            if ai_cat and ai_cat != "Other":
                parsed["category"] = ai_cat
            else:
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
        if _METRICS:
            EXPENSE_ADDED.labels(method="whatsapp", category=parsed["category"]).inc()
            EXPENSE_AMOUNT.labels(category=parsed["category"]).inc(parsed["amount"])
        shop_line  = f"\n🏪 {parsed['shop_name']}" if parsed.get("shop_name") else ""
        label_line = f"\n📝 {parsed['label']}" if parsed.get("label") else ""
        return _finish(
            f"✅ *Expense Added!*\n\n"
            f"💸 S${parsed['amount']:,.2f}\n"
            f"🏷️ {parsed['category']}"
            f"{shop_line}"
            f"{label_line}\n"
            f"📅 {today}\n"
            f"_Added by {member_name}_",
            msg_type="expense",
        )

    # ── UNKNOWN ───────────────────────────────────────────────────────────────
    return _finish(
        "❓ I didn't understand that.\n\n"
        "Send *help* to see all commands.\n"
        "Quick example: `FairPrice 45.50`",
        msg_type="unknown",
    )
