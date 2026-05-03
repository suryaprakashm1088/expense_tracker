"""
app.py — Thin entry point for the Expense Tracker Flask application.

Responsibilities:
  1. Import extensions (creates the Flask `app` instance + middleware)
  2. Import database and initialise the schema
  3. Import routes (triggers all @app.route registrations via routes/__init__.py)
  4. Start the APScheduler background scheduler
  5. Run the dev server when executed directly

Production:
  gunicorn app:app -b 0.0.0.0:5001
"""

# ── Bootstrap ──────────────────────────────────────────────────────────────────
from extensions import app          # creates app + CSRF + auth middleware
import database as db
db.init_db()                        # create/migrate SQLite schema on startup

# ── Register all routes (import triggers @app.route decorations) ───────────────
import routes                       # noqa: F401  (routes/__init__.py imports all submodules)

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import socket
    from services.scheduler import start_scheduler

    start_scheduler()

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    from config import DASHBOARD_URL
    print("\n🚀  Expense Tracker is running!")
    print(f"   Local:        http://127.0.0.1:5001")
    print(f"   Network:      http://{local_ip}:5001")
    print(f"   Dashboard URL: {DASHBOARD_URL}\n")

    app.run(host="0.0.0.0", debug=False, port=5001)
