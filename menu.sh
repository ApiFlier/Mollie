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

# All docker compose calls use APP_DIR as project root.
cd "$APP_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }

# =============================================================================
# Advanced tools submenu
# =============================================================================
_advanced_menu() {
    while true; do
        echo ""
        echo "  ── Advanced Tools ─────────────────────────────────────────────"
        echo ""
        echo "  These tools manage the repo's baseline seed data and system state."
        echo "  Normal users do not need these — use the main menu for daily tasks."
        echo ""
        echo "  [1] Seed workflow"
        echo -e "  ${DIM}      Refresh, review, or publish api/data/seed.sql${NC}"
        echo -e "  ${DIM}      Does NOT change the running database${NC}"
        echo ""
        echo "  [2] Show recent app logs   (last 40 lines)"
        echo "  [3] Show recent DB logs    (last 40 lines)"
        echo "  [4] Docker Compose status  (docker compose ps)"
        echo ""
        echo "  [5] Back to main menu"
        echo ""
        printf "  Your choice [1-5]: "
        local ADV=""
        read -r ADV < /dev/tty || { echo ""; break; }
        echo ""

        case "$ADV" in
            1)
                echo "  ── Seed workflow ──────────────────────────────────────────────"
                echo ""
                "$APP_DIR/scripts/commands/seed.sh" \
                    || warn "Seed workflow exited with an error — check output above."
                ;;
            2)
                echo ""
                echo -e "  ${DIM}Last 40 lines of app logs:${NC}"
                echo ""
                docker compose logs --tail=40 app 2>/dev/null | sed 's/^/    /' \
                    || warn "Could not retrieve app logs."
                echo ""
                ;;
            3)
                echo ""
                echo -e "  ${DIM}Last 40 lines of DB logs:${NC}"
                echo ""
                docker compose logs --tail=40 db 2>/dev/null | sed 's/^/    /' \
                    || warn "Could not retrieve DB logs."
                echo ""
                ;;
            4)
                echo ""
                docker compose ps 2>/dev/null \
                    || warn "Could not run docker compose ps — is Docker running?"
                echo ""
                ;;
            5|q|Q|"")
                break
                ;;
            *)
                warn "Unknown choice '${ADV}' — enter 1 to 5."
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
# Main menu
# =============================================================================
_show_menu() {
    echo ""
    echo "================================================"
    echo "   Event Map"
    echo "================================================"
    echo ""
    echo -e "  ${BOLD}What would you like to do?${NC}"
    echo ""
    echo "  [1] Set up the app for the first time"
    echo -e "  ${DIM}      Builds containers, generates secrets, loads starter data${NC}"
    echo ""
    echo "  [2] Update the app"
    echo -e "  ${DIM}      Pulls latest code, rebuilds container, checks health${NC}"
    echo ""
    echo "  [3] Back up the database"
    echo -e "  ${DIM}      Quick save to ~/.event-map/backups/ — no seed changes${NC}"
    echo ""
    echo "  [4] Back up database + optionally update starter seed data"
    echo -e "  ${DIM}      Backup, then offer to snapshot the current data for fresh installs${NC}"
    echo ""
    echo "  [5] Troubleshoot or repair common problems"
    echo -e "  ${DIM}      Diagnose issues; optionally restart or rebuild containers${NC}"
    echo ""
    echo "  [6] Show status / running URL"
    echo -e "  ${DIM}      Current container state and local app address${NC}"
    echo ""
    echo "  [7] Advanced tools"
    echo -e "  ${DIM}      Seed workflow, logs, Docker status${NC}"
    echo ""
    echo "  [8] Quit"
    echo ""
}

while true; do
    _show_menu
    printf "  Your choice [1-8]: "
    CHOICE=""
    read -r CHOICE < /dev/tty || { echo ""; info "Goodbye."; break; }
    echo ""

    case "${CHOICE}" in
        1)
            echo "  ── Set up the app ────────────────────────────────────────────"
            echo ""
            "$APP_DIR/setup.sh" \
                || warn "setup.sh exited with an error — check output above."
            ;;
        2)
            echo "  ── Update the app ────────────────────────────────────────────"
            echo ""
            "$APP_DIR/update.sh" \
                || warn "update.sh exited with an error — check output above."
            ;;
        3)
            echo "  ── Quick database backup ─────────────────────────────────────"
            echo ""
            "$APP_DIR/scripts/commands/backup.sh" --quick \
                || warn "Backup exited with an error — check output above."
            ;;
        4)
            echo "  ── Backup + optional seed update ─────────────────────────────"
            echo ""
            "$APP_DIR/scripts/commands/backup.sh" \
                || warn "Backup/seed workflow exited with an error — check output above."
            ;;
        5)
            echo "  ── Troubleshoot / repair ─────────────────────────────────────"
            echo ""
            "$APP_DIR/scripts/commands/troubleshoot.sh" || true
            ;;
        6)
            echo "  ── Status / running URL ──────────────────────────────────────"
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
            echo "  Events:  http://localhost:${APP_PORT}/"
            echo "  Map:     http://localhost:${APP_PORT}/map"
            echo "  Admin:   http://localhost:${APP_PORT}/admin/"
            echo "  Health:  http://localhost:${APP_PORT}/health"
            echo ""
            ;;
        7)
            _advanced_menu
            ;;
        8|q|Q)
            info "Goodbye."
            break
            ;;
        "")
            ;;
        *)
            warn "Unknown choice '${CHOICE}' — enter a number from 1 to 8."
            ;;
    esac

    echo ""
    printf "  Press Enter to return to the menu, or q to quit: "
    NAV=""
    read -r NAV < /dev/tty || { echo ""; info "Goodbye."; break; }
    case "${NAV}" in q|Q) info "Goodbye."; break ;; esac
done

echo ""
