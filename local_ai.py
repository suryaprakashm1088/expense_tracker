"""
local_ai.py — Hybrid local AI integration

Three separate engines, each doing what it does best:

  VISION (primary)  → LM Studio  (qwen3-vl-4b or any vision model)
    Receipt photo scanning — OpenAI-compatible API, accepts base64 data URIs.
    API: http://localhost:1234/v1  (OpenAI-compatible format)

  VISION (fallback) → Ollama  (llava:13b)
    Receipt photo scanning — runs natively on Mac with Metal GPU.
    Ollama supports base64 image input (plain base64, no data URI prefix).
    API: http://host.docker.internal:11434/api/chat  (Ollama format)

  TEXT    → Docker Model Runner  (ai/llama3.2)
    Monthly expense summaries — built into Docker Desktop, no install needed.
    API: http://host.docker.internal:12434/engines/llama.cpp/v1  (OpenAI format)

Setup:
  # LM Studio (primary vision — recommended)
  Download LM Studio from https://lmstudio.ai
  Load a vision model (e.g. qwen3-vl-4b) and start the local server on port 1234.

  # Ollama (fallback vision)
  brew install ollama
  ollama pull llava          # or llava:13b for higher quality
  ollama serve               # keep running (or: brew services start ollama)

  # Docker Model Runner (text)
  docker desktop enable model-runner --tcp 12434
  docker model pull ai/llama3.2

Environment variables (docker-compose.local.yml):
  LM_STUDIO_URL          — default: http://host.docker.internal:1234/v1
  LM_STUDIO_VISION_MODEL — default: qwen3-vl-4b
  OLLAMA_URL             — default: http://host.docker.internal:11434
  OLLAMA_VISION          — default: llava
  MODEL_RUNNER_URL       — default: http://host.docker.internal:12434/engines/llama.cpp/v1
  DMR_TEXT_MODEL         — default: docker.io/ai/llama3.2:latest
"""

import os
import json
import re
import requests
import logging

logger = logging.getLogger("local_ai")

# ── LM Studio (primary vision) ───────────────────────────────────────────────
LM_STUDIO_URL          = os.getenv("LM_STUDIO_URL", "http://host.docker.internal:1234/v1").rstrip("/")
LM_STUDIO_VISION_MODEL = os.getenv("LM_STUDIO_VISION_MODEL", "qwen3-vl-4b")

# ── Ollama (fallback vision) ──────────────────────────────────────────────────
OLLAMA_URL    = os.getenv("OLLAMA_URL",    "http://host.docker.internal:11434")
VISION_MODEL  = os.getenv("OLLAMA_VISION", "llava")

# ── Docker Model Runner (text) ────────────────────────────────────────────────
MODEL_RUNNER_URL = os.getenv(
    "MODEL_RUNNER_URL",
    "http://host.docker.internal:12434/engines/llama.cpp/v1"
).rstrip("/")
TEXT_MODEL = os.getenv("DMR_TEXT_MODEL", "docker.io/ai/llama3.2:latest")

RECEIPT_PROMPT = (
    "You are a receipt scanner. Extract all expense items from this receipt image.\n"
    "Return ONLY valid JSON with no markdown, no explanation, no extra text:\n"
    '{"store": "string", "date": "YYYY-MM-DD or null", "receipt_total": 0.0, '
    '"subdivisions": [{"name": "string", "amount": 0.0, '
    '"category": "one of: Food & Groceries, Outside Food, Transport, Personal Care, '
    "Bills & Utilities, Shopping, Healthcare, Education, Other"
    '", "label": "short description or null"}]}\n'
    'If the image is not a receipt respond with: {"error": "not a receipt"}\n'
    'If the receipt is too unclear to read: {"error": "unclear receipt"}'
)


# ─────────────────────────────────────────────────────────────────────────────
# Connectivity checks
# ─────────────────────────────────────────────────────────────────────────────

def is_lmstudio_available() -> bool:
    """Return True if LM Studio server is reachable and has a vision model loaded."""
    try:
        r = requests.get(f"{LM_STUDIO_URL}/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def is_ollama_available() -> bool:
    """Return True if Ollama server is reachable (used for vision fallback)."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def is_available() -> bool:
    """Return True if Docker Model Runner is reachable (used for text)."""
    try:
        r = requests.get(f"{MODEL_RUNNER_URL}/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def get_loaded_models() -> list:
    """Return combined list of models from all engines."""
    models = []
    # LM Studio models
    try:
        r = requests.get(f"{LM_STUDIO_URL}/models", timeout=5)
        r.raise_for_status()
        models += [f"lmstudio:{m['id']}" for m in r.json().get("data", [])]
    except Exception:
        pass
    # Ollama models
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models += [f"ollama:{m['name']}" for m in r.json().get("models", [])]
    except Exception:
        pass
    # Docker Model Runner models
    try:
        r = requests.get(f"{MODEL_RUNNER_URL}/models", timeout=5)
        r.raise_for_status()
        models += [f"dmr:{m['id']}" for m in r.json().get("data", [])]
    except Exception:
        pass
    return models


# ─────────────────────────────────────────────────────────────────────────────
# LM Studio vision — receipt scanning (primary)
# ─────────────────────────────────────────────────────────────────────────────

def scan_receipt_lmstudio(image_b64: str, media_type: str = "image/jpeg") -> dict:
    """
    Send a base64-encoded receipt image to LM Studio (qwen3-vl-4b or similar).
    LM Studio exposes an OpenAI-compatible API. Vision models expect images as
    data URIs inside the content array:
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<b64>"}}

    Returns parsed dict:
      {"store": ..., "date": ..., "receipt_total": ..., "subdivisions": [...]}
    Raises Exception on network/model error.
    Raises json.JSONDecodeError if model returns non-JSON.
    """
    data_uri = f"data:{media_type};base64,{image_b64}"
    payload = {
        "model": LM_STUDIO_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": RECEIPT_PROMPT},
            ],
        }],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    logger.info(
        f"🖼️  Scanning receipt via LM Studio ({LM_STUDIO_VISION_MODEL}) at {LM_STUDIO_URL}"
    )
    r = requests.post(
        f"{LM_STUDIO_URL}/chat/completions",
        json=payload,
        timeout=120,
    )
    if not r.ok:
        logger.error(f"LM Studio {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown fences some models wrap output in
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw.strip())
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Ollama vision — receipt scanning (fallback)
# ─────────────────────────────────────────────────────────────────────────────

def scan_receipt(image_b64: str, media_type: str = "image/jpeg") -> dict:
    """
    Send a base64-encoded receipt image to Ollama (llava).
    Ollama's /api/chat accepts images as plain base64 strings (no data URI prefix).
    Returns parsed dict:
      {"store": ..., "date": ..., "receipt_total": ..., "subdivisions": [...]}
    Raises Exception on network/model error.
    Raises json.JSONDecodeError if model returns non-JSON.
    """
    payload = {
        "model":   VISION_MODEL,
        "messages": [{
            "role":    "user",
            "content": RECEIPT_PROMPT,
            "images":  [image_b64],   # plain base64, no data URI prefix
        }],
        "stream":  False,
        "options": {"temperature": 0.1},
    }
    logger.info(f"🖼️  Scanning receipt via Ollama ({VISION_MODEL}) at {OLLAMA_URL}")
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    if not r.ok:
        logger.error(f"Ollama {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    raw = r.json()["message"]["content"].strip()

    # Strip markdown fences some models wrap output in
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$",       "", raw.strip())
    return json.loads(raw)


# Aliases
scan_receipt_with_ollama = scan_receipt
scan_receipt_url = scan_receipt   # kept for any residual references


# ─────────────────────────────────────────────────────────────────────────────
# Docker Model Runner text — expense summaries
# ─────────────────────────────────────────────────────────────────────────────

def _dmr_chat(model: str, messages: list, timeout: int = 120) -> str:
    """POST to Docker Model Runner /chat/completions (OpenAI-compatible)."""
    payload = {
        "model":       model,
        "messages":    messages,
        "stream":      False,
        "temperature": 0.1,
    }
    url = f"{MODEL_RUNNER_URL}/chat/completions"
    logger.info(f"DMR request → model={model}")
    r = requests.post(url, json=payload, timeout=timeout)
    if not r.ok:
        logger.error(f"DMR {r.status_code} error: {r.text[:300]}")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def summarise_expenses(
    expenses: list,
    month_name: str,
    year: int,
    grand_total: float,
    category_data: list,
) -> str:
    """
    Generate a friendly natural-language monthly spending summary via Docker Model Runner.
    Returns a plain-text paragraph (3–4 sentences).
    """
    if not expenses:
        return f"No expenses recorded for {month_name} {year}."

    cat_lines = "\n".join(
        f"  - {r['category']}: ${r['total']:.2f} ({r.get('pct', 0):.1f}%)"
        for r in sorted(category_data, key=lambda x: x["total"], reverse=True)
    )
    top5 = sorted(expenses, key=lambda e: e["amount"], reverse=True)[:5]
    top_lines = "\n".join(
        f"  - {e['title']} ${e['amount']:.2f} [{e['category']}] on {e['date']}"
        for e in top5
    )

    prompt = (
        f"You are a friendly personal finance assistant. "
        f"Write a 3–4 sentence natural-language summary of this family's spending "
        f"for {month_name} {year}. Be warm, practical, and concise.\n\n"
        f"Stats:\n"
        f"  - Total spent: ${grand_total:.2f}\n"
        f"  - Number of transactions: {len(expenses)}\n"
        f"  - Average per day: ${grand_total/30:.2f}\n\n"
        f"Breakdown by category:\n{cat_lines}\n\n"
        f"Top 5 largest expenses:\n{top_lines}\n\n"
        f"In your summary:\n"
        f"  1. State the total and highest-spending category\n"
        f"  2. Note any interesting pattern or second-highest category\n"
        f"  3. Give one concrete, actionable saving tip based on the actual data\n\n"
        f"Write in flowing prose, no bullet points, no headers."
    )
    messages = [{"role": "user", "content": prompt}]
    return _dmr_chat(TEXT_MODEL, messages, timeout=60)


# Alias
summarise_expenses_with_ollama = summarise_expenses
