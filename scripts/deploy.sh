#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — One-command deploy for Expense Tracker on EC2
# Usage: ./scripts/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e   # Exit immediately on any error

echo ""
echo "🚀 Deploying Expense Tracker..."
echo "───────────────────────────────"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
echo "📥 [1/5] Pulling latest code from git..."
git pull origin main

# ── 2. Rebuild the Docker image ───────────────────────────────────────────────
echo "🔨 [2/5] Building Docker image..."
docker compose build --no-cache app

# ── 3. Stop old containers gracefully ────────────────────────────────────────
echo "🛑 [3/5] Stopping old containers..."
docker compose down

# ── 4. Start new containers ───────────────────────────────────────────────────
echo "▶️  [4/5] Starting containers..."
docker compose up -d

# ── 5. Verify health ──────────────────────────────────────────────────────────
echo "⏳ [5/5] Waiting for app to become healthy (max 60s)..."
for i in $(seq 1 12); do
    sleep 5
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/health 2>/dev/null || echo "000")
    if [ "$HTTP_STATUS" = "200" ]; then
        echo ""
        echo "✅ Deploy successful! App is healthy."
        echo "───────────────────────────────"
        docker compose ps
        exit 0
    fi
    echo "   Attempt $i/12 — status: $HTTP_STATUS"
done

echo ""
echo "❌ Deploy failed — app did not become healthy within 60 seconds."
echo "   Check logs with: docker compose logs app"
docker compose logs --tail=30 app
exit 1
