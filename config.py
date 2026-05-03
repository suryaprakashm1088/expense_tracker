"""
config.py — All application constants, environment variables, and lookup tables.

No project-level imports here. This is the root of the dependency tree.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── External service credentials ──────────────────────────────────────────────
TWILIO_SID          = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_NUMBER       = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
DASHBOARD_URL       = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:5001")

# ── Investments ───────────────────────────────────────────────────────────────
EODHD_API_KEY           = os.environ.get("EODHD_API_KEY", "")
INVESTMENT_REFRESH_HOUR = int(os.environ.get("INVESTMENT_REFRESH_HOUR", "9"))   # UTC; 9 UTC = 17:00 SGT

# ── Month names (1-indexed; index 0 is empty string) ─────────────────────────
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# ── Category choices for WhatsApp bot (short label → DB category name) ────────
CATEGORY_CHOICES = [
    ("Groceries",     "Food & Groceries"),
    ("Food",          "Outside Food"),
    ("Transport",     "Transport"),
    ("Personal Care", "Personal Care"),
    ("Utilities",     "Bills & Utilities"),
    ("Shopping",      "Shopping"),
    ("Healthcare",    "Healthcare"),
    ("Education",     "Education"),
    ("Other",         "Other"),
]

# ── Keyword → DB category (used in WhatsApp message parsing) ──────────────────
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
    "entertainment": "Entertainment",
    "movie":        "Entertainment",
    "netflix":      "Entertainment",
    "spotify":      "Entertainment",
    "games":        "Entertainment",
    "game":         "Entertainment",
}

# ── Singapore Credit Card Banks — short token → display name ──────────────────
SG_CC_BANKS = {
    # Big local banks
    "dbs":              "DBS",
    "posb":             "POSB",
    "ocbc":             "OCBC",
    "uob":              "UOB",
    # International banks
    "citi":             "Citi",
    "citibank":         "Citi",
    "hsbc":             "HSBC",
    "scb":              "SCB",
    "sc":               "SCB",
    "standardchartered": "SCB",
    "maybank":          "Maybank",
    "mbb":              "Maybank",
    "amex":             "AMEX",
    "americanexpress":  "AMEX",
    # Smaller / newer SG banks
    "boc":              "BOC",
    "icbc":             "ICBC",
    "rhb":              "RHB",
    "anz":              "ANZ",
    "trust":            "Trust",
    "gxs":              "GXS",
    "maribank":         "Mari",
}

# Tokens that signal a CC bill message (must contain at least one)
CC_TOKENS = {"cc", "credit", "card", "creditcard", "bill", "payment", "pay"}

# ── Endpoint access-control sets ──────────────────────────────────────────────
PUBLIC_ENDPOINTS = {'login', 'logout', 'whatsapp_webhook', 'static', 'health', 'serve_temp_image', 'metrics', 'prometheus_metrics'}

MEMBER_ALLOWED = {
    'index', 'expenses', 'add_expense', 'edit_expense',
    'summary', 'receipts', 'receipt_detail', 'static',
    'budget', 'delete_income', 'delete_fixed_expense',
    'add', 'edit', 'delete',
    'credit_cards', 'delete_cc_bill',
    'statement_upload', 'statement_review', 'add_statement_transaction',
    'api_category_detail', 'api_monthly_data',
    # Investments
    'investments', 'investment_add', 'investment_edit', 'investment_delete',
    'investment_refresh_all', 'investment_refresh_one',
    'investment_search', 'investment_history',
}

ADMIN_ONLY = {
    'members', 'approve_member', 'delete_member', 'toggle_admin',
    'set_member_password_route', 'revoke_member_login_route',
    'categories', 'add_category', 'edit_category', 'delete_category',
    'shop_mappings', 'add_shop_mapping', 'delete_shop_mapping',
    'invite', 'unknown_contacts', 'change_credentials',
    'families', 'add_family', 'delete_family',
    'onboarding',
}

CSRF_EXEMPT = {'whatsapp_webhook', 'static', 'login', 'health'}
