#!/bin/bash
# =============================================================================
# Event Map — Main Menu
#
# The single entry point for all common operations.
# Run this and pick what you need — no need to remember script names.
#
# Usage:
#   ./menu.sh
#
# What this does NOT do on its own:
#   - Does not commit, push, or stage files (only if you confirm in a sub-step)
#   - Does not delete volumes or database data
#   - Does not modify .env or .htpasswd
# =============================================================================

# No set -e: menu loop must survive sub-script failures.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info() { echo -e "  ${GREEN}✓${NC}  $1"; }
warn() { echo -e "  ${YELLOW}!${NC}  $1"; }
dim()  { echo -e "  ${DIM}$1${NC}"; }

# =============================================================================
# Status summary — shown at the top of each main menu render
# =============================================================================
_status_summary() {
    echo ""
    echo -e "  ${BOLD}Status${NC}"
    echo "  ────────────────────────────────────────────────────────"

    # Docker
    if docker info &>/dev/null 2>&1; then
        info "Docker is running"

        # Containers
        APP_RUNNING="$(docker ps --filter name=event-map-app --format '{{.Status}}' 2>/dev/null | head -1)"
        DB_RUNNING="$(docker ps --filter name=event-map-db  --format '{{.Status}}' 2>/dev/null | head -1)"

        if [ -n "$APP_RUNNING" ] && [ -n "$DB_RUNNING" ]; then
            info "App and database containers are up"
        elif [ -z "$APP_RUNNING" ] && [ -z "$DB_RUNNING" ]; then
            warn "Containers are not running — choose [1] to set up, or [4] to troubleshoot"
        else
            [ -z "$APP_RUNNING" ] && warn "App container is not running"
            [ -z "$DB_RUNNING"  ] && warn "Database container is not running"
        fi
    else
        warn "Docker is not running or not available"
    fi

    # App URL and health (no secrets printed — only port number)
    APP_PORT=""
    if [ -f "$APP_DIR/.env" ]; then
        APP_PORT="$(grep -E '^APP_PORT=' "$APP_DIR/.env" 2>/dev/null \
            | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
    fi
    APP_PORT="${APP_PORT:-8090}"

    HEALTH_URL="http://localhost:${APP_PORT}/health"
    if curl -sf --max-time 2 "$HEALTH_URL" &>/dev/null 2>&1; then
        info "App is healthy  →  http://localhost:${APP_PORT}/"
    else
        dim "App URL: http://localhost:${APP_PORT}/  (not responding)"
    fi

    echo "  ────────────────────────────────────────────────────────"
}

# =============================================================================
# Advanced tools submenu
# =============================================================================
_advanced_menu() {
    while true; do
        echo ""
        echo -e "  ${BOLD}${CYAN}Advanced Tools${NC}"
        echo "  ────────────────────────────────────────────────────────"
        echo ""
        dim "Backup, seed management, diagnostics, and Docker tools."
        dim "Normal users can use the main menu for daily tasks."
        echo ""
        echo "  [1] Quick database backup"
        dim "      Save the database to ~/.event-map/backups/ — nothing else changed"
        echo ""
        echo "  [2] Backup + optional seed refresh / publish"
        dim "      Backup, then offer to update seed.sql and push to GitHub"
        echo ""
        echo "  [3] Seed workflow: refresh / review / publish"
        dim "      Update api/data/seed.sql from the database — does NOT touch the running DB"
        echo ""
        echo "  [4] Run diagnostics"
        dim "      Check containers, ports, config, and common problems"
        echo ""
        echo "  [5] Show Docker Compose status"
        dim "      docker compose ps"
        echo ""
        echo "  [6] Show recent logs"
        dim "      Last 40 lines of app and DB logs"
        echo ""
        echo "  [7] Return to main menu"
        echo ""
        printf "  Your choice [1-7]: "
        local ADV=""
        read -r ADV < /dev/tty || { echo ""; break; }
        echo ""

        case "$ADV" in
            1)
                echo "  ── Quick database backup ──────────────────────────────────"
                echo ""
                "$APP_DIR/scripts/commands/backup.sh" --quick \
                    || warn "Backup exited with an error — check output above."
                ;;
            2)
                echo "  ── Backup + optional seed update ──────────────────────────"
                echo ""
                "$APP_DIR/scripts/commands/backup.sh" \
                    || warn "Backup/seed workflow exited with an error — check output above."
                ;;
            3)
                echo "  ── Seed workflow ──────────────────────────────────────────"
                echo ""
                "$APP_DIR/scripts/commands/seed.sh" \
                    || warn "Seed workflow exited with an error — check output above."
                ;;
            4)
                echo "  ── Diagnostics ────────────────────────────────────────────"
                echo ""
                "$APP_DIR/scripts/commands/troubleshoot.sh" || true
                ;;
            5)
                echo ""
                docker compose ps 2>/dev/null \
                    || warn "Could not run docker compose ps — is Docker running?"
                echo ""
                ;;
            6)
                echo ""
                echo -e "  ${DIM}Last 40 lines — app:${NC}"
                echo ""
                docker compose logs --tail=40 app 2>/dev/null | sed 's/^/    /' \
                    || warn "Could not retrieve app logs."
                echo ""
                echo -e "  ${DIM}Last 40 lines — db:${NC}"
                echo ""
                docker compose logs --tail=40 db 2>/dev/null | sed 's/^/    /' \
                    || warn "Could not retrieve DB logs."
                echo ""
                ;;
            7|q|Q|"")
                break
                ;;
            *)
                warn "Unknown choice '${ADV}' — enter 1 to 7."
                ;;
        esac

        echo ""
        printf "  Press Enter for advanced tools, or q to go back: "
        local ADV_NAV=""
        read -r ADV_NAV < /dev/tty || break
        case "$ADV_NAV" in q|Q) break ;; esac
    done
}

# =============================================================================
# Main menu loop
# =============================================================================
while true; do
    clear 2>/dev/null || true
    echo ""
    echo -e "  ${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "  ${BOLD}${CYAN}║             Event Map — Main Menu                   ║${NC}"
    echo -e "  ${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${NC}"

    _status_summary

    echo ""
    echo -e "  ${BOLD}What would you like to do?${NC}"
    echo ""
    echo "  [1] Start here: set up the app"
    dim "      Build containers, generate secrets, load starter data"
    echo ""
    echo "  [2] Update the app"
    dim "      Pull latest code, rebuild container, check health"
    echo ""
    echo "  [3] Back up my data"
    dim "      Save database to ~/.event-map/backups/"
    echo ""
    echo "  [4] Fix something that is broken"
    dim "      Diagnose issues, optionally restart or rebuild containers"
    echo ""
    echo "  [5] Show app status and links"
    dim "      Container state, app URL, admin URL"
    echo ""
    echo "  [6] Advanced tools"
    dim "      Backup, seed workflow, logs, Docker status"
    echo ""
    echo "  [7] Quit"
    echo ""

    printf "  Your choice [1-7]: "
    CHOICE=""
    read -r CHOICE < /dev/tty || { echo ""; info "Goodbye."; break; }
    echo ""

    case "${CHOICE}" in
        1)
            echo "  ── Set up the app ─────────────────────────────────────────"
            echo ""
            "$APP_DIR/setup.sh" \
                || warn "setup.sh exited with an error — check output above."
            ;;
        2)
            echo "  ── Update the app ─────────────────────────────────────────"
            echo ""
            "$APP_DIR/update.sh" \
                || warn "update.sh exited with an error — check output above."
            ;;
        3)
            echo "  ── Back up my data ────────────────────────────────────────"
            echo ""
            "$APP_DIR/scripts/commands/backup.sh" --quick \
                || warn "Backup exited with an error — check output above."
            ;;
        4)
            echo "  ── Fix something that is broken ───────────────────────────"
            echo ""
            "$APP_DIR/scripts/commands/troubleshoot.sh" || true
            ;;
        5)
            echo "  ── App status and links ───────────────────────────────────"
            echo ""
            docker compose ps 2>/dev/null \
                || warn "Could not run docker compose ps — is Docker running?"
            echo ""
            APP_PORT=""
            if [ -f "$APP_DIR/.env" ]; then
                APP_PORT="$(grep -E '^APP_PORT=' "$APP_DIR/.env" 2>/dev/null \
                    | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
            fi
            APP_PORT="${APP_PORT:-8090}"
            echo "  Events:  http://localhost:${APP_PORT}/#events"
            echo "  Map:     http://localhost:${APP_PORT}/#map"
            echo "  Admin:   http://localhost:${APP_PORT}/admin/#events"
            echo "  Health:  http://localhost:${APP_PORT}/health"
            echo ""
            ;;
        6)
            _advanced_menu
            ;;
        7|q|Q)
            info "Goodbye."
            break
            ;;
        "")
            ;;
        *)
            warn "Unknown choice '${CHOICE}' — enter a number from 1 to 7."
            ;;
    esac

    echo ""
    printf "  Press Enter to return to the menu, or q to quit: "
    NAV=""
    read -r NAV < /dev/tty || { echo ""; info "Goodbye."; break; }
    case "${NAV}" in q|Q) info "Goodbye."; break ;; esac
done

echo ""
