"""
routes/__init__.py — Import all route modules to trigger @app.route registrations.

Just importing these modules is enough — the decorators register the routes
on `app` (from extensions) at import time.
"""
from routes import auth          # noqa: F401
from routes import expenses      # noqa: F401
from routes import summary       # noqa: F401
from routes import budget        # noqa: F401
from routes import credit_cards  # noqa: F401
from routes import admin         # noqa: F401
from routes import whatsapp      # noqa: F401
from routes import investments   # noqa: F401
