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
fi

MYSQL_PASS=${_OLD_MYSQL:-$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")}
DB_PASS=${_OLD_DB:-$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")}
FLASK_SECRET=${_OLD_SECRET:-$(python3 -c "import secrets; print(secrets.token_hex(32))")}

# Old containers are stopped at this point, so their ports are free.
PREF_APP_PORT=${_OLD_PORT:-8090}
ACTUAL_APP_PORT=$(find_open_port $PREF_APP_PORT)

cat > "$ENV_FILE" <<ENVEOF
MYSQL_ROOT_PASSWORD=${MYSQL_PASS}
DB_PASSWORD=${DB_PASS}
FLASK_SECRET=${FLASK_SECRET}
APP_PORT=${ACTUAL_APP_PORT}
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
docker compose up -d --build
info "Containers started. Waiting for MySQL to initialize..."
sleep 20

if ! docker compose ps | grep -q "event-map-db.*running\|event-map-db.*Up"; then
    error "event-map-db failed to start. Check: docker compose logs event-map-db"
fi
info "All containers are up."

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 6: Load seed data ---"
echo ""

SEED_PATH="$APP_DIR/api/data/seed.sql"
ROOT_PASS=$(grep "^MYSQL_ROOT_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)

# Check if the database already has locations before loading seed data.
# The seed file is a full mysqldump (includes DROP TABLE) so we skip it
# if data already exists to avoid overwriting any user-added content.
EXISTING=$(docker exec event-map-db mysql \
    -uroot -p"${ROOT_PASS}" \
    event_map -se "SELECT COUNT(*) FROM locations;" 2>/dev/null || echo "0")

if [ "${EXISTING:-0}" -eq 0 ] 2>/dev/null; then
    if [ -f "$SEED_PATH" ]; then
        info "Loading seed data..."
        docker exec -i event-map-db mysql \
            -uroot -p"${ROOT_PASS}" \
            event_map < "$SEED_PATH"
        LOC_COUNT=$(docker exec event-map-db mysql \
            -uroot -p"${ROOT_PASS}" \
            event_map -se "SELECT COUNT(*) FROM locations;" 2>/dev/null || echo "?")
        info "Seed data loaded. Locations: $LOC_COUNT"
    else
        warn "No seed file found at $SEED_PATH. Site will start with an empty map."
    fi
else
    info "Database already has ${EXISTING} locations — skipping seed load."
fi

# ---------------------------------------------------------------------------
echo ""
echo "--- Step 7: Verify ---"
echo ""

sleep 5

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "http://127.0.0.1:${ACTUAL_APP_PORT}" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    info "App is responding on port ${ACTUAL_APP_PORT}."
else
    warn "Port ${ACTUAL_APP_PORT} not yet responding (HTTP $HTTP_CODE). Give it a moment."
fi

HEALTH_OK=0
if curl -s "http://127.0.0.1:${ACTUAL_APP_PORT}/health" 2>/dev/null \
        | grep -q '"ok":.*true'; then
    HEALTH_OK=1
elif curl -s "http://127.0.0.1:${ACTUAL_APP_PORT}/api/health" 2>/dev/null \
        | grep -q '"ok":.*true'; then
    HEALTH_OK=1
fi

if [ $HEALTH_OK -eq 1 ]; then
    info "API health check passed."
else
    warn "API health check did not respond. Check: docker compose logs event-map-app"
fi

# ---------------------------------------------------------------------------
echo ""
echo "================================================"
echo -e "${GREEN}   Setup complete!${NC}"
echo "================================================"
echo ""
echo "  Public map:   http://localhost:${ACTUAL_APP_PORT}"
echo "  Admin panel:  http://localhost:${ACTUAL_APP_PORT}/admin/"
echo "  Health check: http://localhost:${ACTUAL_APP_PORT}/health"
echo ""
echo "  Default admin login:  meeks / meeks"
echo -e "  ${RED}Change this immediately after first login.${NC}"
echo "  Do not expose the admin panel publicly without changing credentials."
echo ""
echo "  Point a domain at this server's IP and enable"
echo "  Cloudflare proxy for automatic HTTPS."
echo ""
echo "  To take a database backup:"
echo "  docker exec event-map-db mysqldump -uroot \\"
echo "    -p\$(grep MYSQL_ROOT_PASSWORD $ENV_FILE | cut -d= -f2) \\"
echo "    event_map > $APP_DIR/api/data/seed.sql"
echo ""

# ---------------------------------------------------------------------------
echo ""
read -p "Delete local source files now? [y/N]: " CLEANUP
if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    cd /
    rm -rf "$APP_DIR"
    echo -e "${GREEN}[INFO]${NC} Local files removed. Containers and data volumes are still running."
    echo "  To stop:   docker stop event-map-app event-map-db"
    echo "  To remove: docker rm event-map-app event-map-db"
else
    echo -e "${GREEN}[INFO]${NC} Local files kept at $APP_DIR"
fi
