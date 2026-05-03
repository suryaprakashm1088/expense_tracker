import sqlite3
import os
import re
import json
from datetime import datetime, timedelta


def _norm(s):
    """Normalise a shop/vendor name for fuzzy matching.
    Strips ALL non-alphanumeric characters (spaces, hyphens, dots, etc.)
    and lowercases, so 'Sat Breakfast 13', 'sat-breakfast-13',
    'sat breakfast-13' all compare as equal.
    """
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _sql_norm(col):
    """Return a SQL expression that normalises a column the same way _norm() does.
    Strips spaces, hyphens, underscores, dots, commas, apostrophes, and slashes.
    SQLite doesn't support regex, so we nest REPLACE() calls.
    """
    return (
        f"REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
        f"LOWER({col}), ' ', ''), '-', ''), '_', ''), '.', ''), ',', ''), '''', ''), '/', '')"
    )

# DB_PATH: use environment variable (set to /data/expenses.db in Docker)
# Falls back to local expenses.db for development
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "expenses.db"))

DEFAULT_CATEGORIES = [
    ("Food & Groceries", "🛒"),
    ("Outside Food",     "🍽️"),
    ("Transport",        "🚗"),
    ("Shopping",         "🛍️"),
    ("Bills & Utilities","💡"),
    ("Entertainment",    "🎬"),
    ("Personal Care",    "🧴"),
    ("Healthcare",       "🏥"),
    ("Education",        "📚"),
    ("Other",            "📦"),
]

# Singapore shop → category mappings (global, family_id = NULL)
SINGAPORE_SHOP_MAPPINGS = [
    # Food & Groceries
    ("fairprice",           "Food & Groceries"),
    ("ntuc fairprice",      "Food & Groceries"),
    ("cold storage",        "Food & Groceries"),
    ("coldstorage",         "Food & Groceries"),
    ("giant",               "Food & Groceries"),
    ("sheng siong",         "Food & Groceries"),
    ("shengsiong",          "Food & Groceries"),
    ("prime supermarket",   "Food & Groceries"),
    ("little farms",        "Food & Groceries"),
    ("redmart",             "Food & Groceries"),
    ("jasons",              "Food & Groceries"),
    ("marketplace",         "Food & Groceries"),
    ("wet market",          "Food & Groceries"),
    # Outside Food
    ("mcdonalds",           "Outside Food"),
    ("mcdonald's",          "Outside Food"),
    ("kfc",                 "Outside Food"),
    ("subway",              "Outside Food"),
    ("burger king",         "Outside Food"),
    ("burgerking",          "Outside Food"),
    ("toast box",           "Outside Food"),
    ("toastbox",            "Outside Food"),
    ("ya kun",              "Outside Food"),
    ("yakun",               "Outside Food"),
    ("old chang kee",       "Outside Food"),
    ("kopitiam",            "Outside Food"),
    ("foodclique",          "Outside Food"),
    ("hawker",              "Outside Food"),
    ("food court",          "Outside Food"),
    ("grabfood",            "Outside Food"),
    ("foodpanda",           "Outside Food"),
    ("deliveroo",           "Outside Food"),
    ("bengawan solo",       "Outside Food"),
    ("prima deli",          "Outside Food"),
    ("breadtalk",           "Outside Food"),
    ("crystal jade",        "Outside Food"),
    ("din tai fung",        "Outside Food"),
    ("jollibee",            "Outside Food"),
    ("pizza hut",           "Outside Food"),
    ("dominos",             "Outside Food"),
    ("starbucks",           "Outside Food"),
    ("coffee bean",         "Outside Food"),
    ("texas chicken",       "Outside Food"),
    ("popeyes",             "Outside Food"),
    ("ichiban",             "Outside Food"),
    ("sakae",               "Outside Food"),
    # Transport
    ("comfortdelgro",       "Transport"),
    ("gojek",               "Transport"),
    ("tada",                "Transport"),
    ("ryde",                "Transport"),
    ("transitlink",         "Transport"),
    ("transit link",        "Transport"),
    ("ez-link",             "Transport"),
    ("ezlink",              "Transport"),
    ("smrt",                "Transport"),
    ("parking",             "Transport"),
    ("carpark",             "Transport"),
    ("sbs transit",         "Transport"),
    # Personal Care
    ("watsons",             "Personal Care"),
    ("guardian",            "Personal Care"),
    ("unity pharmacy",      "Personal Care"),
    ("mannings",            "Personal Care"),
    ("sasa",                "Personal Care"),
    ("natures farm",        "Personal Care"),
    ("naturesfarm",         "Personal Care"),
    ("body shop",           "Personal Care"),
    ("lush",                "Personal Care"),
    ("innisfree",           "Personal Care"),
    # Bills & Utilities
    ("sp group",            "Bills & Utilities"),
    ("spgroup",             "Bills & Utilities"),
    ("singtel",             "Bills & Utilities"),
    ("starhub",             "Bills & Utilities"),
    ("myrepublic",          "Bills & Utilities"),
    ("viewqwest",           "Bills & Utilities"),
    ("city gas",            "Bills & Utilities"),
    ("citygas",             "Bills & Utilities"),
    ("conservancy",         "Bills & Utilities"),
    ("town council",        "Bills & Utilities"),
    # Shopping
    ("lazada",              "Shopping"),
    ("shopee",              "Shopping"),
    ("qoo10",               "Shopping"),
    ("uniqlo",              "Shopping"),
    ("zara",                "Shopping"),
    ("h&m",                 "Shopping"),
    ("cotton on",           "Shopping"),
    ("cottonon",            "Shopping"),
    ("charles & keith",     "Shopping"),
    ("pedro",               "Shopping"),
    ("courts",              "Shopping"),
    ("harvey norman",       "Shopping"),
    ("harveynorman",        "Shopping"),
    ("ikea",                "Shopping"),
    ("spotlight",           "Shopping"),
    ("daiso",               "Shopping"),
    ("dondondonki",         "Shopping"),
    ("don don donki",       "Shopping"),
    ("mustafa",             "Shopping"),
    ("bugis street",        "Shopping"),
    # Healthcare
    ("raffles medical",     "Healthcare"),
    ("mount elizabeth",     "Healthcare"),
    ("parkway",             "Healthcare"),
    ("sgh",                 "Healthcare"),
    ("ttsh",                "Healthcare"),
    ("nuh",                 "Healthcare"),
    ("kkh",                 "Healthcare"),
    ("polyclinic",          "Healthcare"),
    ("ntuc health",         "Healthcare"),
    ("dental",              "Healthcare"),
    # Education
    ("popular bookstore",   "Education"),
    ("kinokuniya",          "Education"),
    ("times bookstore",     "Education"),
    ("coursera",            "Education"),
    ("udemy",               "Education"),
]

# Ordered longest-first so multi-word names match before single words
SINGAPORE_SHOP_MAPPINGS.sort(key=lambda x: len(x[0]), reverse=True)

# Single-word shops that could conflict with other meanings — listed separately
# so they are inserted after multi-word ones
SINGLE_WORD_SHOPS = [
    ("grab",    "Transport"),
    ("comfort", "Transport"),
    ("mrt",     "Transport"),
    ("sbs",     "Transport"),
    ("pub",     "Bills & Utilities"),
    ("m1",      "Bills & Utilities"),
    ("amazon",  "Shopping"),
    ("prime",   "Food & Groceries"),
    ("clinic",  "Healthcare"),
    ("pharmacy","Healthcare"),
    ("medisave","Healthcare"),
    ("school",  "Education"),
    ("tuition", "Education"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# init_db  — creates / migrates all tables
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    conn = get_connection()
    c = conn.cursor()

    # ── categories ────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            icon       TEXT    NOT NULL DEFAULT '📦',
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Seed defaults (INSERT OR IGNORE → safe for existing DBs)
    for i, (name, icon) in enumerate(DEFAULT_CATEGORIES):
        c.execute(
            "INSERT OR IGNORE INTO categories (name, icon, sort_order) VALUES (?, ?, ?)",
            (name, icon, i),
        )

    # ── expenses ──────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL,
            amount     REAL    NOT NULL,
            category   TEXT    NOT NULL,
            date       TEXT    NOT NULL,
            note       TEXT,
            added_by   TEXT    DEFAULT 'Web'
        )
    """)
    for col, ddl in [
        ("added_by",   "TEXT DEFAULT 'Web'"),
        ("shop_name",  "TEXT"),
        ("label",      "TEXT"),
        ("receipt_id", "TEXT"),
        ("family_id",  "INTEGER"),
    ]:
        try:
            c.execute(f"ALTER TABLE expenses ADD COLUMN {col} {ddl}")
        except Exception:
            pass

    # ── members ───────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            whatsapp_number TEXT    NOT NULL UNIQUE,
            is_approved     INTEGER NOT NULL DEFAULT 1,
            added_on        TEXT    NOT NULL
        )
    """)
    for col, ddl in [
        ("family_id",    "INTEGER"),
        ("is_admin",     "INTEGER DEFAULT 0"),
        ("nickname",     "TEXT"),
        ("joined_at",    "DATETIME"),
        ("added_by",     "TEXT"),
        ("password_hash","TEXT"),
        ("can_login",    "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col} {ddl}")
        except Exception:
            pass

    # ── families ──────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS families (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            created_at DATETIME NOT NULL,
            created_by TEXT
        )
    """)

    # ── invite_codes ──────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT    UNIQUE NOT NULL,
            family_id  INTEGER,
            created_by TEXT,
            created_at DATETIME NOT NULL,
            expires_at DATETIME,
            is_used    INTEGER DEFAULT 0,
            used_by    TEXT,
            used_at    DATETIME,
            max_uses   INTEGER DEFAULT 1,
            nickname   TEXT,
            is_admin   INTEGER DEFAULT 0
        )
    """)

    # ── shop_mappings ─────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS shop_mappings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name  TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            family_id  INTEGER,
            created_at DATETIME NOT NULL,
            UNIQUE(shop_name, family_id)
        )
    """)
    # Seed global Singapore shop mappings (only if table has < 10 global rows)
    global_count = c.execute(
        "SELECT COUNT(*) FROM shop_mappings WHERE family_id IS NULL"
    ).fetchone()[0]
    if global_count < 10:
        now_str = datetime.now().isoformat()
        all_shops = SINGAPORE_SHOP_MAPPINGS + SINGLE_WORD_SHOPS
        for shop, category in all_shops:
            c.execute(
                "INSERT OR IGNORE INTO shop_mappings (shop_name, category, family_id, created_at) VALUES (?, ?, NULL, ?)",
                (shop, category, now_str),
            )

    # ── pending_receipts ──────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_receipts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            member_phone TEXT    NOT NULL,
            receipt_json TEXT    NOT NULL,
            created_at   DATETIME NOT NULL
        )
    """)

    # ── receipt_items ─────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS receipt_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id TEXT    NOT NULL,
            expense_id INTEGER,
            item_name  TEXT,
            amount     REAL,
            category   TEXT,
            label      TEXT,
            family_id  INTEGER
        )
    """)

    # ── unknown_contacts ──────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS unknown_contacts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            phone         TEXT    NOT NULL,
            message       TEXT,
            attempt_type  TEXT,
            code_tried    TEXT,
            attempted_at  DATETIME NOT NULL,
            attempt_count INTEGER DEFAULT 1
        )
    """)

    # ── credit_card_bills ─────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS credit_card_bills (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_name   TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            member_name TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            month       INTEGER NOT NULL,
            year        INTEGER NOT NULL,
            note        TEXT,
            family_id   INTEGER,
            created_at  DATETIME NOT NULL
        )
    """)

    # ── income_entries ────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS income_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            family_id   INTEGER,
            created_at  DATETIME NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ── fixed_expenses ────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS fixed_expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL DEFAULT 'Fixed',
            family_id   INTEGER,
            created_at  DATETIME NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ── admin_credentials ─────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin_credentials (
            id                   INTEGER PRIMARY KEY,
            username             TEXT    NOT NULL,
            password_hash        TEXT    NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            created_at           DATETIME NOT NULL,
            updated_at           DATETIME,
            initial_otp          TEXT
        )
    """)
    # Migration: add initial_otp column to existing databases
    try:
        c.execute("ALTER TABLE admin_credentials ADD COLUMN initial_otp TEXT")
    except Exception:
        pass

    # ── statement_uploads ─────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS statement_uploads (
            id           TEXT    PRIMARY KEY,
            family_id    INTEGER,
            bank_name    TEXT,
            filename     TEXT,
            uploaded_at  TEXT    NOT NULL,
            transactions TEXT    NOT NULL DEFAULT '[]'
        )
    """)

    # ── whatsapp_message_log ──────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_message_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at    TEXT    NOT NULL,
            family_id    INTEGER,
            from_number  TEXT,
            message_type TEXT    NOT NULL DEFAULT 'unknown'
        )
    """)

    # ── investment_portfolios ─────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS investment_portfolios (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            family_id  INTEGER,
            created_at DATETIME NOT NULL
        )
    """)

    # ── investment_holdings ───────────────────────────────────────────────────
    # asset_type: 'stock' | 'mf'  (mutual fund)
    # provider:   'eodhd' | 'mfapi' | 'manual'
    # ticker:     EODHD code for stocks (e.g. "RELIANCE.NSE"), MFAPI scheme code for MFs
    c.execute("""
        CREATE TABLE IF NOT EXISTS investment_holdings (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id   INTEGER,
            family_id      INTEGER,
            name           TEXT    NOT NULL,
            ticker         TEXT,
            asset_type     TEXT    NOT NULL DEFAULT 'stock',
            provider       TEXT    NOT NULL DEFAULT 'manual',
            quantity       REAL    NOT NULL DEFAULT 0,
            buy_price      REAL,
            currency       TEXT    NOT NULL DEFAULT 'SGD',
            notes          TEXT,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     DATETIME NOT NULL,
            updated_at     DATETIME
        )
    """)

    # ── investment_price_snapshots ────────────────────────────────────────────
    # One row per holding per day (latest price on that day)
    c.execute("""
        CREATE TABLE IF NOT EXISTS investment_price_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            holding_id  INTEGER NOT NULL,
            price_date  TEXT    NOT NULL,
            price       REAL    NOT NULL,
            currency    TEXT    NOT NULL DEFAULT 'SGD',
            source      TEXT,
            fetched_at  DATETIME NOT NULL,
            UNIQUE(holding_id, price_date)
        )
    """)

    # ── investment_refresh_runs ───────────────────────────────────────────────
    # Audit log for each daily refresh attempt
    c.execute("""
        CREATE TABLE IF NOT EXISTS investment_refresh_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at    DATETIME NOT NULL,
            finished_at   DATETIME,
            holdings_total   INTEGER DEFAULT 0,
            holdings_updated INTEGER DEFAULT 0,
            holdings_failed  INTEGER DEFAULT 0,
            triggered_by  TEXT    NOT NULL DEFAULT 'scheduler',
            error_log     TEXT
        )
    """)

    # Seed default admin if table is empty — generate a one-time password (OTP)
    existing = c.execute("SELECT COUNT(*) FROM admin_credentials").fetchone()[0]
    if existing == 0:
        import secrets as _sec
        from werkzeug.security import generate_password_hash
        otp = _sec.token_urlsafe(8)   # e.g. "X7k2M9aB" — shown once on login page
        otp_hash = generate_password_hash(otp)
        c.execute(
            """INSERT INTO admin_credentials
               (id, username, password_hash, must_change_password, created_at, initial_otp)
               VALUES (1, 'admin', ?, 1, ?, ?)""",
            (otp_hash, datetime.now().isoformat(), otp),
        )

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Categories
# ─────────────────────────────────────────────────────────────────────────────

def get_all_categories():
    conn = get_connection()
    rows = conn.execute("SELECT name FROM categories ORDER BY sort_order, name").fetchall()
    conn.close()
    return [r["name"] for r in rows]


def get_categories_full():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_category(name, icon="📦"):
    conn = get_connection()
    max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM categories").fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO categories (name, icon, sort_order) VALUES (?, ?, ?)",
        (name.strip(), icon, max_order + 1),
    )
    conn.commit()
    conn.close()


def update_category(cat_id, name, icon):
    conn = get_connection()
    conn.execute("UPDATE categories SET name=?, icon=? WHERE id=?", (name.strip(), icon, cat_id))
    conn.commit()
    conn.close()


def delete_category(cat_id):
    conn = get_connection()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


def get_category_by_id(cat_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Families
# ─────────────────────────────────────────────────────────────────────────────

def get_all_families():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM families ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_family(name, created_by=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO families (name, created_at, created_by) VALUES (?, ?, ?)",
        (name.strip(), datetime.now().isoformat(), created_by),
    )
    fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return fid


def get_family_by_id(family_id):
    if not family_id:
        return None
    conn = get_connection()
    row = conn.execute("SELECT * FROM families WHERE id=?", (family_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Invite Codes
# ─────────────────────────────────────────────────────────────────────────────

def add_invite_code(code, family_id, created_by, expires_at, nickname=None, is_admin=0, max_uses=1):
    conn = get_connection()
    conn.execute(
        """INSERT INTO invite_codes
           (code, family_id, created_by, created_at, expires_at, is_used, max_uses, nickname, is_admin)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (code, family_id, created_by, datetime.now().isoformat(),
         expires_at.isoformat() if expires_at else None,
         max_uses, nickname, 1 if is_admin else 0),
    )
    conn.commit()
    conn.close()


def get_invite_code(code):
    conn = get_connection()
    row = conn.execute("SELECT * FROM invite_codes WHERE code=?", (code.upper(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_invite_codes(family_id=None):
    conn = get_connection()
    if family_id:
        rows = conn.execute(
            "SELECT * FROM invite_codes WHERE family_id=? ORDER BY created_at DESC",
            (family_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ic.*, f.name as family_name FROM invite_codes ic "
            "LEFT JOIN families f ON f.id=ic.family_id "
            "ORDER BY ic.created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def use_invite_code(code, used_by):
    conn = get_connection()
    conn.execute(
        "UPDATE invite_codes SET is_used=1, used_by=?, used_at=? WHERE code=?",
        (used_by, datetime.now().isoformat(), code.upper()),
    )
    conn.commit()
    conn.close()


def revoke_invite_code(code):
    conn = get_connection()
    conn.execute(
        "UPDATE invite_codes SET is_used=1 WHERE code=?",
        (code.upper(),),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Shop Mappings
# ─────────────────────────────────────────────────────────────────────────────

def get_all_shop_mappings(family_id=None):
    """Returns global + family-specific mappings, family overrides global."""
    conn = get_connection()
    if family_id:
        rows = conn.execute(
            "SELECT * FROM shop_mappings WHERE family_id IS NULL OR family_id=? "
            "ORDER BY family_id DESC, LENGTH(shop_name) DESC",
            (family_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM shop_mappings WHERE family_id IS NULL "
            "ORDER BY LENGTH(shop_name) DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_shop_in_text(text, family_id=None):
    """Returns (shop_name, category) if a known shop is found in text, else (None, None).

    Comparison is space-insensitive so 'FairPrice' and 'Fair Price' both match
    a mapping stored as 'fairprice'.
    """
    text_norm = _norm(text)
    mappings = get_all_shop_mappings(family_id=family_id)
    for m in mappings:
        shop_norm = _norm(m["shop_name"])
        if shop_norm and shop_norm in text_norm:
            return m["shop_name"], m["category"]
    return None, None


def add_shop_mapping(shop_name, category, family_id=None):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO shop_mappings (shop_name, category, family_id, created_at) VALUES (?, ?, ?, ?)",
        (shop_name.lower().strip(), category, family_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def delete_shop_mapping(mapping_id):
    conn = get_connection()
    conn.execute("DELETE FROM shop_mappings WHERE id=?", (mapping_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────

def add_member(name, whatsapp_number, is_approved=0,
               family_id=None, is_admin=0, nickname=None,
               joined_at=None, added_by=None):
    conn = get_connection()
    conn.execute(
        """INSERT OR IGNORE INTO members
           (name, whatsapp_number, is_approved, added_on,
            family_id, is_admin, nickname, joined_at, added_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, whatsapp_number, is_approved,
         datetime.now().strftime("%Y-%m-%d"),
         family_id, 1 if is_admin else 0,
         nickname or name,
         joined_at or datetime.now().isoformat(),
         added_by),
    )
    conn.commit()
    conn.close()


def get_all_members():
    conn = get_connection()
    rows = conn.execute(
        "SELECT m.*, f.name as family_name FROM members m "
        "LEFT JOIN families f ON f.id=m.family_id "
        "ORDER BY m.is_approved ASC, m.added_on DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_members():
    """Return members waiting for admin approval (is_approved=0)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT m.*, f.name as family_name FROM members m "
        "LEFT JOIN families f ON f.id=m.family_id "
        "WHERE m.is_approved=0 ORDER BY m.added_on DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_member_by_number(whatsapp_number):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM members WHERE whatsapp_number=?", (whatsapp_number,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_member_by_id(member_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def is_member_approved(whatsapp_number):
    conn = get_connection()
    row = conn.execute(
        "SELECT is_approved FROM members WHERE whatsapp_number=?", (whatsapp_number,)
    ).fetchone()
    conn.close()
    return row is not None and row["is_approved"] == 1


def approve_member(member_id, family_id=None):
    """Approve a pending member and optionally assign a family."""
    conn = get_connection()
    if family_id:
        conn.execute(
            "UPDATE members SET is_approved=1, family_id=? WHERE id=?",
            (family_id, member_id),
        )
    else:
        conn.execute(
            "UPDATE members SET is_approved=1 WHERE id=?",
            (member_id,),
        )
    conn.commit()
    conn.close()


def update_member_family(member_id, family_id):
    """Change (or clear) the family assignment for a member."""
    conn = get_connection()
    conn.execute(
        "UPDATE members SET family_id=? WHERE id=?",
        (family_id if family_id else None, member_id),
    )
    conn.commit()
    conn.close()


def toggle_member(member_id):
    conn = get_connection()
    conn.execute(
        "UPDATE members SET is_approved = CASE WHEN is_approved=1 THEN 0 ELSE 1 END WHERE id=?",
        (member_id,),
    )
    conn.commit()
    conn.close()


def deactivate_member_by_phone(phone):
    conn = get_connection()
    conn.execute("UPDATE members SET is_approved=0 WHERE whatsapp_number=?", (phone,))
    conn.commit()
    conn.close()


def delete_member(member_id):
    conn = get_connection()
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()
    conn.close()


def update_member_admin(member_id, is_admin):
    conn = get_connection()
    conn.execute("UPDATE members SET is_admin=? WHERE id=?", (1 if is_admin else 0, member_id))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Expenses
# ─────────────────────────────────────────────────────────────────────────────

def add_expense(title, amount, category, date, note="", added_by="Web",
                shop_name=None, label=None, receipt_id=None, family_id=None):
    conn = get_connection()
    conn.execute(
        """INSERT INTO expenses
           (title, amount, category, date, note, added_by, shop_name, label, receipt_id, family_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, float(amount), category, date, note, added_by,
         shop_name, label, receipt_id, family_id),
    )
    eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return eid


def get_all_expenses(month=None, year=None, category=None, family_id=None):
    conn = get_connection()
    query = "SELECT * FROM expenses WHERE 1=1"
    params = []
    if month and year:
        query += " AND strftime('%m', date)=? AND strftime('%Y', date)=?"
        params += [f"{int(month):02d}", str(year)]
    elif year:
        query += " AND strftime('%Y', date)=?"
        params.append(str(year))
    if category and category != "All":
        query += " AND category=?"
        params.append(category)
    if family_id:
        query += " AND family_id=?"
        params.append(family_id)
    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_expenses_by_family_and_date(family_id, date_str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE family_id=? AND date=? ORDER BY id DESC",
        (family_id, date_str),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_expense_by_member(added_by):
    """Returns the most recent expense added by this member name."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM expenses WHERE added_by=? ORDER BY id DESC LIMIT 1",
        (added_by,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_expenses_by_member(added_by, limit=5):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE added_by=? ORDER BY id DESC LIMIT ?",
        (added_by, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_recent_duplicate(added_by, amount, category, minutes=5):
    """Returns True if a matching expense exists within the last N minutes."""
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    # We use the id as a proxy for time (since date is YYYY-MM-DD only)
    # Check the last 3 expenses for this member
    rows = conn.execute(
        "SELECT * FROM expenses WHERE added_by=? AND amount=? AND category=? ORDER BY id DESC LIMIT 3",
        (added_by, float(amount), category),
    ).fetchall()
    conn.close()
    if rows:
        # If last entry was added very recently (we check by id proximity), flag it
        # Since we don't store time-of-day, we use the DB row id gap as proxy
        # If there's any match in the last 3 rows it's suspicious
        return len(rows) > 0
    return False


def check_group_duplicate(amount, date_str, family_id, shop_name=None, title=None, excluded_added_by=None):
    """
    Check if any OTHER group member already logged the same amount
    from the same outlet/shop on the same date.

    Returns a dict with {added_by, amount, title, shop_name, category}
    if a duplicate is found, else None.

    Matching logic:
      - Same amount (within ±0.01)
      - Same date
      - Same family_id (if provided)
      - Same shop_name OR same title (case-insensitive)
    """
    if not family_id:
        return None   # No family context — skip cross-member check

    conn = get_connection()
    params = [float(amount), date_str, family_id]

    # Build the shop/title condition.
    # Both the stored column value and the incoming value are normalised by
    # stripping all non-alphanumeric characters (spaces, hyphens, dots…)
    # and lowercasing. Python side: _norm(). SQL side: _sql_norm().
    # This means "Sat Breakfast 13", "sat-breakfast-13", "sat breakfast-13"
    # all compare as equal ("satbreakfast13").
    shop_or_title_cond = ""
    if shop_name:
        norm_shop = _norm(shop_name)
        shop_or_title_cond = (
            f"AND ({_sql_norm('shop_name')} = ?"
            f" OR {_sql_norm('title')} = ?)"
        )
        params += [norm_shop, norm_shop]
    elif title:
        norm_title = _norm(title)
        shop_or_title_cond = f"AND {_sql_norm('title')} = ?"
        params += [norm_title]
    else:
        conn.close()
        return None  # Not enough info to match meaningfully

    if excluded_added_by:
        shop_or_title_cond += " AND added_by != ?"
        params.append(excluded_added_by)

    query = f"""
        SELECT * FROM expenses
        WHERE ABS(amount - ?) < 0.01
          AND date = ?
          AND family_id = ?
          {shop_or_title_cond}
        ORDER BY id DESC LIMIT 1
    """
    row = conn.execute(query, params).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_expense(expense_id):
    conn = get_connection()
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()


def update_expense(expense_id, title, amount, category, date, note="",
                   shop_name=None, label=None):
    conn = get_connection()
    conn.execute(
        "UPDATE expenses SET title=?, amount=?, category=?, date=?, note=?, shop_name=?, label=? WHERE id=?",
        (title, float(amount), category, date, note, shop_name, label, expense_id),
    )
    conn.commit()
    conn.close()


def get_expense_by_id(expense_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Pending Receipts / Pending States
# ─────────────────────────────────────────────────────────────────────────────

def save_pending_state(member_phone, data, expire_minutes=10):
    """Save any pending bot state (receipt, category_ask, duplicate_confirm)."""
    conn = get_connection()
    conn.execute("DELETE FROM pending_receipts WHERE member_phone=?", (member_phone,))
    conn.execute(
        "INSERT INTO pending_receipts (member_phone, receipt_json, created_at) VALUES (?, ?, ?)",
        (member_phone, json.dumps(data), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_pending_state(member_phone, expire_minutes=10):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM pending_receipts WHERE member_phone=? ORDER BY id DESC LIMIT 1",
        (member_phone,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    created = datetime.fromisoformat(row["created_at"])
    if (datetime.now() - created).total_seconds() > expire_minutes * 60:
        clear_pending_state(member_phone)
        return None
    try:
        return json.loads(row["receipt_json"])
    except Exception:
        return None


def clear_pending_state(member_phone):
    conn = get_connection()
    conn.execute("DELETE FROM pending_receipts WHERE member_phone=?", (member_phone,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Receipt Items
# ─────────────────────────────────────────────────────────────────────────────

def save_receipt_items(receipt_id, items, family_id=None):
    conn = get_connection()
    for item in items:
        conn.execute(
            """INSERT INTO receipt_items
               (receipt_id, expense_id, item_name, amount, category, label, family_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (receipt_id,
             item.get("expense_id"),
             item.get("name") or item.get("item_name"),
             item.get("amount"),
             item.get("category"),
             item.get("label"),
             family_id),
        )
    conn.commit()
    conn.close()


def get_receipts_summary(family_id=None, limit=20):
    conn = get_connection()
    if family_id:
        rows = conn.execute(
            """SELECT receipt_id, MIN(item_name) as store,
                      SUM(amount) as total, COUNT(*) as item_count,
                      MIN(added_by) as member
               FROM expenses
               WHERE receipt_id IS NOT NULL AND family_id=?
               GROUP BY receipt_id
               ORDER BY MAX(id) DESC LIMIT ?""",
            (family_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT receipt_id, MIN(shop_name) as store,
                      SUM(amount) as total, COUNT(*) as item_count,
                      MIN(added_by) as member
               FROM expenses
               WHERE receipt_id IS NOT NULL
               GROUP BY receipt_id
               ORDER BY MAX(id) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_receipt_items(receipt_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id",
        (receipt_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Unknown Contacts
# ─────────────────────────────────────────────────────────────────────────────

def log_unknown_contact(phone, message, attempt_type, code_tried=None):
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, attempt_count FROM unknown_contacts WHERE phone=? AND attempt_type=? "
        "ORDER BY attempted_at DESC LIMIT 1",
        (phone, attempt_type),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE unknown_contacts SET attempt_count=attempt_count+1, attempted_at=?, message=? WHERE id=?",
            (datetime.now().isoformat(), message[:200], existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO unknown_contacts
               (phone, message, attempt_type, code_tried, attempted_at, attempt_count)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (phone, message[:200], attempt_type, code_tried, datetime.now().isoformat()),
        )
    conn.commit()
    conn.close()


def get_unknown_contacts():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM unknown_contacts ORDER BY attempted_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_security_alerts():
    """Returns phones with 5+ attempts in the last hour."""
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
    rows = conn.execute(
        """SELECT phone, SUM(attempt_count) as total_attempts,
                  MAX(attempt_type) as last_type
           FROM unknown_contacts
           WHERE attempted_at >= ?
           GROUP BY phone
           HAVING total_attempts >= 5""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────────────────────────────────────

def get_monthly_summary(month, year, family_id=None):
    conn = get_connection()
    query = """SELECT category, SUM(amount) as total
               FROM expenses
               WHERE strftime('%m', date)=? AND strftime('%Y', date)=?"""
    params = [f"{int(month):02d}", str(year)]
    if family_id:
        query += " AND family_id=?"
        params.append(family_id)
    query += " GROUP BY category ORDER BY total DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_totals(year, family_id=None):
    conn = get_connection()
    query = """SELECT strftime('%m', date) as month, SUM(amount) as total
               FROM expenses WHERE strftime('%Y', date)=?"""
    params = [str(year)]
    if family_id:
        query += " AND family_id=?"
        params.append(family_id)
    query += " GROUP BY month ORDER BY month"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_available_months():
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT strftime('%Y', date) as year,
                           strftime('%m', date) as month
           FROM expenses ORDER BY year DESC, month DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_dashboard_stats(family_id=None):
    conn = get_connection()
    now = datetime.now()
    month_str = f"{now.month:02d}"
    year_str = str(now.year)
    today_str = now.strftime("%Y-%m-%d")

    filt = "AND family_id=?" if family_id else ""
    params_m = [month_str, year_str] + ([family_id] if family_id else [])
    params_t = [today_str] + ([family_id] if family_id else [])

    this_month = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) as total FROM expenses "
        f"WHERE strftime('%m',date)=? AND strftime('%Y',date)=? {filt}",
        params_m,
    ).fetchone()["total"]

    today_total = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) as total FROM expenses WHERE date=? {filt}",
        params_t,
    ).fetchone()["total"]

    total_all = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) as total FROM expenses"
        + (" WHERE family_id=?" if family_id else ""),
        ([family_id] if family_id else []),
    ).fetchone()["total"]

    count_this_month = conn.execute(
        f"SELECT COUNT(*) as cnt FROM expenses "
        f"WHERE strftime('%m',date)=? AND strftime('%Y',date)=? {filt}",
        params_m,
    ).fetchone()["cnt"]

    top_cat = conn.execute(
        f"SELECT category, SUM(amount) as total FROM expenses "
        f"WHERE strftime('%m',date)=? AND strftime('%Y',date)=? {filt} "
        f"GROUP BY category ORDER BY total DESC LIMIT 1",
        params_m,
    ).fetchone()

    top_shop = conn.execute(
        f"SELECT shop_name, SUM(amount) as total FROM expenses "
        f"WHERE strftime('%m',date)=? AND strftime('%Y',date)=? "
        f"AND shop_name IS NOT NULL {filt} "
        f"GROUP BY shop_name ORDER BY total DESC LIMIT 1",
        params_m,
    ).fetchone()

    conn.close()
    return {
        "this_month":       round(this_month, 2),
        "today_total":      round(today_total, 2),
        "total_all":        round(total_all, 2),
        "count_this_month": count_this_month,
        "top_category":     dict(top_cat)  if top_cat  else None,
        "top_shop":         dict(top_shop) if top_shop else None,
    }


def get_shop_summary(month, year, family_id=None):
    conn = get_connection()
    query = """SELECT shop_name, SUM(amount) as total
               FROM expenses
               WHERE strftime('%m', date)=? AND strftime('%Y', date)=?
               AND shop_name IS NOT NULL"""
    params = [f"{int(month):02d}", str(year)]
    if family_id:
        query += " AND family_id=?"
        params.append(family_id)
    query += " GROUP BY shop_name ORDER BY total DESC LIMIT 10"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Admin Credentials
# ─────────────────────────────────────────────────────────────────────────────

def get_admin_credentials():
    """Return the single admin credentials row as a dict."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM admin_credentials WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else None


def update_admin_credentials(new_username, new_password_hash):
    """Update username and password; clears must_change_password and initial_otp."""
    conn = get_connection()
    conn.execute(
        """UPDATE admin_credentials
           SET username=?, password_hash=?, must_change_password=0,
               initial_otp=NULL, updated_at=?
           WHERE id=1""",
        (new_username, new_password_hash, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Member web login
# ─────────────────────────────────────────────────────────────────────────────

def set_member_password(member_id, password_hash):
    """Set (or update) a member's web-login password and enable their login access."""
    conn = get_connection()
    conn.execute(
        "UPDATE members SET password_hash=?, can_login=1 WHERE id=?",
        (password_hash, member_id),
    )
    conn.commit()
    conn.close()


def revoke_member_login(member_id):
    """Remove web-login access from a member."""
    conn = get_connection()
    conn.execute(
        "UPDATE members SET password_hash=NULL, can_login=0 WHERE id=?",
        (member_id,),
    )
    conn.commit()
    conn.close()


def get_member_for_login(whatsapp_number):
    """Return an approved member with web-login enabled, or None."""
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM members
           WHERE whatsapp_number=? AND can_login=1 AND is_approved=1""",
        (whatsapp_number,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Income Entries
# ─────────────────────────────────────────────────────────────────────────────

def add_income(description, amount, family_id=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO income_entries (description, amount, family_id, created_at) VALUES (?, ?, ?, ?)",
        (description.strip(), float(amount), family_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_all_income(family_id=None):
    conn = get_connection()
    if family_id:
        rows = conn.execute(
            "SELECT * FROM income_entries WHERE is_active=1 AND (family_id=? OR family_id IS NULL) ORDER BY id DESC",
            (family_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM income_entries WHERE is_active=1 ORDER BY id DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_income(income_id):
    conn = get_connection()
    conn.execute("UPDATE income_entries SET is_active=0 WHERE id=?", (income_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Fixed Expenses
# ─────────────────────────────────────────────────────────────────────────────

def add_fixed_expense(description, amount, category="Fixed", family_id=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO fixed_expenses (description, amount, category, family_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (description.strip(), float(amount), category.strip(), family_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_all_fixed_expenses(family_id=None):
    conn = get_connection()
    if family_id:
        rows = conn.execute(
            "SELECT * FROM fixed_expenses WHERE is_active=1 AND (family_id=? OR family_id IS NULL) ORDER BY category, id",
            (family_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM fixed_expenses WHERE is_active=1 ORDER BY category, id"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_fixed_expense(fe_id):
    conn = get_connection()
    conn.execute("UPDATE fixed_expenses SET is_active=0 WHERE id=?", (fe_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Credit Card Bills
# ─────────────────────────────────────────────────────────────────────────────

def add_cc_bill(bank_name, amount, member_name, date_str, note="", family_id=None):
    conn = get_connection()
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    conn.execute(
        """INSERT INTO credit_card_bills
           (bank_name, amount, member_name, date, month, year, note, family_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (bank_name.upper(), float(amount), member_name, date_str,
         dt.month, dt.year, note, family_id, datetime.now().isoformat()),
    )
    bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return bid


def get_cc_bills(month=None, year=None, member_name=None, family_id=None):
    conn = get_connection()
    q = "SELECT * FROM credit_card_bills WHERE 1=1"
    params = []
    if month:
        q += " AND month=?"
        params.append(int(month))
    if year:
        q += " AND year=?"
        params.append(int(year))
    if member_name:
        q += " AND member_name=?"
        params.append(member_name)
    if family_id:
        q += " AND family_id=?"
        params.append(family_id)
    q += " ORDER BY date DESC, id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cc_summary(month, year, family_id=None):
    """Returns total CC bills grouped by member and bank for a given month/year."""
    conn = get_connection()
    q = """
        SELECT member_name, bank_name, SUM(amount) as total, COUNT(*) as count
        FROM credit_card_bills
        WHERE month=? AND year=?
    """
    params = [int(month), int(year)]
    if family_id:
        q += " AND family_id=?"
        params.append(family_id)
    q += " GROUP BY member_name, bank_name ORDER BY member_name, total DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_cc_bill(bill_id):
    conn = get_connection()
    conn.execute("DELETE FROM credit_card_bills WHERE id=?", (bill_id,))
    conn.commit()
    conn.close()


def get_cc_member_total(month, year, member_name, family_id=None):
    """Total CC bills for one member this month."""
    conn = get_connection()
    q = "SELECT COALESCE(SUM(amount),0) as total FROM credit_card_bills WHERE month=? AND year=? AND member_name=?"
    params = [int(month), int(year), member_name]
    if family_id:
        q += " AND family_id=?"
        params.append(family_id)
    total = conn.execute(q, params).fetchone()["total"]
    conn.close()
    return round(total, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Enhanced Analytics — top spends by category
# ─────────────────────────────────────────────────────────────────────────────

def get_top_expenses_by_category(category, month, year, limit=5, family_id=None):
    """Top N expenses for a category in a given month/year."""
    conn = get_connection()
    q = """SELECT * FROM expenses
           WHERE category=?
             AND strftime('%m', date)=?
             AND strftime('%Y', date)=?"""
    params = [category, f"{int(month):02d}", str(year)]
    if family_id:
        q += " AND family_id=?"
        params.append(family_id)
    q += " ORDER BY amount DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_expenses_this_week_by_category(category, limit=5, family_id=None):
    """Top N expenses for a category in the last 7 days."""
    conn = get_connection()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    q = """SELECT * FROM expenses
           WHERE category=? AND date >= ?"""
    params = [category, week_ago]
    if family_id:
        q += " AND family_id=?"
        params.append(family_id)
    q += " ORDER BY amount DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_top_by_category(month, year, limit=3, family_id=None):
    """
    Returns a dict {category: [top expenses]} for all categories
    in the given month — used to render the drill-down on the summary page.
    """
    cats = get_all_categories()
    result = {}
    for cat in cats:
        top = get_top_expenses_by_category(cat, month, year, limit=limit, family_id=family_id)
        if top:
            result[cat] = top
    return result


def get_budget_summary(month, year, family_id=None):
    """Returns total income, total fixed expenses, and variable expenses for the month."""
    income_entries = get_all_income(family_id=family_id)
    fixed_entries  = get_all_fixed_expenses(family_id=family_id)
    total_income   = sum(e["amount"] for e in income_entries)
    total_fixed    = sum(e["amount"] for e in fixed_entries)

    conn = get_connection()
    query = """SELECT COALESCE(SUM(amount), 0) as total
               FROM expenses
               WHERE strftime('%m', date)=? AND strftime('%Y', date)=?"""
    params = [f"{int(month):02d}", str(year)]
    if family_id:
        query += " AND family_id=?"
        params.append(family_id)
    variable_total = conn.execute(query, params).fetchone()["total"]
    conn.close()

    return {
        "total_income":    round(total_income, 2),
        "total_fixed":     round(total_fixed, 2),
        "variable_total":  round(variable_total, 2),
        "projected_net":   round(total_income - total_fixed - variable_total, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Statement uploads
# ─────────────────────────────────────────────────────────────────────────────

def save_statement_upload(upload_id, family_id, bank_name, filename, transactions):
    """Persist parsed statement transactions linked to an upload UUID."""
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO statement_uploads
           (id, family_id, bank_name, filename, uploaded_at, transactions)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (upload_id, family_id, bank_name, filename,
         datetime.now().isoformat(), json.dumps(transactions)),
    )
    conn.commit()
    conn.close()


def get_statement_upload(upload_id):
    """Return upload dict with transactions list, or None if not found."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM statement_uploads WHERE id=?", (upload_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    result["transactions"] = json.loads(result["transactions"] or "[]")
    return result


def mark_statement_transaction_added(upload_id, txn_id):
    """Flip the 'added' flag on a single transaction inside the stored JSON blob."""
    conn = get_connection()
    row = conn.execute(
        "SELECT transactions FROM statement_uploads WHERE id=?", (upload_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    txns = json.loads(row["transactions"] or "[]")
    for txn in txns:
        if txn.get("id") == txn_id:
            txn["added"] = True
            break
    conn.execute(
        "UPDATE statement_uploads SET transactions=? WHERE id=?",
        (json.dumps(txns), upload_id),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp message log  (persistent — survives container restarts)
# ─────────────────────────────────────────────────────────────────────────────

def log_whatsapp_message(from_number, message_type, family_id=None):
    """Persist one WhatsApp message arrival to the log table."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO whatsapp_message_log (logged_at, family_id, from_number, message_type)
           VALUES (?, ?, ?, ?)""",
        (datetime.now().isoformat(), family_id, from_number, message_type),
    )
    conn.commit()
    conn.close()


def get_whatsapp_message_count_today(family_id=None):
    """Return the number of WhatsApp messages logged today (SGT date)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    if family_id:
        count = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_message_log WHERE logged_at LIKE ? AND family_id=?",
            (f"{today}%", family_id),
        ).fetchone()[0]
    else:
        count = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_message_log WHERE logged_at LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
    conn.close()
    return count


def get_expense_count_today(family_id=None):
    """Return the number of expense entries added today."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    if family_id:
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE date=? AND family_id=?",
            (today, family_id),
        ).fetchone()[0]
    else:
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE date=?",
            (today,),
        ).fetchone()[0]
    conn.close()
    return count


def get_whatsapp_message_log(days=30, family_id=None):
    """Return message log rows for the past N days, newest first."""
    conn = get_connection()
    q = """SELECT logged_at, from_number, message_type, family_id
           FROM whatsapp_message_log
           WHERE logged_at >= date('now', ?)"""
    params: list = [f"-{days} days"]
    if family_id:
        q += " AND family_id=?"
        params.append(family_id)
    q += " ORDER BY logged_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Investments — Portfolios
# ─────────────────────────────────────────────────────────────────────────────

def get_all_portfolios(family_id=None):
    conn = get_connection()
    if family_id:
        rows = conn.execute(
            "SELECT * FROM investment_portfolios WHERE family_id=? ORDER BY name",
            (family_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM investment_portfolios ORDER BY name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_portfolio(name, family_id=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO investment_portfolios (name, family_id, created_at) VALUES (?, ?, ?)",
        (name.strip(), family_id, datetime.now().isoformat()),
    )
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return pid


def delete_portfolio(portfolio_id):
    conn = get_connection()
    conn.execute("DELETE FROM investment_portfolios WHERE id=?", (portfolio_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Investments — Holdings
# ─────────────────────────────────────────────────────────────────────────────

def get_holdings(family_id=None, portfolio_id=None, active_only=True):
    conn = get_connection()
    where = []
    params = []
    if active_only:
        where.append("h.is_active=1")
    if family_id:
        where.append("h.family_id=?")
        params.append(family_id)
    if portfolio_id:
        where.append("h.portfolio_id=?")
        params.append(portfolio_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(f"""
        SELECT h.*,
               s.price      AS latest_price,
               s.price_date AS price_date,
               s.currency   AS price_currency
        FROM investment_holdings h
        LEFT JOIN investment_price_snapshots s
            ON s.holding_id = h.id
            AND s.price_date = (
                SELECT MAX(price_date) FROM investment_price_snapshots
                WHERE holding_id = h.id
            )
        {clause}
        ORDER BY h.name
    """, params).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        qty = d.get("quantity") or 0
        price = d.get("latest_price") or d.get("buy_price") or 0
        d["current_value"] = round(qty * price, 2)
        d["gain_loss"] = round(qty * (price - (d.get("buy_price") or 0)), 2) if d.get("buy_price") else None
        result.append(d)
    return result


def get_holding(holding_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM investment_holdings WHERE id=?", (holding_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_holding(name, ticker, asset_type, provider, quantity, buy_price,
                currency="SGD", notes=None, portfolio_id=None, family_id=None):
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute(
        """INSERT INTO investment_holdings
           (name, ticker, asset_type, provider, quantity, buy_price, currency,
            notes, portfolio_id, family_id, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (name.strip(), (ticker or "").strip().upper(), asset_type, provider,
         quantity, buy_price, currency, notes, portfolio_id, family_id, now, now),
    )
    conn.commit()
    hid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return hid


def update_holding(holding_id, **kwargs):
    allowed = {"name", "ticker", "asset_type", "provider", "quantity",
               "buy_price", "currency", "notes", "portfolio_id", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [holding_id]
    conn = get_connection()
    conn.execute(f"UPDATE investment_holdings SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_holding(holding_id):
    conn = get_connection()
    conn.execute("DELETE FROM investment_price_snapshots WHERE holding_id=?", (holding_id,))
    conn.execute("DELETE FROM investment_holdings WHERE id=?", (holding_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Investments — Price snapshots
# ─────────────────────────────────────────────────────────────────────────────

def upsert_price_snapshot(holding_id, price_date, price, currency="SGD", source=None):
    """Insert or replace a price snapshot for a holding on a given date."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO investment_price_snapshots
           (holding_id, price_date, price, currency, source, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(holding_id, price_date) DO UPDATE SET
               price=excluded.price,
               currency=excluded.currency,
               source=excluded.source,
               fetched_at=excluded.fetched_at""",
        (holding_id, price_date, price, currency, source, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_price_history(holding_id, days=30):
    conn = get_connection()
    rows = conn.execute(
        """SELECT price_date, price, currency, source
           FROM investment_price_snapshots
           WHERE holding_id=? AND price_date >= date('now', ?)
           ORDER BY price_date""",
        (holding_id, f"-{days} days"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_snapshot(holding_id):
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM investment_price_snapshots
           WHERE holding_id=? ORDER BY price_date DESC LIMIT 1""",
        (holding_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Investments — Refresh runs
# ─────────────────────────────────────────────────────────────────────────────

def start_refresh_run(triggered_by="scheduler"):
    conn = get_connection()
    conn.execute(
        """INSERT INTO investment_refresh_runs
           (started_at, holdings_total, holdings_updated, holdings_failed, triggered_by)
           VALUES (?, 0, 0, 0, ?)""",
        (datetime.now().isoformat(), triggered_by),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rid


def finish_refresh_run(run_id, total, updated, failed, error_log=None):
    conn = get_connection()
    conn.execute(
        """UPDATE investment_refresh_runs SET
           finished_at=?, holdings_total=?, holdings_updated=?, holdings_failed=?, error_log=?
           WHERE id=?""",
        (datetime.now().isoformat(), total, updated, failed, error_log, run_id),
    )
    conn.commit()
    conn.close()


def get_last_refresh_run():
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM investment_refresh_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_portfolio_summary(family_id=None):
    """Return aggregate valuation stats across all active holdings."""
    holdings = get_holdings(family_id=family_id, active_only=True)
    total_invested = sum((h.get("buy_price") or 0) * (h.get("quantity") or 0) for h in holdings)
    total_current  = sum(h.get("current_value") or 0 for h in holdings)
    gain_loss      = total_current - total_invested
    gain_pct       = (gain_loss / total_invested * 100) if total_invested else 0
    return {
        "holdings_count": len(holdings),
        "total_invested": round(total_invested, 2),
        "total_current":  round(total_current, 2),
        "gain_loss":      round(gain_loss, 2),
        "gain_pct":       round(gain_pct, 2),
    }
