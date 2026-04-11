#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Expense Tracker – Quick Start Script
#  Usage:  bash run.sh
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║          💰  Expense Tracker  💰              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
  echo "❌  Python 3 not found. Please install Python 3.8+ first."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
  echo "🔧  Creating virtual environment..."
  python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install / upgrade dependencies quietly
echo "📦  Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ""
echo "✅  Setup complete!"
echo "🚀  Starting server at  http://127.0.0.1:5001"
echo "   Press Ctrl+C to stop."
echo ""

python3 app.py
