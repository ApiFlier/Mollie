#!/bin/bash
# Event Map — update an existing deployment after git pull.
# Rebuilds and restarts app containers only.
#
# Safety guarantees:
#   - Does NOT delete or reset the database.
#   - Does NOT delete Docker volumes.
#   - Does NOT touch .env or .htpasswd.
#   - Does NOT restore seed data or ask backup/restore questions.
#   - Does NOT remove local source files.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "================================================"
echo "   Event Map — Update"
echo "================================================"
warn "Rebuilds app containers only."
warn "Database, volumes, .env, and .htpasswd are preserved."
echo ""

# --- Preflight ---
if ! command -v docker &>/dev/null; then
    error "Docker is not installed or not in PATH."
fi
if ! docker compose version &>/dev/null 2>&1; then
    error "Docker Compose v2 not found. Install or upgrade Docker."
fi
if [ ! -f "$ENV_FILE" ]; then
    error ".env not found in $APP_DIR. Run ./setup.sh first to initialize the deployment."
fi
if [ ! -f "$APP_DIR/docker-compose.yml" ]; then
    error "docker-compose.yml not found in $APP_DIR."
fi

# --- Port ---
APP_PORT="$(grep -E '^APP_PORT=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
APP_PORT="${APP_PORT:-8090}"
info "APP_PORT = $APP_PORT"

# --- Build and start ---
info "Building and restarting containers..."
cd "$APP_DIR"
if ! docker compose up -d --build; then
    error "docker compose up --build failed. Check the output above."
fi

# --- Health check ---
info "Waiting for app to respond..."
HEALTH="unreachable"
for i in $(seq 1 20); do
    RESP="$(curl -sf "http://localhost:${APP_PORT}/health" 2>/dev/null || true)"
    if echo "$RESP" | grep -q '"ok"'; then
        HEALTH="$RESP"
        break
    fi
    sleep 2
done

echo ""
echo "================================================"
info "Events URL:  http://localhost:${APP_PORT}/"
info "Map URL:     http://localhost:${APP_PORT}/map"
info "Admin URL:   http://localhost:${APP_PORT}/admin/"
info "Health:      ${HEALTH}"
info "Database volume preserved."
echo "================================================"
echo ""

if [ "$HEALTH" = "unreachable" ]; then
    warn "App may still be starting. Check: curl http://localhost:${APP_PORT}/health"
fi
