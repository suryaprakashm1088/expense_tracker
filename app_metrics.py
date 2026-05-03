"""
app_metrics.py — Prometheus metric definitions for the Expense Tracker.

All metrics are defined here and imported by routes/services that need them.
The /metrics endpoint is exposed automatically by prometheus-flask-exporter,
which is initialized in extensions.py.

Metric naming convention:
  expense_tracker_<subsystem>_<name>_<unit>

Usage example:
  from app_metrics import EXPENSE_ADDED, AI_SCAN_DURATION
  EXPENSE_ADDED.labels(method="web", category="Food & Groceries").inc()
  with AI_SCAN_DURATION.labels(engine="lmstudio").time():
      result = scan_receipt(...)
"""

from prometheus_client import Counter, Histogram, Gauge, Info, REGISTRY
from prometheus_client.core import GaugeMetricFamily

# ─────────────────────────────────────────────────────────────────────────────
# HTTP — tracked automatically by prometheus-flask-exporter
# flask_http_request_total{method, path, status}
# flask_http_request_duration_seconds{method, path, status}
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Expenses
# ─────────────────────────────────────────────────────────────────────────────

EXPENSE_ADDED = Counter(
    "expense_tracker_expense_added_total",
    "Total number of expense entries created",
    ["method", "category"],
    # method: web | whatsapp | import
)

EXPENSE_AMOUNT = Counter(
    "expense_tracker_expense_amount_dollars_total",
    "Cumulative dollar value of all expenses added (S$)",
    ["category"],
)

DUPLICATE_DETECTED = Counter(
    "expense_tracker_duplicate_detected_total",
    "Number of duplicate expense warnings triggered",
    ["source"],
    # source: web | whatsapp
)

# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp bot
# ─────────────────────────────────────────────────────────────────────────────

WHATSAPP_MESSAGE = Counter(
    "expense_tracker_whatsapp_message_total",
    "WhatsApp messages received, labelled by parsed type",
    ["message_type"],
    # message_type: expense | cc_bill | receipt | command | unknown | pending_reply
)

WHATSAPP_REPLY_DURATION = Histogram(
    "expense_tracker_whatsapp_reply_duration_seconds",
    "Time to fully process a WhatsApp message and build a reply",
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
)

# ─────────────────────────────────────────────────────────────────────────────
# AI / receipt scanning
# ─────────────────────────────────────────────────────────────────────────────

AI_SCAN_TOTAL = Counter(
    "expense_tracker_ai_scan_total",
    "Receipt scan attempts by engine and outcome",
    ["engine", "status"],
    # engine: lmstudio | ollama | claude
    # status: success | failed
)

AI_SCAN_DURATION = Histogram(
    "expense_tracker_ai_scan_duration_seconds",
    "Wall-clock time for a receipt scan attempt per engine",
    ["engine"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120],
)

# ─────────────────────────────────────────────────────────────────────────────
# Statement imports
# ─────────────────────────────────────────────────────────────────────────────

STATEMENT_IMPORT = Counter(
    "expense_tracker_statement_import_total",
    "Statement files uploaded and parsed",
    ["bank", "file_format", "status"],
    # file_format: csv | pdf
    # status: success | failed | empty
)

STATEMENT_TXN_ADDED = Counter(
    "expense_tracker_statement_transaction_added_total",
    "Individual statement transactions added to expenses from the review page",
    ["bank"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Application info (static labels shown in dashboards)
# ─────────────────────────────────────────────────────────────────────────────

APP_INFO = Info(
    "expense_tracker_app",
    "Static application metadata",
)
APP_INFO.info({
    "version": "2.0",
    "currency": "SGD",
    "stack": "Flask+SQLite+Prometheus",
})

# ─────────────────────────────────────────────────────────────────────────────
# DB-backed live Gauges — pulled fresh on every /metrics scrape
# These survive container restarts because they read from SQLite, not memory.
# ─────────────────────────────────────────────────────────────────────────────

class _DailyStatsCollector:
    """Custom Prometheus collector that queries the DB and filesystem on each scrape.

    Emits:
      expense_tracker_expenses_today          — expenses added today (all methods)
      expense_tracker_whatsapp_messages_today — WhatsApp messages received today
      expense_tracker_last_backup_age_seconds — seconds since the most recent DB backup
      expense_tracker_backup_count            — number of backup files currently on disk
      expense_tracker_last_backup_size_bytes  — size of the most recent backup file
    """

    def collect(self):
        import os, glob, time
        from datetime import datetime

        # ── DB counts ────────────────────────────────────────────────────────
        try:
            import database as db
            expense_count = db.get_expense_count_today()
            msg_count     = db.get_whatsapp_message_count_today()
        except Exception:
            expense_count = 0
            msg_count     = 0

        g1 = GaugeMetricFamily(
            "expense_tracker_expenses_today",
            "Number of expense entries added today (all methods)",
        )
        g1.add_metric([], float(expense_count))
        yield g1

        g2 = GaugeMetricFamily(
            "expense_tracker_whatsapp_messages_today",
            "Number of WhatsApp messages received today",
        )
        g2.add_metric([], float(msg_count))
        yield g2

        # ── Backup filesystem stats ──────────────────────────────────────────
        keep_days = int(os.getenv("BACKUP_KEEP_DAYS", 30))

        try:
            db_path    = os.getenv("DB_PATH", "/data/expenses.db")
            backup_dir = os.path.join(os.path.dirname(db_path), "backups")
            backups    = sorted(glob.glob(os.path.join(backup_dir, "expenses_*.db")))

            backup_count = len(backups)
            if backups:
                latest      = backups[-1]
                mtime       = os.path.getmtime(latest)
                age_seconds = time.time() - mtime
                size_bytes  = os.path.getsize(latest)
            else:
                age_seconds = -1   # -1 = no backup ever taken
                size_bytes  = 0
        except Exception:
            backup_count = 0
            age_seconds  = -1
            size_bytes   = 0

        g3 = GaugeMetricFamily(
            "expense_tracker_last_backup_age_seconds",
            "Seconds elapsed since the most recent DB backup (-1 if no backup exists)",
        )
        g3.add_metric([], float(age_seconds))
        yield g3

        g4 = GaugeMetricFamily(
            "expense_tracker_backup_count",
            "Number of DB backup files currently on disk",
        )
        g4.add_metric([], float(backup_count))
        yield g4

        g5 = GaugeMetricFamily(
            "expense_tracker_last_backup_size_bytes",
            "File size in bytes of the most recent DB backup",
        )
        g5.add_metric([], float(size_bytes))
        yield g5

        g6 = GaugeMetricFamily(
            "expense_tracker_backup_keep_days",
            "Configured backup retention limit (BACKUP_KEEP_DAYS env var)",
        )
        g6.add_metric([], float(keep_days))
        yield g6


# Register once — guard against double-import during Flask startup
try:
    REGISTRY.register(_DailyStatsCollector())
except ValueError:
    pass  # already registered from a previous import
