#!/bin/bash
# =============================================================================
# Event Map — Management Menu
#
# One-stop menu for all common operations. Safe to run any time.
# Each option calls an existing script — no logic is duplicated here.
#
# Usage:
#   ./manage.sh
#
# What this does NOT do:
#   - Does not take destructive action on its own
#   - Does not commit, push, or stage files unless you confirm it within a sub-script
#   - Does not delete volumes or database data
#   - Does not modify .env or .htpasswd
# =============================================================================

# No set -e: menu loop must survive sub-script failures.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }

_show_menu() {
    echo ""
    echo "================================================"
    echo "   Event Map — Manage"
    echo "================================================"
    echo ""
    echo -e "  ${BOLD}What would you like to do?${NC}"
    echo ""
    echo "  [1] First-time setup"
    echo -e "  ${DIM}      Build containers, generate secrets, load seed data${NC}"
    echo ""
    echo "  [2] Update the app"
    echo -e "  ${DIM}      Pull latest code, rebuild container, health check${NC}"
    echo ""
    echo "  [3] Back up database  (quick — no seed changes)"
    echo -e "  ${DIM}      Save DB snapshot to ~/.event-map/backups/${NC}"
    echo ""
    echo "  [4] Back up database + optionally refresh/publish seed"
    echo -e "  ${DIM}      Full workflow: backup, then offer to update seed.sql for fresh installs${NC}"
    echo ""
    echo "  [5] Seed workflow: refresh / review / publish"
    echo -e "  ${DIM}      Manage api/data/seed.sql — does NOT change the running database${NC}"
    echo ""
    echo "  [6] Troubleshoot / repair"
    echo -e "  ${DIM}      Diagnose issues; optionally restart or rebuild containers${NC}"
    echo ""
    echo "  [7] Show status / running URL"
    echo -e "  ${DIM}      Container state and local app address${NC}"
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
            echo "  ── First-time setup ──────────────────────────────────────────"
            echo ""
            "$APP_DIR/setup.sh" || warn "setup.sh exited with an error — check output above."
            ;;
        2)
            echo "  ── Updating app ──────────────────────────────────────────────"
            echo ""
            "$APP_DIR/update.sh" || warn "update.sh exited with an error — check output above."
            ;;
        3)
            echo "  ── Quick database backup ─────────────────────────────────────"
            echo ""
            "$APP_DIR/backup.sh" --quick || warn "Backup exited with an error — check output above."
            ;;
        4)
            echo "  ── Backup + seed workflow ────────────────────────────────────"
            echo ""
            "$APP_DIR/backup.sh" || warn "Backup/seed workflow exited with an error — check output above."
            ;;
        5)
            echo "  ── Seed workflow ─────────────────────────────────────────────"
            echo ""
            "$APP_DIR/seed.sh" || warn "seed.sh exited with an error — check output above."
            ;;
        6)
            echo "  ── Troubleshoot / repair ─────────────────────────────────────"
            echo ""
            "$APP_DIR/troubleshoot.sh" || true
            ;;
        7)
            echo "  ── Status / running URL ──────────────────────────────────────"
            echo ""
            docker compose --project-directory "$APP_DIR" ps 2>/dev/null \
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
