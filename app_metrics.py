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
    """Custom Prometheus collector that queries the DB on each scrape.

    Emits two Gauges:
      expense_tracker_expenses_today   — expenses added today (all methods)
      expense_tracker_whatsapp_messages_today — WhatsApp messages received today
    """

    def collect(self):
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


# Register once — guard against double-import during Flask startup
try:
    REGISTRY.register(_DailyStatsCollector())
except ValueError:
    pass  # already registered from a previous import
