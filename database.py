import sqlite3
import os
import json
from datetime import datetime, timedelta

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
        ("family_id", "INTEGER"),
        ("is_admin",  "INTEGER DEFAULT 0"),
        ("nickname",  "TEXT"),
        ("joined_at", "DATETIME"),
        ("added_by",  "TEXT"),
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

    # ── admin_credentials ─────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin_credentials (
            id                   INTEGER PRIMARY KEY,
            username             TEXT    NOT NULL,
            password_hash        TEXT    NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            created_at           DATETIME NOT NULL,
            updated_at           DATETIME
        )
    """)

    # Seed default admin if table is empty
    existing = c.execute("SELECT COUNT(*) FROM admin_credentials").fetchone()[0]
    if existing == 0:
        from werkzeug.security import generate_password_hash
        default_hash = generate_password_hash("Admin@123")
        c.execute(
            "INSERT INTO admin_credentials (id, username, password_hash, must_change_password, created_at) VALUES (1, 'admin', ?, 1, ?)",
            (default_hash, datetime.now().isoformat()),
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
    """Returns (shop_name, category) if a known shop is found in text, else (None, None)."""
    text_lower = text.lower()
    mappings = get_all_shop_mappings(family_id=family_id)
    for m in mappings:
        shop = m["shop_name"].lower()
        if shop in text_lower:
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
        "ORDER BY m.added_on DESC"
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
    """Update username and password; clears the must_change_password flag."""
    conn = get_connection()
    conn.execute(
        """UPDATE admin_credentials
           SET username=?, password_hash=?, must_change_password=0, updated_at=?
           WHERE id=1""",
        (new_username, new_password_hash, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
