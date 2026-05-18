#!/bin/bash
# =============================================================================
# Event Map — Diagnostics and Repair
#
# Inspects your Docker environment, required files, container state,
# app and database connectivity, and recent logs. When issues are found,
# optionally offers safe repair actions with confirmation.
#
# Usage:
#   ./troubleshoot.sh
#
# Repair actions available (all ask before acting, default No):
#   - Start containers
#   - Restart app container
#   - Rebuild app container (docker compose up -d --build app)
#   - Show more app/db logs
#   - Rerun diagnostics
#
# What this does NOT do (even with repair):
#   - Does not delete volumes or database data
#   - Does not reset the database
#   - Does not overwrite seed.sql
#   - Does not commit or push
#   - Does not expose secrets (env values are not printed)
# =============================================================================

# No set -e — we continue past failing checks and report everything.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"

# Change to repo root so docker compose commands resolve correctly.
cd "$APP_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

_ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
_fail() { echo -e "  ${RED}✗${NC}  $1"; ISSUES=$((ISSUES + 1)); }
_warn() { echo -e "  ${YELLOW}!${NC}  $1"; }
_info() { echo -e "  ${DIM}   $1${NC}"; }
_head() { echo -e "\n${BOLD}── $1 ──${NC}"; }

ISSUES=0

echo ""
echo "================================================"
echo "   Event Map — Diagnostics"
echo "================================================"
echo ""
echo "  Checks system, containers, and app health."
echo "  If issues are found, repair options are offered at the end."

# =============================================================================
_head "1. Prerequisites"
# =============================================================================

DOCKER_OK=false
COMPOSE_OK=false

if command -v docker &>/dev/null; then
    _ok "docker found: $(docker --version 2>/dev/null | head -1)"
else
    _fail "docker not found in PATH"
    _info "Install: https://docs.docker.com/engine/install/"
fi

if docker info &>/dev/null 2>&1; then
    _ok "Docker daemon is running"
    DOCKER_OK=true
else
    _fail "Docker daemon is NOT running (or permission denied)"
    _info "Try: sudo systemctl start docker   or add user to docker group"
fi

if docker compose version &>/dev/null 2>&1; then
    _ok "docker compose: $(docker compose version 2>/dev/null | head -1)"
    COMPOSE_OK=true
else
    _fail "docker compose v2 not found"
    _info "Upgrade Docker or install the Compose plugin"
fi

# =============================================================================
_head "2. Required files"
# =============================================================================

if [ -f "$APP_DIR/docker-compose.yml" ]; then
    _ok "docker-compose.yml exists"
else
    _fail "docker-compose.yml missing in $APP_DIR"
    _info "You may not be in the repo root — try: cd /path/to/event-map"
fi

if [ -f "$ENV_FILE" ]; then
    _ok ".env exists"
else
    _fail ".env missing — run ./setup.sh to create it"
fi

if [ -f "$APP_DIR/.htpasswd" ]; then
    _ok ".htpasswd exists"
else
    _fail ".htpasswd missing"
    _info "Run ./setup.sh to create it, or: htpasswd -B -b -c .htpasswd <user> <password>"
fi

# =============================================================================
_head "3. Container status"
# =============================================================================

DB_RUNNING=false
APP_RUNNING=false

if [ "$DOCKER_OK" = true ] && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "event-map-db"; then
    DB_RUNNING=true
    DB_STATUS="$(docker inspect --format '{{.State.Status}}' event-map-db 2>/dev/null || echo unknown)"
    DB_HEALTH="$(docker inspect --format '{{.State.Health.Status}}' event-map-db 2>/dev/null || echo unknown)"
    _ok "event-map-db: $DB_STATUS, health: $DB_HEALTH"
    if [ "$DB_HEALTH" != "healthy" ]; then
        _warn "DB is not reporting healthy — may still be starting up (normal for 1-2 min)"
    fi
else
    _fail "event-map-db is not running"
    _info "Start with: docker compose up -d   or run ./setup.sh"
fi

if [ "$DOCKER_OK" = true ] && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "event-map-app"; then
    APP_RUNNING=true
    APP_STATUS="$(docker inspect --format '{{.State.Status}}' event-map-app 2>/dev/null || echo unknown)"
    _ok "event-map-app: $APP_STATUS"
else
    _fail "event-map-app is not running"
    _info "Start with: docker compose up -d   or run ./setup.sh"
fi

# Read port from .env (value is not printed — only the key name is shown)
APP_PORT=""
if [ -f "$ENV_FILE" ]; then
    APP_PORT="$(grep -E '^APP_PORT=' "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
fi
APP_PORT="${APP_PORT:-8090}"
_ok "APP_PORT = $APP_PORT (from .env)"

# =============================================================================
_head "4. App health"
# =============================================================================

HEALTH_OK=false

if [ "$APP_RUNNING" = true ]; then
    HEALTH_RESP="$(curl -sf --max-time 5 "http://localhost:${APP_PORT}/health" 2>/dev/null || true)"
    if echo "$HEALTH_RESP" | grep -q '"ok"'; then
        _ok "Health endpoint responded: $HEALTH_RESP"
        HEALTH_OK=true
    else
        _fail "Health endpoint not responding on http://localhost:${APP_PORT}/health"
        _info "Response: ${HEALTH_RESP:-(no response)}"
        _info "Try: docker compose logs --tail=30 app"
    fi

    LOC_RESP="$(curl -sf --max-time 10 "http://localhost:${APP_PORT}/api/locations" 2>/dev/null || true)"
    LOC_COUNT="$(echo "$LOC_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d))' 2>/dev/null || true)"
    if [ -n "$LOC_COUNT" ]; then
        _ok "API /locations responded: $LOC_COUNT locations"
    else
        _warn "API /locations did not return expected data"
        _info "This may be normal if the DB is still starting or the events cache is empty"
    fi
else
    _warn "Skipping health check — event-map-app is not running"
fi

# =============================================================================
_head "5. Recent app logs"
# =============================================================================

if [ "$APP_RUNNING" = true ]; then
    echo ""
    echo -e "${DIM}  Last 15 lines of app container logs:${NC}"
    echo ""
    docker compose logs --tail=15 app 2>/dev/null | sed 's/^/    /' || true
else
    _warn "App container not running — no logs to show"
fi

if [ "$DB_RUNNING" = true ]; then
    DB_HEALTH_NOW="$(docker inspect --format '{{.State.Health.Status}}' event-map-db 2>/dev/null || echo unknown)"
    if [ "$DB_HEALTH_NOW" != "healthy" ]; then
        echo ""
        echo -e "${DIM}  DB is not healthy — last 15 lines of db logs:${NC}"
        echo ""
        docker compose logs --tail=15 db 2>/dev/null | sed 's/^/    /' || true
    fi
fi

# =============================================================================
_head "6. Summary"
# =============================================================================

echo ""
if [ "$ISSUES" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}All checks passed.${NC} The app looks healthy."
    echo ""
    echo "  Events:  http://localhost:${APP_PORT}/"
    echo "  Map:     http://localhost:${APP_PORT}/map"
    echo "  Admin:   http://localhost:${APP_PORT}/admin/"
    echo "  Health:  http://localhost:${APP_PORT}/health"
else
    echo -e "  ${RED}${BOLD}${ISSUES} issue(s) found.${NC} See the ✗ lines above."
    echo ""

    if ! command -v docker &>/dev/null || ! docker info &>/dev/null 2>&1; then
        echo "  → Docker is not available. Install or start Docker first."
    elif [ "$DB_RUNNING" = false ] && [ "$APP_RUNNING" = false ]; then
        echo "  → No containers running."
        if [ -f "$ENV_FILE" ]; then
            echo "    Start:  docker compose up -d"
            echo "    Or run: ./setup.sh  (if this is a fresh install)"
        else
            echo "    Run:    ./setup.sh  (first-time setup)"
        fi
    elif [ "$APP_RUNNING" = false ]; then
        echo "  → App container not running. Try:"
        echo "    docker compose up -d app"
        echo "    docker compose logs app"
    fi

    if [ ! -f "$ENV_FILE" ]; then
        echo "  → .env missing. Run ./setup.sh to generate it."
    fi
    if [ ! -f "$APP_DIR/.htpasswd" ]; then
        echo "  → .htpasswd missing. Run ./setup.sh or:"
        echo "    htpasswd -B -b -c .htpasswd meeks <yourpassword>"
    fi
fi

# =============================================================================
_head "7. Repair options"
# =============================================================================

if [ "$ISSUES" -eq 0 ] && [ "$HEALTH_OK" = true ]; then
    echo ""
    _info "No repair needed — all checks passed."
    echo ""
    exit 0
fi

if [ "$DOCKER_OK" = false ] || [ "$COMPOSE_OK" = false ]; then
    echo ""
    _warn "Docker or Compose is not available — repair options require Docker."
    echo ""
    echo "  Install or start Docker, then re-run this script."
    echo ""
    exit 0
fi

echo ""
echo -e "  ${BOLD}Would you like to try a repair action?${NC}"
echo "  All actions ask for confirmation first. Default is No."
echo ""

if [ "$DB_RUNNING" = false ] || [ "$APP_RUNNING" = false ]; then
    echo "  [1] Start containers        docker compose up -d"
fi
echo "  [2] Restart app container   docker compose restart app"
echo "  [3] Rebuild app container   docker compose up -d --build app"
echo "  [4] Show more app logs      last 50 lines"
echo "  [5] Show more DB logs       last 50 lines"
echo "  [6] Rerun diagnostics       run this script again"
echo "  [7] Nothing — I'll handle it myself"
echo ""
printf "  Your choice: "
REPAIR_CHOICE=""
read -r REPAIR_CHOICE < /dev/tty || REPAIR_CHOICE="7"
echo ""

_confirm() {
    printf "  %s [y/N] " "$1"
    local ANS=""
    read -r ANS < /dev/tty || ANS=""
    echo ""
    [[ "${ANS,,}" == "y" ]]
}

case "${REPAIR_CHOICE}" in
    1)
        if _confirm "Start containers with 'docker compose up -d'?"; then
            docker compose up -d \
                && echo "" && _ok "Containers started." \
                || _warn "Command failed — check output above."
        else
            _info "Skipped."
        fi
        ;;
    2)
        if _confirm "Restart app container?"; then
            docker compose restart app \
                && echo "" && _ok "App container restarted." \
                || _warn "Command failed — check output above."
        else
            _info "Skipped."
        fi
        ;;
    3)
        echo "  This will briefly restart the app container to apply any image changes."
        if _confirm "Rebuild and restart app container?"; then
            docker compose up -d --build app \
                && echo "" && _ok "App container rebuilt and started." \
                || _warn "Command failed — check output above."
        else
            _info "Skipped."
        fi
        ;;
    4)
        echo ""
        echo -e "${DIM}  Last 50 lines of app logs:${NC}"
        echo ""
        docker compose logs --tail=50 app 2>/dev/null | sed 's/^/    /' \
            || _warn "Could not retrieve app logs."
        echo ""
        ;;
    5)
        echo ""
        echo -e "${DIM}  Last 50 lines of DB logs:${NC}"
        echo ""
        docker compose logs --tail=50 db 2>/dev/null | sed 's/^/    /' \
            || _warn "Could not retrieve DB logs."
        echo ""
        ;;
    6)
        exec "$APP_DIR/troubleshoot.sh"
        ;;
    7|"")
        _info "No repair action taken."
        echo ""
        echo "  Other useful commands:"
        echo "    docker compose ps                   — container state summary"
        echo "    docker compose logs --tail=50 app   — recent app logs"
        echo "    docker compose logs --tail=50 db    — recent DB logs"
        echo "    ./setup.sh                          — full (re)initialization"
        echo "    ./update.sh                         — pull latest code and rebuild"
        ;;
    *)
        _warn "Unknown choice. No repair action taken."
        ;;
esac

echo ""
