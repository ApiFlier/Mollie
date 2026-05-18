#!/bin/bash
# =============================================================================
# Event Map — Seed workflow helper
#
# Interactive menu for managing api/data/seed.sql — the curated starter data
# that fresh installs begin with.
#
# Usage:
#   ./menu.sh  →  [7] Advanced tools  →  Seed workflow
#   scripts/commands/seed.sh
#
# Menu options:
#   [1] Refresh seed  — snapshot current curated database → seed.sql
#   [2] Review diff   — show what changed in seed.sql since last commit
#   [3] Publish seed  — commit + push seed.sql to GitHub (after review)
#   [4] Cancel
#
# What is the seed?
#   seed.sql is a snapshot of your curated farms, markets, and places.
#   When someone runs ./setup.sh on a fresh install, it loads seed.sql
#   as the starting data. It lives in this repo and may be PUBLIC on GitHub.
#   Never put private addresses, credentials, or personal data in the seed.
#
# What this script does NOT do:
#   - Does not change the running database
#   - Does not restart containers
#   - Does not delete volumes or data
#   - Does not commit or push unless you explicitly choose option [3] and confirm
#
# Important distinction:
#   ./update.sh  — updates the running app container (code changes)
#   seed workflow  — updates api/data/seed.sql (the repo baseline for fresh installs)
#   These are completely separate. Refreshing the seed does NOT restart anything.
# =============================================================================

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }

echo ""
echo "================================================"
echo "   Event Map — Seed Workflow"
echo "================================================"
echo ""
echo -e "  ${BOLD}What is the seed?${NC}"
echo "  api/data/seed.sql holds your curated starter data (farms, markets, places)."
echo "  Fresh installs load it. This file may be PUBLIC on GitHub."
echo "  Refreshing or publishing it does NOT change the running database."
echo ""
echo -e "  ${BOLD}What would you like to do?${NC}"
echo ""
echo "  [1] Refresh seed"
echo "        Current curated database  →  api/data/seed.sql"
echo "        Use after adding or editing places in the admin panel."
echo "        Creates a safety backup first. Does NOT push to GitHub."
echo ""
echo "  [2] Review diff"
echo "        Show what has changed in seed.sql since the last Git commit."
echo "        Always review before publishing."
echo ""
echo "  [3] Publish seed to GitHub"
echo "        Commit seed.sql and push to the remote repository."
echo "        Checks for unrelated dirty files first. Requires confirmation."
echo "        Run option [1] and [2] first."
echo ""
echo "  [4] Cancel — do nothing"
echo ""
printf "  Your choice [1/2/3/4]: "
CHOICE=""
read -r CHOICE < /dev/tty || true
echo ""

case "${CHOICE}" in
    1)
        echo "  ── Refreshing seed from running database ──────────────────"
        echo ""
        exec "$APP_DIR/scripts/commands/update-seed.sh"
        ;;
    2)
        echo "  ── Reviewing seed.sql diff ────────────────────────────────"
        echo ""
        if git -C "$APP_DIR" diff --quiet -- api/data/seed.sql \
                && git -C "$APP_DIR" diff --cached --quiet -- api/data/seed.sql; then
            info "seed.sql has no uncommitted changes — matches the last Git commit."
            echo ""
            echo "  If you just ran option [1] (Refresh seed) and see no diff here,"
            echo "  the database content may already match the last committed seed."
        else
            git -C "$APP_DIR" diff -- api/data/seed.sql
            echo ""
            info "Review complete. Run option [3] to publish."
        fi
        echo ""
        ;;
    3)
        echo "  ── Publishing seed to GitHub ──────────────────────────────"
        echo ""

        # Check: does seed.sql have any changes to publish?
        if git -C "$APP_DIR" diff --quiet -- api/data/seed.sql \
                && git -C "$APP_DIR" diff --cached --quiet -- api/data/seed.sql; then
            warn "seed.sql has no uncommitted changes — nothing new to publish."
            echo ""
            echo "  Run option [1] to refresh the seed first."
            echo "  Or run option [2] to check the current state."
            echo ""
            exit 0
        fi

        # Dirty-tree check: refuse if files OTHER than seed-related are modified/staged
        DIRTY_OTHER="$(git -C "$APP_DIR" status --porcelain 2>/dev/null \
            | grep -v '^??' \
            | awk '{print $NF}' \
            | grep -v '^api/data/seed' \
            || true)"
        if [ -n "$DIRTY_OTHER" ]; then
            warn "Your working tree has other modified files — publish refused:"
            echo ""
            echo "$DIRTY_OTHER" | sed 's/^/    /'
            echo ""
            warn "Publishing seed alongside unrelated changes can be confusing."
            warn "Commit, stash, or discard those changes first, then re-run option [3]."
            echo ""
            echo "  Run: git status   to review what's changed"
            echo ""
            exit 0
        fi

        # Show what's about to be published
        echo "  Changes being published:"
        echo ""
        git -C "$APP_DIR" diff --stat -- api/data/seed.sql 2>/dev/null | sed 's/^/    /' || true
        echo ""

        # Public repo warning
        echo -e "  ${YELLOW}This repo may be PUBLIC on GitHub.${NC}"
        echo "  Review the diff (option [2]) to confirm no private data is included."
        echo "  Never publish home addresses, exact private coordinates, or credentials."
        echo ""

        exec "$APP_DIR/scripts/commands/publish-seed.sh"
        ;;
    4|"")
        info "Cancelled. No changes made."
        ;;
    *)
        warn "Unknown choice '${CHOICE}'. No changes made."
        ;;
esac
