"""
services/ai_clients.py — Lazy-initialised API client factories.

  get_twilio_client()    → twilio.rest.Client or None
  get_anthropic_client() → anthropic.Anthropic or None
  get_category_from_ai() → DB category string or None

These return None (instead of raising) so callers can degrade gracefully when
the third-party services aren't configured.
"""
from extensions import app
from config import TWILIO_SID, TWILIO_AUTH_TOKEN, ANTHROPIC_API_KEY, CATEGORY_CHOICES


def get_twilio_client():
    """Return a Twilio REST client, or None if credentials aren't set."""
    if not TWILIO_SID or not TWILIO_AUTH_TOKEN:
        return None
    try:
        from twilio.rest import Client
        return Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
    except Exception:
        return None


def get_anthropic_client():
    """Return an Anthropic client, or None if the API key isn't set."""
    if not ANTHROPIC_API_KEY:
        app.logger.warning("Claude not configured: ANTHROPIC_API_KEY is missing from environment")
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as e:
        app.logger.error(f"Claude client init failed: {e}")
        return None


def get_category_from_ai(text):
    """Ask Claude Haiku to categorise an expense description.

    Returns a DB category name from CATEGORY_CHOICES, or None on failure.
    """
    ai = get_anthropic_client()
    if not ai:
        return None
    categories = [c[1] for c in CATEGORY_CHOICES]
    try:
        response = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{
                "role": "user",
                "content": (
                    f"Given the expense description '{text}', which category fits best? "
                    f"Options: {', '.join(categories)}. "
                    "Reply with ONLY the exact category name from the list."
                ),
            }],
        )
        result = response.content[0].text.strip()
        if result in categories:
            return result
    except Exception:
        pass
    return None
