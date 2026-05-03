"""
services/receipt.py — Receipt photo handling: download → resize → AI scan → pending state.

  handle_receipt_photo(media_url, sender, member) → reply string
"""
import re
import json
import base64
import time
from datetime import datetime

import database as db
import local_ai as ollama_cl
from extensions import app
from config import TWILIO_SID, TWILIO_AUTH_TOKEN
from services.ai_clients import get_anthropic_client
try:
    from app_metrics import AI_SCAN_TOTAL, AI_SCAN_DURATION
    _METRICS = True
except Exception:
    _METRICS = False


def _resize_image_for_llm(image_bytes: bytes, media_type: str,
                           max_px: int = 512, quality: int = 80) -> tuple:
    """Resize a receipt image to fit within max_px × max_px.

    llava:7b crashes on large phone photos (3–5 MB). Keeping images ≤512px
    on the longest side prevents the llama runner OOM crash.
    Returns (new_bytes, 'image/jpeg').
    """
    try:
        from PIL import Image
        import io
        app.logger.info(f"📐 Original image size: {len(image_bytes)//1024} KB — resizing to {max_px}px max")
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        app.logger.info(
            f"📐 Resized image to {img.size[0]}×{img.size[1]} "
            f"({len(buf.getvalue())//1024} KB) for Ollama"
        )
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        app.logger.warning(f"Image resize failed ({e}), sending original")
        return image_bytes, media_type


def _scan_receipt_image(image_b64, media_type):
    """Scan a base64-encoded receipt image.

    Priority order:
      1. LM Studio (qwen3-vl-4b) — OpenAI-compatible local vision model
      2. Ollama (llava)          — local Metal GPU vision model
      3. Claude Vision           — cloud fallback (requires ANTHROPIC_API_KEY)

    Returns a parsed dict on success; raises Exception on total failure.
    """
    # 1. Try LM Studio first (fastest local option when loaded)
    if ollama_cl.is_lmstudio_available():
        engine = "lmstudio"
        t0 = time.time()
        try:
            app.logger.info(
                f"🖼️  Scanning receipt with LM Studio ({ollama_cl.LM_STUDIO_VISION_MODEL}) …"
            )
            result = ollama_cl.scan_receipt_lmstudio(image_b64, media_type)
            if _METRICS:
                AI_SCAN_TOTAL.labels(engine=engine, status="success").inc()
                AI_SCAN_DURATION.labels(engine=engine).observe(time.time() - t0)
            return result
        except Exception as e:
            if _METRICS:
                AI_SCAN_TOTAL.labels(engine=engine, status="failed").inc()
                AI_SCAN_DURATION.labels(engine=engine).observe(time.time() - t0)
            app.logger.warning(f"LM Studio receipt scan failed ({e}), trying Ollama …")

    # 2. Try Ollama vision (runs locally with Metal GPU on Mac)
    if ollama_cl.is_ollama_available():
        engine = "ollama"
        t0 = time.time()
        try:
            app.logger.info("🖼️  Scanning receipt with Ollama (llava) …")
            result = ollama_cl.scan_receipt(image_b64, media_type)
            if _METRICS:
                AI_SCAN_TOTAL.labels(engine=engine, status="success").inc()
                AI_SCAN_DURATION.labels(engine=engine).observe(time.time() - t0)
            return result
        except Exception as e:
            if _METRICS:
                AI_SCAN_TOTAL.labels(engine=engine, status="failed").inc()
                AI_SCAN_DURATION.labels(engine=engine).observe(time.time() - t0)
            app.logger.warning(f"Ollama receipt scan failed ({e}), trying Claude …")

    # 3. Fall back to Claude Vision
    ai = get_anthropic_client()
    if not ai:
        raise RuntimeError(
            "No AI service available (LM Studio unreachable, Ollama unreachable, "
            "Claude not configured)."
        )

    prompt = (
        "Extract all expenses from this receipt. "
        "Return ONLY valid JSON, no other text:\n"
        '{"store": "string", "date": "YYYY-MM-DD or null", "receipt_total": 0.0, '
        '"subdivisions": [{"name": "string", "amount": 0.0, '
        '"category": "one of [Food & Groceries, Outside Food, Transport, '
        'Personal Care, Bills & Utilities, Shopping, Healthcare, Education, Other]", '
        '"label": "short description or null"}]}\n'
        'If not a receipt return: {"error": "not a receipt"}\n'
        'If unclear return: {"error": "unclear receipt"}'
    )
    app.logger.info("🖼️  Scanning receipt with Claude Vision (fallback) …")
    t0 = time.time()
    try:
        response = ai.messages.create(
            model="claude-opus-4-6",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw)
        if _METRICS:
            AI_SCAN_TOTAL.labels(engine="claude", status="success").inc()
            AI_SCAN_DURATION.labels(engine="claude").observe(time.time() - t0)
        return result
    except Exception:
        if _METRICS:
            AI_SCAN_TOTAL.labels(engine="claude", status="failed").inc()
            AI_SCAN_DURATION.labels(engine="claude").observe(time.time() - t0)
        raise


def handle_receipt_photo(media_url, sender, member):
    """Download a receipt photo, resize it, scan with AI, and save pending state.

    Returns a reply string for the WhatsApp bot.
    """
    import requests as http_req

    # Download from Twilio
    try:
        resp = http_req.get(media_url, auth=(TWILIO_SID, TWILIO_AUTH_TOKEN), timeout=15)
        resp.raise_for_status()
        raw_bytes = resp.content
        media_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    except Exception:
        return "Could not download the image. Please try again."

    raw_bytes, media_type = _resize_image_for_llm(raw_bytes, media_type)
    image_b64 = base64.standard_b64encode(raw_bytes).decode("utf-8")

    try:
        data = _scan_receipt_image(image_b64, media_type)
    except json.JSONDecodeError:
        return "Could not read receipt data. Please type your expense manually."
    except Exception as e:
        app.logger.error(f"Receipt scan error: {e}")
        return "AI service unavailable. Please type your expense manually."

    if "error" in data:
        if data["error"] == "not a receipt":
            return (
                "This does not look like a receipt. "
                "Please send a clearer photo or type your expense manually."
            )
        return (
            "Receipt is hard to read. Please retake in better lighting "
            "or type expenses manually."
        )

    subdivisions = data.get("subdivisions", [])
    if not subdivisions:
        return "No items found in receipt. Please type your expense manually."

    store = data.get("store", "Unknown Store")
    date  = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    total = data.get("receipt_total") or sum(s.get("amount", 0) for s in subdivisions)

    # Save pending state so user can confirm / edit
    pending_data = {
        "type": "receipt",
        "store": store,
        "date": date,
        "total": total,
        "subdivisions": subdivisions,
        "family_id": member.get("family_id"),
    }
    db.save_pending_state(sender, pending_data)

    lines = [f"🧾 {store}", f"📅 {date}", ""]
    for i, item in enumerate(subdivisions, 1):
        amt  = item.get("amount", 0)
        name = item.get("name", "Item")
        cat  = item.get("category", "Other")
        lines.append(f"{i}. {name:<22} S${amt:.2f}")
        lines.append(f"   📂 {cat}")
    lines.append("─" * 32)
    lines.append(f"💰 Total: S${total:.2f}")
    lines.append("")
    lines.append("Reply YES to save all")
    lines.append("Reply NO to cancel")
    lines.append("Reply EDIT to change categories")

    return "\n".join(lines)
