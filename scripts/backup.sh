#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# backup.sh — SQLite backup script for Expense Tracker
# Recommended cron (daily at 2am):
#   0 2 * * * /home/ubuntu/expense_tracker/scripts/backup.sh >> /var/log/expense_backup.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────

BACKUP_DIR="/home/ubuntu/backups/expense_tracker"
DB_PATH="./data/expenses.db"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/expenses_$DATE.db"
KEEP_LAST=30   # Number of backups to retain

# ── Verify database exists ───────────────────────────────────────────────────
if [ ! -f "$DB_PATH" ]; then
    echo "❌ ERROR: Database not found at $DB_PATH"
    exit 1
fi

# ── Create backup directory ───────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"

# ── Safe SQLite backup (uses SQLite's .backup command — safe while app runs) ──
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

if [ $? -ne 0 ]; then
    echo "❌ ERROR: sqlite3 backup failed"
    exit 1
fi

# ── Compress backup ───────────────────────────────────────────────────────────
gzip "$BACKUP_FILE"
BACKUP_SIZE=$(du -sh "$BACKUP_FILE.gz" | cut -f1)

echo "✅ Backup saved: $BACKUP_FILE.gz ($BACKUP_SIZE)"

# ── Rotate — keep only last N backups ────────────────────────────────────────
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$KEEP_LAST" ]; then
    ls -t "$BACKUP_DIR"/*.gz | tail -n +"$((KEEP_LAST + 1))" | xargs rm -f
    echo "🗑️  Rotated old backups. Keeping last $KEEP_LAST."
fi

echo "📊 Total backups: $(ls -1 "$BACKUP_DIR"/*.gz 2>/dev/null | wc -l)"
