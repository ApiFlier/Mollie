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

echo ""
echo "================================================"
echo "   Mollie's Guide - Setup Script"
echo "================================================"
echo ""

# --- Check we're in the right place ---
if [ ! -f "$MOLLIE_DIR/docker-compose.yml" ]; then
    error "docker-compose.yml not found in $MOLLIE_DIR. Did you clone to /mollie?"
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
echo "--- Step 1: Create .env file ---"
echo ""

if [ -f "$ENV_FILE" ]; then
    warn ".env already exists. Skipping creation. Delete it manually if you want to regenerate."
else
    FLASK_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    cat > "$ENV_FILE" << EOF
MYSQL_ROOT_PASSWORD=meeks
DB_PASSWORD=meeks
FLASK_SECRET=${FLASK_SECRET}
EOF

    chmod 600 "$ENV_FILE"
    info ".env created with default credentials (meeks/meeks). Change these in production!"
fi

echo ""
echo "--- Step 2: Create admin login (.htpasswd) ---"
echo ""

if [ -f "$HTPASSWD_FILE" ]; then
    warn ".htpasswd already exists. Skipping. Delete it manually to reset credentials."
else
    # Default: meeks/meeks (bcrypt hash)
    echo 'meeks:$2y$05$0Z1234567890123456789uQKZv1234567890123456789012345678' > "$HTPASSWD_FILE"
    # Generate a real hash for meeks/meeks
    htpasswd -B -b -c "$HTPASSWD_FILE" meeks meeks
    chmod 600 "$HTPASSWD_FILE"
    info ".htpasswd created with default credentials meeks/meeks. Change via admin panel after login!"
fi

echo ""
echo "--- Step 3: Start Docker containers ---"
echo ""

cd "$MOLLIE_DIR"
docker compose up -d
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
DB_PASS=$(grep DB_PASSWORD "$ENV_FILE" | cut -d= -f2)

if [ -f "$BACKUP_PATH" ]; then
    info "Found backup at $BACKUP_PATH. Restoring..."
    docker exec -i mollies-db mysql \
        -uroot -p"${ROOT_PASS}" \
        mollies_guide < "$BACKUP_PATH"

    FARM_COUNT=$(docker exec mollies-db mysql \
        -umollies -p"${DB_PASS}" \
        mollies_guide -se "SELECT COUNT(*) FROM locations;" 2>/dev/null)

    info "Database restored. Farm count: $FARM_COUNT"
else
    warn "No backup file found at $BACKUP_PATH."
    read -p "Enter full path to a .sql backup file (or press Enter to skip): " CUSTOM_BACKUP
    if [ -n "$CUSTOM_BACKUP" ] && [ -f "$CUSTOM_BACKUP" ]; then
        docker exec -i mollies-db mysql \
            -uroot -p"${ROOT_PASS}" \
            mollies_guide < "$CUSTOM_BACKUP"
        info "Database restored from $CUSTOM_BACKUP."
    else
        warn "Skipping database restore. Site will work but show no farms."
    fi
fi

echo ""
echo "--- Step 5: Verify ---"
echo ""

sleep 3

if curl -s -o /dev/null -w "%{http_code}" http://localhost:8090 | grep -q "200"; then
    info "Public site is responding on port 8090."
else
    warn "Port 8090 not responding yet. Give it another 10 seconds and try: curl http://localhost:8090"
fi

if curl -s -o /dev/null -w "%{http_code}" http://localhost:8091/api/health | grep -q "200"; then
    info "API is healthy on port 8091."
else
    warn "API not responding yet. Check: docker compose logs mollies-api"
fi

echo ""
echo "================================================"
echo -e "${GREEN}   Setup complete!${NC}"
echo "================================================"
echo ""
echo "  Public map:   http://localhost:8090"
echo "  Admin panel:  http://localhost:8090/admin/"
echo "  API health:   http://localhost:8091/api/health"
echo ""
echo "  If using Cloudflare, point your domain at this"
echo "  server's IP and enable the proxy for auto SSL."
echo ""
echo "  To take a backup anytime:"
echo "  docker exec mollies-db mysqldump -umollies \\"
echo "    -p\$(grep DB_PASSWORD /mollie/.env | cut -d= -f2) \\"
echo "    mollies_guide > ~/mollies_backup_\$(date +%Y%m%d).sql"
echo ""
