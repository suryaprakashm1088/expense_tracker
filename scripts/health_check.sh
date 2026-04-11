#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# health_check.sh — Auto-restart if app goes down
# Recommended cron (every 5 minutes):
#   */5 * * * * /home/ubuntu/expense_tracker/scripts/health_check.sh >> /var/log/expense_health.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────

APP_DIR="/home/ubuntu/expense_tracker"
HEALTH_URL="http://localhost:5001/health"
LOG_TAG="[$(date '+%Y-%m-%d %H:%M:%S')] expense-tracker"

cd "$APP_DIR" || exit 1

# ── Check health endpoint ─────────────────────────────────────────────────────
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_STATUS" = "200" ]; then
    # App is healthy — silent success (don't spam logs)
    exit 0
fi

# ── App is down — log and restart ────────────────────────────────────────────
echo "$LOG_TAG — ❌ Health check FAILED (HTTP $HTTP_STATUS). Restarting..."

# Restart just the app container (keeps nginx running)
docker compose restart app

# Wait for it to come back
sleep 15
HTTP_AFTER=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_AFTER" = "200" ]; then
    echo "$LOG_TAG — ✅ App recovered after restart."
else
    echo "$LOG_TAG — ❌ App still down after restart (HTTP $HTTP_AFTER)."
    echo "$LOG_TAG —    Recent logs:"
    docker compose logs --tail=20 app
fi
