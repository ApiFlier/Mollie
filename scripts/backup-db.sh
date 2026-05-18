#!/bin/bash
# =============================================================================
# Event Map - Database Backup Script
#
# Creates a full backup (timestamped + latest pointer):
#   ~/.event-map/backups/event-map-YYYYmmdd-HHMMSS.sql.gz  (kept indefinitely)
#   ~/.event-map/backups/event-map-latest.sql.gz            (replaced each run)
#
# Usage:
#   ./scripts/backup-db.sh           # full backup (recommended)
#
# To refresh api/data/seed.sql (the public repo baseline), use:
#   scripts/commands/update-seed.sh
#
# The --update-seed flag is kept for backward compatibility but redirects
# to scripts/commands/update-seed.sh.
# =============================================================================

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

BACKUP_DIR="$HOME/.event-map/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
TS_BACKUP="$BACKUP_DIR/event-map-${STAMP}.sql.gz"
LATEST_BACKUP="$BACKUP_DIR/event-map-latest.sql.gz"

UPDATE_SEED=false
if [[ "${1:-}" == "--update-seed" ]]; then
    UPDATE_SEED=true
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Pre-flight checks -------------------------------------------------------

if [ ! -f "$ENV_FILE" ]; then
    error "No .env file found at $ENV_FILE. Run setup.sh first."
fi

if ! docker ps --format '{{.Names}}' | grep -qx "event-map-db"; then
    error "event-map-db container is not running. Start it with: docker compose up -d"
fi

# --- Full backup (timestamped + latest) --------------------------------------

mkdir -p "$BACKUP_DIR"

info "Writing backup..."
# Uses the container's own MYSQL_ROOT_PASSWORD env var — no host-side credential passing.
docker exec event-map-db sh -lc \
    'mysqldump -h127.0.0.1 -P3306 -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
    | gzip > "$TS_BACKUP"

if [ ! -s "$TS_BACKUP" ]; then
    rm -f "$TS_BACKUP"
    error "Backup file is empty — mysqldump produced no output. The latest backup was NOT replaced."
fi

cp "$TS_BACKUP" "$LATEST_BACKUP"

_size="$(du -h "$TS_BACKUP" | cut -f1)"
info "Backup complete. Size: ${_size}"
info "  Timestamped: $TS_BACKUP"
info "  Latest:      $LATEST_BACKUP"

# --- --update-seed: redirect to dedicated tool -------------------------------

if [ "$UPDATE_SEED" = true ]; then
    echo ""
    warn "--update-seed redirects to scripts/commands/update-seed.sh"
    warn "The dedicated tool excludes runtime event cache data and resets"
    warn "runtime timestamps for a clean public repo baseline."
    echo ""
    info "Running: scripts/commands/update-seed.sh"
    echo ""
    exec "$APP_DIR/scripts/commands/update-seed.sh"
fi

echo ""
info "Done."
echo ""
echo "  Timestamped backup: $TS_BACKUP"
echo "  Latest backup:      $LATEST_BACKUP"
echo ""
echo "  To restore:"
echo "    zcat $LATEST_BACKUP | docker exec -i event-map-db sh -lc \\"
echo "      'mysql -h127.0.0.1 -P3306 -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \"\$MYSQL_DATABASE\"'"
echo ""
echo "  To refresh api/data/seed.sql (public repo baseline):"
echo "    scripts/commands/update-seed.sh"
echo ""
