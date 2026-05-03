"""
services/cc_parser.py — Credit card bill message parser.

  parse_cc_bill_message(body) → {bank_name, amount} or None

Supported formats:
  "DBS CC BILL 500"
  "OCBC cc 300"
  "citi credit card 450.50"
  "pay UOB cc 1200"
"""
import re
from config import SG_CC_BANKS, CC_TOKENS


def parse_cc_bill_message(body):
    """Detect and parse a CC bill WhatsApp message.

    Returns dict {bank_name: str, amount: float} or None if not a CC bill.

    A message is considered a CC bill if it contains:
      1. At least one CC-signal token (cc, credit, card, bill, payment, pay)
      2. A known Singapore bank name (from SG_CC_BANKS)
      3. A positive numeric amount
    """
    text = body.strip().lower()
    # Strip currency symbols
    text = re.sub(r"s?\$", "", text)

    tokens = text.split()
    if not tokens:
        return None

    # 1. Must contain at least one CC-signal token
    if not any(t in CC_TOKENS for t in tokens):
        return None

    # 2. Find a known bank name
    bank_display = None
    for token in tokens:
        clean_tok = re.sub(r"[^a-z0-9]", "", token)
        if clean_tok in SG_CC_BANKS:
            bank_display = SG_CC_BANKS[clean_tok]
            break

    if not bank_display:
        return None

    # 3. Extract amount
    amount = None
    for token in tokens:
        try:
            val = float(re.sub(r"[^0-9.]", "", token))
            if val > 0:
                amount = val
                break
        except ValueError:
            pass

    if amount is None:
        return None

    return {"bank_name": bank_display, "amount": amount}
