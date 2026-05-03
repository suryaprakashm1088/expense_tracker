"""
services/statement_parser.py — Credit card / bank statement file parser.

Supports:
  • CSV  — DBS/POSB, OCBC, UOB, Citi, Standard Chartered, generic auto-detect
  • PDF  — pdfplumber text extraction → heuristic line parser
             falls back to LM Studio / Claude Vision for scanned/image PDFs

Each parsed transaction is returned as:
  {
    "id":          str (UUID — stable row key for front-end AJAX),
    "date":        "YYYY-MM-DD",
    "description": str,
    "amount":      float (debits only — positive),
    "category":    str  (auto-matched from shop_mappings or CATEGORY_KEYWORDS),
    "shop_name":   str  (matched vendor display name, or ""),
    "added":       False,
  }
"""

import csv
import io
import json
import logging
import re
import uuid
from datetime import datetime

import database as db
from config import CATEGORY_KEYWORDS

logger = logging.getLogger("statement_parser")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(s) -> float:
    """Convert '1,234.56' / '(123.00)' / '-45' → float. Returns 0.0 on failure."""
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(re.sub(r"[^0-9.\-]", "", s))
    except (ValueError, TypeError):
        return 0.0


def _parse_date(date_str: str) -> str:
    """Try multiple date formats → 'YYYY-MM-DD'. Returns today on failure."""
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
    for fmt in [
        "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%d-%m-%Y",
        "%m/%d/%Y", "%d %B %Y", "%d %b %y", "%d/%m/%y",
        "%d %b", "%d/%m",
    ]:
        try:
            parsed = datetime.strptime(date_str.strip(), fmt)
            # For formats without year, use current year
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            pass
    return datetime.now().strftime("%Y-%m-%d")


def _auto_category(description: str, family_id=None) -> tuple:
    """
    Match description against shop_mappings (DB), then CATEGORY_KEYWORDS.
    Returns (shop_name, category_str).
    """
    shop_name, category = db.find_shop_in_text(description, family_id=family_id)
    if not category:
        desc_lower = description.lower()
        for kw, cat in CATEGORY_KEYWORDS.items():
            if kw in desc_lower:
                category = cat
                break
    return (shop_name or ""), (category or "Other")


def _make_txn(date_str, description, amount, family_id=None):
    """
    Build a transaction dict. Returns None if amount ≤ 0 or description is blank.
    """
    amt = _to_float(amount) if not isinstance(amount, (int, float)) else float(amount or 0)
    if amt <= 0:
        return None
    desc = (description or "").strip()
    if not desc:
        return None

    shop_name, category = _auto_category(desc, family_id)
    return {
        "id":          str(uuid.uuid4()),
        "date":        _parse_date(str(date_str)),
        "description": desc,
        "amount":      round(amt, 2),
        "category":    category,
        "shop_name":   shop_name,
        "added":       False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────────────────────────────────────

def _detect_csv_format(headers: list) -> str:
    """Identify bank CSV format from the header row."""
    h = " ".join(str(x).strip().lower() for x in headers)
    if "debit amount" in h and "credit amount" in h:
        return "dbs"
    if "transaction description" in h and "withdrawals" in h and "deposits" in h:
        return "ocbc"
    if "withdrawals (sgd)" in h or "deposits (sgd)" in h:
        return "uob"
    if "debit" in h and "credit" in h and "description" in h:
        return "citi"
    if "amount" in h and "balance" in h and "description" in h:
        return "scb"
    return "generic"


def _hmap(headers: list) -> dict:
    """Lowercased header → column-index map."""
    return {str(h).strip().lower(): i for i, h in enumerate(headers)}


def _col(row, hm, *names) -> str:
    """Return first non-empty column match from a data row."""
    for name in names:
        idx = hm.get(name.lower())
        if idx is not None and idx < len(row):
            v = str(row[idx]).strip()
            if v and v not in ("-", "N/A", "n/a"):
                return v
    return ""


def _extract_row_fields(row, headers, fmt) -> tuple:
    """Return (date_str, description, amount_str) for a data row."""
    hm = _hmap(headers)

    if fmt == "dbs":
        date   = _col(row, hm, "transaction date")
        desc   = _col(row, hm, "transaction ref1", "transaction ref2",
                               "transaction ref3", "reference")
        amount = _col(row, hm, "debit amount")

    elif fmt == "ocbc":
        date   = _col(row, hm, "transaction date")
        desc   = _col(row, hm, "transaction description")
        amount = _col(row, hm, "withdrawals")

    elif fmt == "uob":
        date   = _col(row, hm, "transaction date")
        desc   = _col(row, hm, "description")
        amount = _col(row, hm, "withdrawals (sgd)")

    elif fmt == "citi":
        date   = _col(row, hm, "date")
        desc   = _col(row, hm, "description")
        amount = _col(row, hm, "debit", "amount")

    elif fmt == "scb":
        date   = _col(row, hm, "date", "transaction date")
        desc   = _col(row, hm, "description", "transaction description")
        raw_amt = _col(row, hm, "amount", "debit")
        # SCB uses negative for debits
        amount = str(abs(_to_float(raw_amt))) if raw_amt else ""

    else:  # generic fallback
        date = _col(row, hm,
                    "date", "transaction date", "trans date",
                    "posting date", "value date", "txn date")
        desc = _col(row, hm,
                    "description", "transaction description",
                    "particulars", "details", "narrative", "remarks")
        amount = _col(row, hm,
                      "debit", "debit amount", "withdrawal",
                      "withdrawals", "amount", "transaction amount",
                      "sgd amount", "local amount")

    return date, desc, amount


def _find_header_row(rows: list) -> tuple:
    """
    Scan for the first row that looks like a header.
    Returns (header_list, data_start_index).
    """
    KEY_SIGNALS = {
        "date", "description", "amount", "debit", "withdrawal",
        "transaction", "particulars", "balance",
    }
    for i, row in enumerate(rows):
        joined = " ".join(str(c).strip().lower() for c in row if c)
        hits = sum(1 for k in KEY_SIGNALS if k in joined)
        if hits >= 2:
            return row, i + 1
    # Fallback: treat first row as header
    return (rows[0] if rows else []), 1


def parse_csv_statement(file_bytes: bytes, family_id=None) -> list:
    """
    Parse a bank statement CSV file.
    Auto-detects format (DBS/OCBC/UOB/Citi/SCB/generic).
    Returns list of transaction dicts (debits only).
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")  # strip BOM
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []

    headers, data_start = _find_header_row(rows)
    fmt = _detect_csv_format(headers)
    logger.info(f"CSV bank format: {fmt}")

    transactions = []
    for row in rows[data_start:]:
        if not any(str(c).strip() for c in row):
            continue  # skip blank rows

        date_str, desc, amount_str = _extract_row_fields(row, headers, fmt)
        txn = _make_txn(date_str, desc, amount_str, family_id)
        if txn:
            transactions.append(txn)

    logger.info(f"CSV parsed {len(transactions)} debit transactions")
    return transactions


# ─────────────────────────────────────────────────────────────────────────────
# PDF parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_pdf_text_heuristic(text: str, family_id=None) -> list:
    """
    Line-by-line heuristic parser for raw PDF text.
    Looks for lines containing a date pattern + a monetary amount.
    """
    DATE_PAT   = (
        r"\b\d{1,2}[\s\-/]\w{3,9}[\s\-/]\d{2,4}"   # 01 Jan 2024 / 01-Jan-24
        r"|\b\d{1,2}/\d{2}/\d{2,4}"                  # 01/01/2024
        r"|\b\d{4}-\d{2}-\d{2}"                       # 2024-01-01
    )
    AMOUNT_PAT = r"\b\d{1,6}[,.]?\d{0,3}[.,]\d{2}\b"

    transactions = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 10:
            continue

        date_m  = re.search(DATE_PAT, line)
        amounts = re.findall(AMOUNT_PAT, line)
        if not date_m or not amounts:
            continue

        date_str   = date_m.group()
        amount_str = amounts[-1]  # rightmost amount is usually the debit column

        # Remove date and amounts to isolate description
        desc = line
        desc = re.sub(DATE_PAT, "", desc)
        for amt in amounts:
            desc = desc.replace(amt, "")
        desc = re.sub(r"\s{2,}", " ", desc).strip().strip("-+").strip()

        txn = _make_txn(date_str, desc, amount_str, family_id)
        if txn:
            transactions.append(txn)

    return transactions


def _parse_pdf_with_ai(file_bytes: bytes, filename: str = "", family_id=None) -> list:
    """
    Fallback: render first PDF page as image → send to LM Studio or Claude Vision.
    """
    import base64

    try:
        from extensions import app as _app
        _log = _app.logger
    except Exception:
        _log = logger

    STMT_PROMPT = (
        "You are a bank statement parser. Extract ALL debit/expense transactions "
        "from this bank statement image. "
        "Return ONLY a valid JSON array, no other text, no markdown:\n"
        '[{"date": "YYYY-MM-DD", "description": "merchant name", "amount": 0.00}, ...]\n'
        "Rules:\n"
        "- Include only charges/debits (money going out)\n"
        "- Exclude credits, payments, refunds\n"
        "- Use YYYY-MM-DD date format\n"
        "- Amount must be a positive number"
    )

    image_b64  = None
    media_type = "image/jpeg"

    # Try pdf2image (poppler-based) first
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=150)
        if pages:
            buf = io.BytesIO()
            pages[0].save(buf, format="JPEG", quality=80)
            image_b64 = base64.standard_b64encode(buf.getvalue()).decode()
    except Exception as e:
        _log.warning(f"pdf2image unavailable ({e})")

    # Try PyMuPDF (fitz) as alternative
    if not image_b64:
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pix = doc[0].get_pixmap(dpi=150)
            image_b64 = base64.standard_b64encode(pix.tobytes("jpeg")).decode()
        except Exception as e:
            _log.warning(f"PyMuPDF unavailable ({e})")

    if not image_b64:
        _log.warning("No PDF-to-image conversion available — cannot AI-parse PDF")
        return []

    raw = None

    # Try LM Studio first
    import local_ai as ai_cl
    if ai_cl.is_lmstudio_available():
        try:
            import requests as _req
            payload = {
                "model": ai_cl.LM_STUDIO_VISION_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                    {"type": "text", "text": STMT_PROMPT},
                ]}],
                "stream": False,
                "temperature": 0.1,
            }
            r = _req.post(f"{ai_cl.LM_STUDIO_URL}/chat/completions", json=payload, timeout=120)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            _log.warning(f"LM Studio PDF parse failed: {e}")

    # Fallback to Claude Vision
    if not raw:
        from services.ai_clients import get_anthropic_client
        anthropic = get_anthropic_client()
        if anthropic:
            try:
                resp = anthropic.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        }},
                        {"type": "text", "text": STMT_PROMPT},
                    ]}],
                )
                raw = resp.content[0].text.strip()
            except Exception as e:
                _log.warning(f"Claude PDF parse failed: {e}")

    if not raw:
        return []

    # Strip markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw.strip())

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        _log.warning("AI PDF parse returned non-JSON")
        return []

    transactions = []
    for item in (items if isinstance(items, list) else []):
        txn = _make_txn(
            item.get("date", ""),
            item.get("description", ""),
            item.get("amount", 0),
            family_id,
        )
        if txn:
            transactions.append(txn)

    _log.info(f"AI PDF parse found {len(transactions)} transactions")
    return transactions


def parse_pdf_statement(file_bytes: bytes, filename: str = "", family_id=None) -> list:
    """
    Parse a PDF bank statement.
    1. pdfplumber text extraction + line heuristics
    2. If < 2 results → AI fallback (LM Studio → Claude Vision)
    """
    transactions = []

    # Stage 1: pdfplumber text extraction
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            all_text = "\n".join(
                (page.extract_text() or "") for page in pdf.pages
            )
        if all_text.strip():
            transactions = _parse_pdf_text_heuristic(all_text, family_id)
            logger.info(f"pdfplumber found {len(transactions)} transactions")
    except ImportError:
        logger.warning("pdfplumber not installed — falling back to AI")
    except Exception as e:
        logger.warning(f"pdfplumber error ({e}) — falling back to AI")

    # Stage 2: AI fallback for scanned PDFs or when extraction is poor
    if len(transactions) < 2:
        logger.info("Switching to AI-based PDF parsing …")
        transactions = _parse_pdf_with_ai(file_bytes, filename, family_id)

    return transactions
