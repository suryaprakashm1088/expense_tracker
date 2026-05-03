"""
services/expense_parser.py — WhatsApp free-text → expense dict parser.

  parse_expense_message(body, family_id=None) → dict or None

Accepted patterns
  "FairPrice 45.50"
  "grab 12"
  "spent 50 food lunch"
  "45.50 fairprice weekly groceries"
  "transport 8 mrt to work"
"""
import re
import database as db
from config import CATEGORY_KEYWORDS


def parse_expense_message(body, family_id=None):
    """Parse a WhatsApp message into expense components.

    Returns dict with keys: title, amount, category, shop_name, label
    Returns None if no valid amount is found.
    """
    text = body.strip()

    # Strip leading 'add' keyword
    if text.lower().startswith("add "):
        text = text[4:].strip()

    # Strip S$ / $ prefixes
    text_clean = re.sub(r"S\$|s\$", "", text)
    text_clean = text_clean.replace("$", "")

    # Normalise vendor-amount shorthand: "Fairprice-20" / "Fairprice_20" → "Fairprice 20"
    # Only replaces - or _ that sits between a letter and a digit (leaves "7-Eleven" intact)
    text_clean = re.sub(r'([a-zA-Z])[-_](\d)', r'\1 \2', text_clean)

    # 1. Extract amount (first positive number)
    amount = None
    amount_pattern = re.compile(r'\b(\d+(?:\.\d{1,2})?)\b')
    for match in amount_pattern.finditer(text_clean):
        val = float(match.group(1))
        if val > 0:
            amount = val
            text_clean = (text_clean[:match.start()] + text_clean[match.end():]).strip()
            break

    if amount is None:
        return None

    # 2. Check shop_mappings DB first
    shop_name, category = db.find_shop_in_text(text_clean, family_id=family_id)

    # 3. Fall back to keyword matching
    if not category:
        for token in text_clean.lower().split():
            token_clean = token.strip(",.!?")
            if token_clean in CATEGORY_KEYWORDS:
                category = CATEGORY_KEYWORDS[token_clean]
                break

    # 4. Build label from remaining words
    remaining_words = []
    for word in text_clean.split():
        w = word.lower().strip(",.!?")
        if shop_name and w in shop_name.lower():
            continue
        if w in CATEGORY_KEYWORDS:
            continue
        if w in ("spent", "on", "at", "for", "the", "a", "an"):
            continue
        remaining_words.append(word)
    label = " ".join(remaining_words).strip() or None

    # 5. Title: prefer shop_name, then label, then category
    title = shop_name.title() if shop_name else (label or category or "Expense")

    return {
        "title":     title,
        "amount":    amount,
        "category":  category or "Other",
        "shop_name": shop_name,
        "label":     label,
    }
