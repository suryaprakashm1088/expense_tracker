"""
services/scheduler.py — Scheduled background jobs for the Expense Tracker.

  backup_database()     — SQLite backup to /data/backups/, rotates last 30; 18:00 UTC (02:00 SGT)
  send_daily_summary()  — AI WhatsApp summary to all family members; 12:00 UTC (20:00 SGT)
  start_scheduler()     — registers both jobs and starts APScheduler; call once at startup
"""
import os
import glob
import shutil
import sqlite3
from datetime import datetime

import database as db
import local_ai as ollama_cl
from extensions import app
from config import TWILIO_NUMBER
from services.ai_clients import get_anthropic_client, get_twilio_client


def backup_database():
    """
    Create a timestamped SQLite backup and rotate old copies.

    Backup location : /data/backups/  (inside the Docker volume — persists between restarts)
    Naming          : expenses_YYYYMMDD_HHMMSS.db
    Retention       : last 30 backups (older ones are deleted automatically)
    Method          : sqlite3.Connection.backup() — hot-backup API, safe while the app
                      is serving requests (no lock contention, no WAL corruption)
    Schedule        : 18:00 UTC = 02:00 SGT (quiet hours)
    """
    KEEP_LAST = 30

    # Resolve the live DB path (same env var used by database.py)
    db_path = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "expenses.db"))
    if not os.path.isfile(db_path):
        app.logger.warning("backup_database: DB not found at %s — skipping", db_path)
        return

    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"expenses_{timestamp}.db")

    try:
        # sqlite3.Connection.backup() is the official hot-backup API.
        # It acquires a shared lock only during page copies — WAL-safe.
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(backup_path)
        with dst:
            src.backup(dst, pages=100)   # copy 100 pages per step (non-blocking)
        src.close()
        dst.close()
        size_kb = os.path.getsize(backup_path) // 1024
        app.logger.info("backup_database: saved %s (%d KB)", backup_path, size_kb)
    except Exception as exc:
        app.logger.error("backup_database: failed — %s", exc)
        # Remove partial file if something went wrong
        if os.path.exists(backup_path):
            os.remove(backup_path)
        return

    # ── Rotate: keep only the KEEP_LAST most-recent backups ─────────────────
    all_backups = sorted(glob.glob(os.path.join(backup_dir, "expenses_*.db")))
    expired     = all_backups[:-KEEP_LAST] if len(all_backups) > KEEP_LAST else []
    for old in expired:
        try:
            os.remove(old)
            app.logger.info("backup_database: rotated old backup %s", old)
        except OSError:
            pass

    app.logger.info(
        "backup_database: %d backup(s) kept in %s", min(len(all_backups), KEEP_LAST), backup_dir
    )


def send_daily_summary():
    """Send an AI-generated daily summary to every approved family member."""
    ai        = get_anthropic_client()
    twilio_cl = get_twilio_client()
    if not ai or not twilio_cl or not TWILIO_NUMBER:
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    families  = db.get_all_families()

    for family in families:
        fid  = family["id"]
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

        # Send to all approved members in this family
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
    """Start the APScheduler background scheduler.

    Jobs (all times in UTC):
      02:00 SGT = 18:00 UTC  → backup_database()     (hot SQLite backup → /data/backups/)
      20:00 SGT = 12:00 UTC  → send_daily_summary()  (AI WhatsApp digest)

    Silently skips if APScheduler is not installed (dev environments without it).
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()

        # Daily DB backup — 02:00 SGT / 18:00 UTC
        scheduler.add_job(backup_database, "cron", hour=18, minute=0,
                          id="db_backup", name="Daily SQLite backup")

        # Daily WhatsApp summary — 20:00 SGT / 12:00 UTC
        scheduler.add_job(send_daily_summary, "cron", hour=12, minute=0,
                          id="daily_summary", name="Daily WhatsApp summary")

        scheduler.start()
        app.logger.info(
            "Scheduler started — db_backup @ 18:00 UTC, daily_summary @ 12:00 UTC"
        )
    except Exception as exc:
        app.logger.warning("Scheduler could not start: %s", exc)
