#!/bin/bash
# =============================================================================
# Event Map — Refresh the repo baseline seed from the live database
#
# Run this after curating farms, places, and event source settings in the
# admin panel, when you want future fresh installs to start with the current
# curated data.
#
# Usage:
#   ./update-seed.sh           # interactive — asks before writing
#   ./update-seed.sh --yes     # noninteractive — skips confirmation prompt
#
# What this does:
#   1. Verifies Docker and the database are running
#   2. Creates a full timestamped safety backup of the entire database
#   3. Generates a selective seed (curated data only — no runtime cache)
#   4. Runs a public-repo safety scan
#   5. Shows exactly what will be written and asks for confirmation
#   6. Replaces api/data/seed.sql and prints review commands
#
# What the generated seed includes:
#   categories, locations, crops, notes, user_notes
#   event_sources (source keys, display names, enabled flags, coverage_days)
#   Full schema for all tables (including external_events — structure only)
#
# What the generated seed excludes:
#   external_events rows  — runtime fetch cache; repopulated automatically
#   event_sources runtime fields  — last_success_at, last_attempt_at, last_error
#                                   reset to NULL so the seed is clean
#
# Admin credentials:
#   Stored in .htpasswd on the host filesystem — NOT in the database.
#   This script does not touch .htpasswd and the seed never contains passwords.
#
# Public repo note:
#   api/data/seed.sql is committed to a PUBLIC GitHub repository.
#   Always inspect `git diff api/data/seed.sql` before committing.
# =============================================================================

set -euo pipefail

# Always run from the repo root (the directory containing this script).
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_FILE="$APP_DIR/api/data/seed.sql"
BACKUP_DIR="$HOME/.event-map/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
TS_BACKUP="$BACKUP_DIR/event-map-${STAMP}.sql.gz"
LATEST_BACKUP="$BACKUP_DIR/event-map-latest.sql.gz"

YES=false
for _arg in "$@"; do
    [[ "$_arg" == "--yes" ]] && YES=true
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() {
    echo -e "${RED}[ERROR]${NC} $1"
    echo ""
    if [ -n "${2:-}" ]; then
        echo "  Hint: $2"
        echo ""
    fi
    exit 1
}
step()  { echo -e "\n${BOLD}--- $1 ---${NC}"; }

echo ""
echo "================================================"
echo "   Event Map — Refresh Repo Baseline Seed"
echo "================================================"
echo ""
echo "  This will snapshot the live curated database into"
echo "  api/data/seed.sql for use by future fresh installs."
echo ""
echo "  api/data/seed.sql is committed to a PUBLIC GitHub repo."
echo "  A full backup will be created before anything is changed."
echo ""

# =============================================================================
# Step 1: Pre-flight checks
# =============================================================================
step "Step 1: Checking environment"

if ! command -v docker &>/dev/null; then
    error "Docker is not installed or not in PATH." \
          "Install Docker: https://docs.docker.com/engine/install/"
fi
info "Docker found: $(docker --version | head -1)"

if ! docker compose version &>/dev/null 2>&1; then
    error "Docker Compose v2 not found." \
          "Upgrade Docker or install the Compose plugin."
fi
info "Docker Compose found: $(docker compose version | head -1)"

if ! docker ps --format '{{.Names}}' | grep -qx "event-map-db"; then
    error "Container event-map-db is not running." \
          "Start it with: docker compose up -d"
fi
info "Container event-map-db is running."

if ! docker exec event-map-db sh -lc \
        'mysqladmin ping -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent' \
        >/dev/null 2>&1; then
    error "MySQL is not accepting connections inside event-map-db." \
          "Check logs with: docker logs event-map-db"
fi
info "MySQL TCP connection verified."

if [ ! -d "$APP_DIR/api/data" ]; then
    error "Directory api/data not found at $APP_DIR." \
          "Run this script from the repo root."
fi

# =============================================================================
# Step 2: Full timestamped safety backup
# =============================================================================
step "Step 2: Creating safety backup"

mkdir -p "$BACKUP_DIR"
info "Backing up to: $TS_BACKUP"

# Uses the container's own MYSQL_ROOT_PASSWORD — no host-side credential passing.
if ! docker exec event-map-db sh -lc \
        'mysqldump -h127.0.0.1 -P3306 -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
        2>/dev/null \
        | gzip > "$TS_BACKUP"; then
    rm -f "$TS_BACKUP"
    error "mysqldump failed — backup not created. Refusing to touch seed.sql." \
          "Check: docker logs event-map-db"
fi

if [ ! -s "$TS_BACKUP" ]; then
    rm -f "$TS_BACKUP"
    error "Backup file is empty — mysqldump produced no output. Refusing to touch seed.sql." \
          "Check: docker logs event-map-db"
fi

cp "$TS_BACKUP" "$LATEST_BACKUP"
_bk_size="$(du -h "$TS_BACKUP" | cut -f1)"
info "Backup complete: ${_bk_size}"
info "  Timestamped: $TS_BACKUP"
info "  Latest:      $LATEST_BACKUP"

# =============================================================================
# Step 3: Gather row counts for the warning prompt
# =============================================================================
step "Step 3: Checking table row counts"

_q() {
    docker exec event-map-db sh -lc \
        "mysql -h127.0.0.1 -P3306 -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \"\$MYSQL_DATABASE\" \
        -se \"$1\"" 2>/dev/null || echo "?"
}

_cat_count="$(_q "SELECT COUNT(*) FROM categories;")"
_loc_count="$(_q "SELECT COUNT(*) FROM locations;")"
_crop_count="$(_q "SELECT COUNT(*) FROM crops;")"
_note_count="$(_q "SELECT COUNT(*) FROM notes;")"
_unote_count="$(_q "SELECT COUNT(*) FROM user_notes;")"
_src_count="$(_q "SELECT COUNT(*) FROM event_sources;")"
_ext_count="$(_q "SELECT COUNT(*) FROM external_events;")"

info "  categories:      ${_cat_count} rows"
info "  locations:       ${_loc_count} rows"
info "  crops:           ${_crop_count} rows"
info "  notes:           ${_note_count} rows"
info "  user_notes:      ${_unote_count} rows"
info "  event_sources:   ${_src_count} rows"
info "  external_events: ${_ext_count} rows  (runtime cache — will be excluded)"

# =============================================================================
# Step 4: Generate selective seed into a temp file
# =============================================================================
step "Step 4: Generating seed"

echo "Running manifest export..."
docker exec event-map-app python scripts/export_seed_manifest.py

# Two-phase mysqldump:
#   Phase A — schema only for ALL tables (no data).
#             Ensures external_events table structure exists on fresh install.
#   Phase B — data for curated tables only (no schema).
#             external_events intentionally omitted.
#   Appended — UPDATE to reset event_sources runtime fields to NULL.

SEED_TMP="$(mktemp /tmp/event-map-seed-XXXXXX.sql)"
trap 'rm -f "$SEED_TMP"' EXIT

{
    # Use echo for SQL comment lines (-- prefix) to avoid printf misinterpreting
    # the leading dashes as option flags.
    echo "-- ============================================================"
    echo "-- Event Map — repo baseline seed"
    echo "-- Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "--"
    echo "-- This file is committed to a PUBLIC GitHub repository."
    echo "-- It does NOT contain runtime event cache or private data."
    echo "-- Admin credentials are managed by .htpasswd (not in DB)."
    echo "-- ============================================================"
    echo ""

    # Phase A: full schema, no data
    docker exec event-map-db sh -lc \
        'mysqldump -h127.0.0.1 -P3306 -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --single-transaction --no-data --skip-comments "$MYSQL_DATABASE"' \
        2>/dev/null

    echo ""
    echo "-- ============================================================"
    echo "-- Curated baseline data"
    echo "-- external_events excluded (runtime cache, repopulated on refresh)"
    echo "-- ============================================================"
    echo ""

    # Phase B: data for curated tables only, no schema
    docker exec event-map-db sh -lc \
        'mysqldump -h127.0.0.1 -P3306 -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --single-transaction --no-create-info --skip-comments \
        "$MYSQL_DATABASE" \
        categories crops locations notes user_notes event_sources' \
        2>/dev/null

    echo ""
    echo "-- Reset event_sources runtime state."
    echo "-- These are populated by the running app; they should not"
    echo "-- ship as stale timestamps in a public baseline seed."
    printf 'UPDATE `event_sources`\n'
    printf '  SET `last_success_at` = NULL,\n'
    printf '      `last_attempt_at` = NULL,\n'
    printf '      `last_error`      = NULL;\n'
    echo ""

} > "$SEED_TMP"

# --- Structural verification -------------------------------------------------

if [ ! -s "$SEED_TMP" ]; then
    error "Generated seed is empty — mysqldump may have failed."
fi

if ! grep -q "CREATE TABLE" "$SEED_TMP"; then
    error "Seed contains no CREATE TABLE statements — dump may have failed."
fi

# external_events schema must be present (fresh-install table creation)
if ! grep -q "CREATE TABLE.*\`external_events\`" "$SEED_TMP"; then
    error "Seed is missing external_events CREATE TABLE — schema dump incomplete."
fi

# external_events data must NOT be present
if grep -q "INSERT INTO \`external_events\`" "$SEED_TMP"; then
    error "Seed unexpectedly contains external_events INSERT data. Aborting for safety."
fi

# external_event_user_state data (personal saved/hidden history) must NOT be present
if grep -q "INSERT INTO \`external_event_user_state\`" "$SEED_TMP"; then
    error "Seed unexpectedly contains external_event_user_state INSERT data. Aborting for safety."
fi

# Runtime reset must be present
if ! grep -q "last_success_at.*NULL" "$SEED_TMP"; then
    error "Seed is missing the event_sources runtime reset statement."
fi

_seed_bytes="$(wc -c < "$SEED_TMP")"
_seed_lines="$(wc -l < "$SEED_TMP")"
info "Seed generated: ${_seed_bytes} bytes, ${_seed_lines} lines"

# =============================================================================
# Step 5: Public-repo safety scan
# =============================================================================
step "Step 5: Safety scan"

_scan_problems=0
_scan_notes=()

for _pattern in "password" "secret" "token" "api_key" "session" "htpasswd"; do
    _hits="$(grep -ic "$_pattern" "$SEED_TMP" 2>/dev/null || true)"
    if [ "${_hits:-0}" -gt 0 ]; then
        # Show the matching lines for review
        _lines="$(grep -in "$_pattern" "$SEED_TMP" | head -3 | sed 's/^/    /')"
        warn "Found ${_hits} line(s) matching '${_pattern}':"
        echo "$_lines"
        _scan_notes+=("$_pattern: ${_hits} hit(s)")
        _scan_problems=$((_scan_problems + 1))
    fi
done

if [ "$_scan_problems" -eq 0 ]; then
    info "Safety scan passed — no sensitive keywords detected."
else
    warn ""
    warn "Safety scan found ${_scan_problems} pattern(s) above."
    warn "Review the lines shown. Comments and schema column names"
    warn "are expected; actual credential values are not."
    warn ""
fi

# =============================================================================
# Step 6: Confirmation prompt
# =============================================================================
step "Step 6: Confirm replacement"

echo ""
echo -e "${YELLOW}${BOLD}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}${BOLD}  ║              PUBLIC REPO WARNING                        ║${NC}"
echo -e "${YELLOW}${BOLD}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo    "  This will replace:"
echo    "    $SEED_FILE"
echo ""
echo    "  Anything in this file may be committed to the public"
echo    "  GitHub repository and become permanently visible."
echo ""
echo    "  A full safety backup was created at:"
echo    "    $TS_BACKUP"
echo    "    $LATEST_BACKUP"
echo ""
echo -e "  ${BOLD}Included tables (curated data):${NC}"
printf  "    %-16s %s rows\n" "categories"  "${_cat_count}"
printf  "    %-16s %s rows\n" "locations"   "${_loc_count}"
printf  "    %-16s %s rows\n" "crops"       "${_crop_count}"
printf  "    %-16s %s rows\n" "notes"       "${_note_count}"
printf  "    %-16s %s rows\n" "user_notes"  "${_unote_count}"
printf  "    %-16s %s rows  (runtime fields reset to NULL)\n" \
                              "event_sources" "${_src_count}"
echo ""
echo -e "  ${BOLD}Excluded runtime data:${NC}"
printf  "    %-16s %s rows  (runtime cache — excluded entirely)\n" \
                              "external_events" "${_ext_count}"
echo ""
echo    "  Credentials: .htpasswd lives on the host, not in the DB."
echo    "               This seed contains no passwords."
echo ""

if [ "$_scan_problems" -gt 0 ]; then
    warn "  Safety scan found ${_scan_problems} keyword pattern(s) above — review before confirming."
    echo ""
fi

if [ "$YES" = true ]; then
    info "  --yes flag set, skipping prompt."
else
    printf "  Continue and replace api/data/seed.sql? [y/N] "
    CONFIRM=""
    read -r CONFIRM < /dev/tty || true
    echo ""
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        info "Cancelled. No files were changed."
        info "Safety backup preserved at: $TS_BACKUP"
        echo ""
        exit 0
    fi
fi

# =============================================================================
# Step 7: Write seed file
# =============================================================================
step "Step 7: Writing seed file"

cp "$SEED_TMP" "$SEED_FILE"
info "api/data/seed.sql updated."

# =============================================================================
# Done
# =============================================================================
echo ""
echo "================================================"
echo -e "${GREEN}  Seed refresh complete${NC}"
echo "================================================"
echo ""
echo "  Safety backup (timestamped):"
echo "    $TS_BACKUP"
echo "  Safety backup (latest):"
echo "    $LATEST_BACKUP"
echo ""
echo "  Seed file:"
echo "    $SEED_FILE"
echo "    ${_seed_bytes} bytes, ${_seed_lines} lines"
echo ""
echo "  Included:   ${_loc_count} locations, ${_crop_count} crops,"
echo "              ${_cat_count} categories, ${_src_count} event sources"
echo "  Excluded:   ${_ext_count} external_events rows (runtime cache)"
echo "  Reset:      event_sources runtime timestamps → NULL"
echo ""
echo -e "${YELLOW}${BOLD}  Review before committing — this repo is public:${NC}"
echo ""
echo "    git diff --stat"
echo "    git diff -- api/data/seed.sql"
echo "    git status --short"
echo ""
echo "  Commit only if the contents look correct:"
echo ""
echo "    git add api/data/seed.sql"
echo "    git commit -m 'Refresh repo baseline seed from curated database'"
echo ""
