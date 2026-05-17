#!/bin/bash
# =============================================================================
# Event Map - Database Backup Script
#
# Creates a local backup at: ~/.event-map/backups/event-map-latest.sql.gz
# Each run replaces the previous latest backup (no accumulating timestamped files).
#
# Optional: refresh the repo baseline seed file (checked into git):
#   ./scripts/backup-db.sh --update-seed
#
# Usage:
#   ./scripts/backup-db.sh              # local neutral backup only
#   ./scripts/backup-db.sh --update-seed  # also refresh api/data/seed.sql
# =============================================================================

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

BACKUP_DIR="$HOME/.event-map/backups"
BACKUP_FILE="$BACKUP_DIR/event-map-latest.sql.gz"
SEED_FILE="$APP_DIR/api/data/seed.sql"

UPDATE_SEED=false
if [[ "$1" == "--update-seed" ]]; then
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

# --- Local neutral backup ----------------------------------------------------

mkdir -p "$BACKUP_DIR"

info "Writing local backup to: $BACKUP_FILE"
# Uses the container's own MYSQL_ROOT_PASSWORD env var — no host-side credential passing.
docker exec event-map-db sh -lc \
    'mysqldump -h127.0.0.1 -P3306 -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
info "Local backup complete. Size: $SIZE"

# --- Optional: refresh repo baseline seed file -------------------------------

if [ "$UPDATE_SEED" = true ]; then
    echo ""
    warn "Refreshing repo baseline seed file: $SEED_FILE"
    warn "This replaces api/data/seed.sql with a fresh dump of the live database."
    printf "Continue? [y/N] "
    read -r CONFIRM < /dev/tty || true
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        info "Seed refresh skipped."
    else
        docker exec event-map-db sh -lc \
            'mysqldump -h127.0.0.1 -P3306 -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
            > "$SEED_FILE"
        info "Seed file updated: $SEED_FILE"
        info "Stage and commit api/data/seed.sql when ready to record this as the repo baseline."
    fi
fi

echo ""
info "Done."
echo ""
echo "  Local backup:  $BACKUP_FILE"
if [ "$UPDATE_SEED" = true ]; then
echo "  Repo baseline: $SEED_FILE  (stage + commit when ready)"
fi
echo ""
echo "  To restore the local backup:"
echo "    zcat $BACKUP_FILE | docker exec -i event-map-db sh -lc 'mysql -h127.0.0.1 -P3306 -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \"\$MYSQL_DATABASE\"'"
