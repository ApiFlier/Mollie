#!/bin/bash
# =============================================================================
# Mollie's Guide - Fresh Deployment Setup Script
# Run this after cloning the repo on a new server
# Usage: chmod +x setup.sh && ./setup.sh
# =============================================================================

set -e

MOLLIE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$MOLLIE_DIR/.env"
HTPASSWD_FILE="$MOLLIE_DIR/.htpasswd"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Find the next available port starting from a given port
find_open_port() {
    local port=$1
    while ss -tuln | grep -q ":${port} "; do
        port=$((port + 1))
    done
    echo $port
}

echo ""
echo "================================================"
echo "   Mollie's Guide - Setup Script"
echo "================================================"
echo ""

# --- Check we're in the right place ---
if [ ! -f "$MOLLIE_DIR/docker-compose.yml" ]; then
    error "docker-compose.yml not found in $MOLLIE_DIR. Did you clone correctly?"
fi

# --- Check Docker is installed ---
if ! command -v docker &> /dev/null; then
    error "Docker is not installed. Install it first: https://docs.docker.com/engine/install/"
fi

if ! docker compose version &> /dev/null; then
    error "Docker Compose not found. Make sure you have Docker Compose v2 installed."
fi

# --- Check apache2-utils for htpasswd ---
if ! command -v htpasswd &> /dev/null; then
    info "Installing apache2-utils for htpasswd..."
    sudo apt update -q && sudo apt install -y apache2-utils
fi

echo ""
echo "--- Step 1: Generate .env with random passwords and open ports ---"
echo ""

MYSQL_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
DB_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
FLASK_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

FRONTEND_PORT=$(find_open_port 8090)
API_PORT=$(find_open_port $((FRONTEND_PORT + 1)))
DB_PORT=$(find_open_port 3308)

cat > "$ENV_FILE" <<ENVEOF
MYSQL_ROOT_PASSWORD=${MYSQL_PASS}
DB_PASSWORD=${DB_PASS}
FLASK_SECRET=${FLASK_SECRET}
FRONTEND_PORT=${FRONTEND_PORT}
API_PORT=${API_PORT}
DB_PORT=${DB_PORT}
ENVEOF

chmod 600 "$ENV_FILE"
info ".env generated with random passwords."
info "Ports assigned — Frontend: $FRONTEND_PORT | API: $API_PORT | DB: $DB_PORT"

echo ""
echo "--- Step 2: Create admin login (.htpasswd) ---"
echo ""

if [ -f "$HTPASSWD_FILE" ]; then
    warn ".htpasswd already exists. Skipping. Delete it manually to reset credentials."
else
    htpasswd -B -b -c "$HTPASSWD_FILE" meeks meeks
    chmod 600 "$HTPASSWD_FILE"
    info ".htpasswd created with default credentials meeks/meeks. Change via admin panel after login!"
fi

echo ""
echo "--- Step 3: Start Docker containers ---"
echo ""

cd "$MOLLIE_DIR"
docker compose up -d
docker cp .htpasswd mollies-api:/etc/nginx/.htpasswd
info "Containers started. Waiting 20 seconds for MySQL to initialize..."
sleep 20

# --- Verify containers are running ---
if ! docker compose ps | grep -q "mollies-db.*running\|mollies-db.*Up"; then
    error "mollies-db container failed to start. Check: docker compose logs mollies-db"
fi

info "All containers are up."

echo ""
echo "--- Step 4: Restore database backup ---"
echo ""

BACKUP_PATH="$MOLLIE_DIR/api/data/mollies_backup.sql"
ROOT_PASS=$(grep MYSQL_ROOT_PASSWORD "$ENV_FILE" | cut -d= -f2)

if [ -f "$BACKUP_PATH" ]; then
    info "Found backup at $BACKUP_PATH. Restoring..."
    docker exec -i mollies-db mysql \
        -uroot -p"${ROOT_PASS}" \
        mollies_guide < "$BACKUP_PATH"

    LOC_COUNT=$(docker exec mollies-db mysql \
        -uroot -p"${ROOT_PASS}" \
        mollies_guide -se "SELECT COUNT(*) FROM locations;" 2>/dev/null)

    info "Database restored. Location count: $LOC_COUNT"
else
    warn "No backup file found at $BACKUP_PATH."
    read -p "Enter full path to a .sql backup file (or press Enter to skip): " CUSTOM_BACKUP
    if [ -n "$CUSTOM_BACKUP" ] && [ -f "$CUSTOM_BACKUP" ]; then
        docker exec -i mollies-db mysql \
            -uroot -p"${ROOT_PASS}" \
            mollies_guide < "$CUSTOM_BACKUP"
        info "Database restored from $CUSTOM_BACKUP."
    else
        warn "Skipping database restore. Site will work but show no locations."
    fi
fi

echo ""
echo "--- Step 5: Verify ---"
echo ""

sleep 10

if curl -s -o /dev/null -w "%{http_code}" http://localhost:${FRONTEND_PORT} | grep -q "200"; then
    info "Public site is responding on port ${FRONTEND_PORT}."
else
    warn "Port ${FRONTEND_PORT} not responding yet. Try: curl http://localhost:${FRONTEND_PORT}"
fi

if curl -s -o /dev/null -w "%{http_code}" http://localhost:${API_PORT}/api/health | grep -q "200"; then
    info "API is healthy on port ${API_PORT}."
else
    warn "API not responding yet. Check: docker compose logs mollies-api"
fi

echo ""
echo "================================================"
echo -e "${GREEN}   Setup complete!${NC}"
echo "================================================"
echo ""
echo "  Public map:   http://localhost:${FRONTEND_PORT}"
echo "  Admin panel:  http://localhost:${FRONTEND_PORT}/admin/"
echo "  API health:   http://localhost:${API_PORT}/api/health"
echo ""
echo "  Default admin login: meeks / meeks"
echo "  Change it at: http://localhost:${FRONTEND_PORT}/admin/"
echo ""
echo "  If using Cloudflare, point your domain at this"
echo "  server's IP and enable the Cloudflare proxy for auto SSL."
echo ""
echo "  To take a backup anytime:"
echo "  docker exec mollies-db mysqldump -uroot \\"
echo "    -p\$(grep MYSQL_ROOT_PASSWORD $ENV_FILE | cut -d= -f2) \\"
echo "    mollies_guide > $MOLLIE_DIR/api/data/mollies_backup.sql"
echo ""
# --- Optional cleanup ---
echo ""
read -p "Would you like to delete the local repo files? The site will continue running. (y/N): " CLEANUP
if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    cd /
    rm -rf "$MOLLIE_DIR"
    echo -e "${GREEN}[INFO]${NC} Local files removed. Containers are still running."
    echo "  To manage containers: docker ps / docker compose -p mollie down"
else
    echo -e "${GREEN}[INFO]${NC} Local files kept at $MOLLIE_DIR"
fi
