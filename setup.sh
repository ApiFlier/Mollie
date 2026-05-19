#!/bin/bash
# =============================================================================
# Event Map - Fresh Deployment Setup Script
# Usage: chmod +x setup.sh && ./setup.sh
# =============================================================================

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
HTPASSWD_FILE="$APP_DIR/.htpasswd"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ---------------------------------------------------------------------------
# Print diagnostics when MySQL readiness times out.
# ---------------------------------------------------------------------------
_db_timeout_diagnostics() {
    echo ""
    warn "MySQL readiness timeout — diagnostics:"
    echo ""
    echo "  Running containers (filter: event-map):"
    docker ps --filter name=event-map
    echo ""
    echo "  DB container state / health:"
    docker inspect --format '{{.Name}}  state={{.State.Status}}  health={{.State.Health.Status}}' \
        event-map-db 2>/dev/null || true
    echo ""
    echo "  Recent DB logs (last 120 lines):"
    docker logs --tail=120 event-map-db 2>&1
    echo ""
    warn "On low-resource machines (Oracle Always Free VPS), MySQL may need several"
    warn "minutes to initialize on first start. If the logs above show MySQL still"
    warn "starting, wait a moment and re-run: ./setup.sh"
}

# ---------------------------------------------------------------------------
# Wait until MySQL inside the DB container is accepting TCP connections.
# Uses docker inspect to poll the health status (which uses TCP in the
# docker-compose healthcheck), then does a belt-and-suspenders TCP ping.
# ---------------------------------------------------------------------------
wait_for_db_healthy() {
    local _max=300 _waited=0
    info "Waiting for MySQL to become ready (timeout ${_max}s)..."
    info "Note: first startup on a small or low-resource VPS can take several minutes."

    # Phase 1: wait for Docker's health check to report healthy.
    # The compose healthcheck uses TCP (-h127.0.0.1), so "healthy" means the
    # port is open — not just that the container process started.
    until [ "$(docker inspect --format '{{.State.Health.Status}}' event-map-db 2>/dev/null)" = "healthy" ]; do
        if [ "$_waited" -ge "$_max" ]; then
            _db_timeout_diagnostics
            error "event-map-db did not become healthy within ${_max}s."
        fi
        sleep 5
        _waited=$((_waited + 5))
        if ((_waited % 15 == 0)); then
            info "  Still waiting for MySQL... ${_waited}s elapsed"
        fi
    done

    # Phase 2: belt-and-suspenders — confirm TCP is accepting connections.
    info "Docker health check passed (${_waited}s). Verifying TCP connectivity..."
    local _tcp_waited=0 _tcp_max=60
    until docker exec event-map-db sh -lc \
            'mysqladmin ping -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent' \
            >/dev/null 2>&1; do
        if [ "$_tcp_waited" -ge "$_tcp_max" ]; then
            _db_timeout_diagnostics
            error "MySQL TCP port not ready ${_tcp_max}s after health check passed."
        fi
        sleep 3
        _tcp_waited=$((_tcp_waited + 3))
        info "  TCP not yet ready... ${_tcp_waited}s"
    done

    info "MySQL is ready and accepting TCP connections (waited $((_waited + _tcp_waited))s total)."
}

# ---------------------------------------------------------------------------
# Import a SQL file into the DB container.
# Credentials come from the container's own environment variables —
# no host-side credential passing or local mysql client needed.
# Usage: import_sql_container /path/to/file.sql
# ---------------------------------------------------------------------------
import_sql_container() {
    local _sql_file="$1"
    if ! docker exec -i event-map-db sh -lc \
            'mysql -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
            < "$_sql_file"; then
        echo ""
        echo -e "${RED}[ERROR]${NC} SQL import failed: $_sql_file"
        echo ""
        echo "  Container status:"
        docker compose ps
        echo ""
        echo "  Recent DB logs:"
        docker compose logs --tail=30 db
        exit 1
    fi
}

find_open_port() {
    local port=$1
    while ss -tuln | grep -q ":${port} "; do
        port=$((port + 1))
    done
    echo $port
}

echo ""
echo "================================================"
echo "   Event Map - Setup"
echo "================================================"
echo ""

# --- Preflight checks ---
if [ ! -f "$APP_DIR/docker-compose.yml" ]; then
    error "docker-compose.yml not found in $APP_DIR. Did you clone correctly?"
fi
if ! command -v docker &> /dev/null; then
    error "Docker is not installed. Install it first: https://docs.docker.com/engine/install/"
fi
if ! docker compose version &> /dev/null; then
    error "Docker Compose not found. Make sure you have Docker Compose v2 installed."
fi
if ! command -v htpasswd &> /dev/null; then
    info "Installing apache2-utils for htpasswd..."
    sudo apt update -q && sudo apt install -y apache2-utils
fi

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 1: Remove old containers ---"
echo ""

# Stop and remove any legacy or current containers so their ports are freed
# before we select a port. This also prevents Docker naming conflicts.
for CONTAINER in mollies-app mollies-db event-map-app event-map-db; do
    if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
        info "Stopping and removing: $CONTAINER"
        docker stop "${CONTAINER}" 2>/dev/null || true
        docker rm   "${CONTAINER}" 2>/dev/null || true
    fi
done

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 2: Generate .env ---"
echo ""

# Read existing values one by one — do NOT export the old .env to the shell.
# Exporting would let old values override the newly chosen port when Docker
# Compose runs (shell env takes precedence over the .env file).
if [ -f "$ENV_FILE" ]; then
    _OLD_MYSQL=$(grep "^MYSQL_ROOT_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)
    _OLD_DB=$(grep "^DB_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)
    _OLD_SECRET=$(grep "^FLASK_SECRET=" "$ENV_FILE" | cut -d= -f2-)
    _OLD_PORT=$(grep "^APP_PORT=" "$ENV_FILE" | cut -d= -f2-)
    _OLD_HOME_LAT=$(grep "^HOME_LAT=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')
    _OLD_HOME_LNG=$(grep "^HOME_LNG=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')
fi

MYSQL_PASS=${_OLD_MYSQL:-$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")}
DB_PASS=${_OLD_DB:-$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")}
FLASK_SECRET=${_OLD_SECRET:-$(python3 -c "import secrets; print(secrets.token_hex(32))")}
HOME_LAT_VAL=${_OLD_HOME_LAT:-40.487993}
HOME_LNG_VAL=${_OLD_HOME_LNG:--79.805208}

# Old containers are stopped at this point, so their ports are free.
PREF_APP_PORT=${_OLD_PORT:-8090}
ACTUAL_APP_PORT=$(find_open_port $PREF_APP_PORT)

cat > "$ENV_FILE" <<ENVEOF
MYSQL_ROOT_PASSWORD=${MYSQL_PASS}
DB_PASSWORD=${DB_PASS}
FLASK_SECRET=${FLASK_SECRET}
APP_PORT=${ACTUAL_APP_PORT}
HOME_LAT=${HOME_LAT_VAL}
HOME_LNG=${HOME_LNG_VAL}
ENVEOF
chmod 600 "$ENV_FILE"

# Export APP_PORT so Docker Compose uses this exact value — shell env takes
# precedence over the .env file, so we set it explicitly here.
export APP_PORT=$ACTUAL_APP_PORT

info ".env written. App port: $ACTUAL_APP_PORT"

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 3: Create admin credentials ---"
echo ""

if [ -f "$HTPASSWD_FILE" ]; then
    warn ".htpasswd already exists — skipping. Delete it to reset credentials."
else
    htpasswd -B -b -c "$HTPASSWD_FILE" meeks meeks
    chmod 600 "$HTPASSWD_FILE"
    info ".htpasswd created with default bootstrap credentials (meeks / meeks)."
fi

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 4: Check for legacy volumes ---"
echo ""

OLD_VOL="mollie_event_map_db_data"
NEW_VOL="event_map_db_data"

if docker volume ls --format '{{.Name}}' | grep -qx "$OLD_VOL"; then
    if ! docker volume ls --format '{{.Name}}' | grep -qx "$NEW_VOL"; then
        warn "Legacy volume '$OLD_VOL' detected (old Docker project-name prefix)."
        warn "Setup will create a fresh '$NEW_VOL' volume."
        warn "Your existing data stays in '$OLD_VOL' — it will NOT be touched."
        echo ""
        echo "  To migrate data first, run these commands before continuing:"
        echo "    docker volume create $NEW_VOL"
        echo "    docker run --rm \\"
        echo "      -v ${OLD_VOL}:/old \\"
        echo "      -v ${NEW_VOL}:/new \\"
        echo "      alpine sh -c 'cp -a /old/. /new/'"
        echo ""
        echo "  To remove the old volume after a successful migration:"
        echo "    docker volume rm $OLD_VOL"
        echo ""
        read -p "Continue and start with a fresh database? [y/N]: " FRESH_OK
        if [[ ! "$FRESH_OK" =~ ^[Yy]$ ]]; then
            info "Aborted. Migrate your data then re-run setup.sh."
            exit 0
        fi
    else
        info "Volume '$NEW_VOL' already exists — database will be reused."
    fi
else
    if docker volume ls --format '{{.Name}}' | grep -qx "$NEW_VOL"; then
        info "Volume '$NEW_VOL' already exists — database will be reused."
    fi
fi

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 5: Start Docker containers ---"
echo ""

cd "$APP_DIR"
if ! docker compose up -d --build; then
    echo ""
    echo -e "${RED}[ERROR]${NC} Docker could not pull/build required images."
    echo "  This is usually a temporary network or Docker Hub issue."
    echo "  Try:  docker pull mysql:8.0"
    echo "  Then re-run: ./setup.sh"
    echo "  Your existing data and .env are unchanged."
    exit 1
fi
wait_for_db_healthy
info "All containers are up and DB is ready."

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 6: Load seed data ---"
echo ""

SEED_PATH="$APP_DIR/api/data/seed.sql"
LOCAL_BACKUP="$HOME/.event-map/backups/event-map-latest.sql.gz"

# Check if the database already has data before offering restore.
# Uses the container's own credentials — no host mysql client or root password needed.
EXISTING=$(docker exec event-map-db sh -lc \
    'mysql -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -se "SELECT COUNT(*) FROM locations;"' \
    2>/dev/null || echo "0")

if [ "${EXISTING:-0}" -gt 0 ] 2>/dev/null; then
    info "Database already has ${EXISTING} locations — skipping seed/restore."
else
    HAS_SEED=false
    HAS_LOCAL=false
    [ -f "$SEED_PATH" ]   && HAS_SEED=true
    [ -f "$LOCAL_BACKUP" ] && HAS_LOCAL=true

    RESTORE_SOURCE=""

    if [ "$HAS_SEED" = true ] && [ "$HAS_LOCAL" = true ]; then
        echo ""
        echo "  Two backups are available:"
        echo "    [1] Repo baseline:  $SEED_PATH"
        echo "    [2] Local backup:   $LOCAL_BACKUP"
        echo "    [3] Fresh (empty database)"
        echo ""
        printf "  Which would you like to restore? [1/2/3, default 1]: "
        RESTORE_CHOICE=""
        read -r RESTORE_CHOICE < /dev/tty || true
        RESTORE_CHOICE="${RESTORE_CHOICE:-1}"
        case "$RESTORE_CHOICE" in
            2) RESTORE_SOURCE="local" ;;
            3) RESTORE_SOURCE="fresh" ;;
            *) RESTORE_SOURCE="seed" ;;
        esac
    elif [ "$HAS_LOCAL" = true ]; then
        echo ""
        echo "  A local backup is available: $LOCAL_BACKUP"
        printf "  Restore from local backup? [Y/n]: "
        LOCAL_OK=""
        read -r LOCAL_OK < /dev/tty || true
        if [[ ! "$LOCAL_OK" =~ ^[Nn]$ ]]; then
            RESTORE_SOURCE="local"
        else
            RESTORE_SOURCE="fresh"
        fi
    elif [ "$HAS_SEED" = true ]; then
        RESTORE_SOURCE="seed"
    fi

    case "$RESTORE_SOURCE" in
        seed)
            info "Loading repo baseline seed data..."
            import_sql_container "$SEED_PATH"
            LOC_COUNT=$(docker exec event-map-db sh -lc \
                'mysql -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -se "SELECT COUNT(*) FROM locations;"' \
                2>/dev/null || echo "?")
            info "Seed data loaded. Locations: $LOC_COUNT"
            ;;
        local)
            info "Restoring from local backup: $LOCAL_BACKUP"
            if ! zcat "$LOCAL_BACKUP" | docker exec -i event-map-db sh -lc \
                    'mysql -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'; then
                echo ""
                echo -e "${RED}[ERROR]${NC} Local backup restore failed."
                echo ""
                echo "  Container status:"
                docker compose ps
                echo ""
                echo "  Recent DB logs:"
                docker compose logs --tail=30 db
                exit 1
            fi
            LOC_COUNT=$(docker exec event-map-db sh -lc \
                'mysql -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -se "SELECT COUNT(*) FROM locations;"' \
                2>/dev/null || echo "?")
            info "Local backup restored. Locations: $LOC_COUNT"
            ;;
        fresh)
            info "Starting with an empty database."
            ;;
        *)
            warn "No seed file found and no local backup. Site will start with an empty map."
            ;;
    esac
fi

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 7: Verify ---"
echo ""

info "Waiting for app to become healthy (up to 60s — Gunicorn and migrations need time)..."
HEALTH_RESP="unreachable"
for _i in $(seq 1 30); do
    RESP="$(curl -sf "http://127.0.0.1:${ACTUAL_APP_PORT}/health" 2>/dev/null || true)"
    if echo "$RESP" | grep -q '"ok"'; then
        HEALTH_RESP="$RESP"
        break
    fi
    sleep 2
done

if [ "$HEALTH_RESP" != "unreachable" ]; then
    info "API health check passed."
else
    warn "App did not respond within 60s."
    warn "Check: docker compose logs app"
    warn "On slow servers, Gunicorn and migrations can take several minutes."
    warn "If the app is still starting, wait a moment then re-run: ./setup.sh"
fi

# ---------------------------------------------------------------------------
echo ""
echo "================================================"
echo -e "${GREEN}   Setup complete!${NC}"
echo "================================================"
echo ""
echo "  Events:       http://localhost:${ACTUAL_APP_PORT}/#events"
echo "  Map:          http://localhost:${ACTUAL_APP_PORT}/#map"
echo "  Admin:        http://localhost:${ACTUAL_APP_PORT}/admin/#events"
echo "  Health:       http://localhost:${ACTUAL_APP_PORT}/health"
echo ""
echo "  Default admin login:  meeks / meeks"
echo -e "  ${RED}Change this immediately after first login.${NC}"
echo "  Do not expose the admin panel publicly without changing credentials."
echo ""
echo "  Point a domain at this server's IP and enable"
echo "  Cloudflare proxy for automatic HTTPS."
echo ""
echo "  For all ongoing operations (backup, update, troubleshoot, seed):"
echo "    ./menu.sh"
echo ""

# ---------------------------------------------------------------------------
echo ""
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Offer to remove local source files (the running app and volumes are unaffected,
# but .env, .htpasswd, docker-compose.yml, and scripts/ live here too — warn the user).
warn "────────────────────────────────────────────────────────"
warn "DANGER: The next step permanently deletes ALL local source"
warn "files in $REPO_DIR — including .env, .htpasswd,"
warn "docker-compose.yml, and scripts/. You will lose the ability"
warn "to restart, update, or back up the app until you re-clone."
warn "Default is NO. Only type 'y' if you are absolutely sure."
warn "────────────────────────────────────────────────────────"
printf "Delete local source files now? [y/N] "
DEL_CHOICE=""
read -r DEL_CHOICE < /dev/tty || true
if [ "${DEL_CHOICE}" = "y" ] || [ "${DEL_CHOICE}" = "Y" ]; then
    echo "==> Removing local source files..."
    cd "$HOME" 2>/dev/null || cd / 2>/dev/null || true
    rm -rf "$REPO_DIR"
    echo "    Done. The running app and Docker volumes are preserved."
else
    echo "    Source files preserved."
fi
