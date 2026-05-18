#!/bin/bash
# =============================================================================
# Event Map — Backup the running database
#
# Saves a full compressed backup of the live database to:
#   ~/.event-map/backups/event-map-TIMESTAMP.sql.gz   (kept forever)
#   ~/.event-map/backups/event-map-latest.sql.gz       (always the most recent)
#
# Run this any time before making data changes, before updating,
# or whenever you want a known-good restore point.
#
# Usage:
#   ./menu.sh  →  option [3] or [4]
#   scripts/commands/backup.sh           — backup, then optionally offer seed refresh/publish
#   scripts/commands/backup.sh --quick   — backup only, no seed prompts
#
# What this does NOT do:
#   - Does not modify seed.sql unless you explicitly answer y
#   - Does not commit or push unless you explicitly confirm it
#   - Does not restart containers or delete any data
# =============================================================================

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

QUICK=false
if [[ "${1:-}" == "--quick" ]]; then
    QUICK=true
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }

echo ""
echo "================================================"
echo "   Event Map — Backup Database"
echo "================================================"
echo ""
echo "  Saves a full backup of the running database."
echo "  Backup location: ~/.event-map/backups/"
echo ""
echo "  This does NOT change seed.sql, commit, push,"
echo "  restart containers, or delete any data."
echo ""

# Run the backup. Exits non-zero on failure — seed prompts are skipped.
"$APP_DIR/scripts/backup-db.sh"

if [ "$QUICK" = true ]; then
    echo ""
    info "Quick backup complete. Run ./menu.sh → [4] to also manage seed.sql."
    echo ""
    exit 0
fi

# =============================================================================
# Optional: refresh the repo baseline seed
# =============================================================================

echo ""
echo -e "${BOLD}  Optional: also refresh api/data/seed.sql${NC}"
echo ""
echo "  What is seed.sql?"
echo "    The starter data loaded on fresh installs — farms, markets, places."
echo "    It lives in the repo and may be PUBLIC on GitHub."
echo "    Refreshing it snapshots the current curated database into that file."
echo ""
echo "  What a seed refresh does:"
echo "    ✓ Updates api/data/seed.sql in the local repo"
echo "    ✗ Does NOT change the running database"
echo "    ✗ Does NOT commit or push — publishing is always a separate, reviewed step"
echo ""
echo "  Skip this if you only needed a safety backup."
echo ""
printf "  Refresh api/data/seed.sql from this database? [y/N] "
SEED_CHOICE=""
read -r SEED_CHOICE < /dev/tty || true
echo ""

case "${SEED_CHOICE}" in
    y|Y)
        echo "  ── Refreshing seed ──────────────────────────────────────────"
        echo ""
        if "$APP_DIR/scripts/commands/update-seed.sh"; then
            echo ""
            info "Seed refreshed. api/data/seed.sql updated — not yet committed or pushed."
            echo ""

            # Show what changed
            DIFF_STAT="$(git -C "$APP_DIR" diff --stat -- api/data/seed.sql 2>/dev/null || true)"
            if [ -n "$DIFF_STAT" ]; then
                echo -e "${BOLD}  Changes in seed.sql:${NC}"
                echo ""
                echo "$DIFF_STAT" | sed 's/^/    /'
                echo ""
            fi

            # Offer to show full diff
            printf "  Show the full seed.sql diff? [y/N] "
            SHOW_DIFF=""
            read -r SHOW_DIFF < /dev/tty || true
            echo ""
            if [[ "${SHOW_DIFF,,}" == "y" ]]; then
                echo "  ── Full diff (first 300 lines) ──────────────────────────────"
                echo ""
                git -C "$APP_DIR" diff -- api/data/seed.sql 2>/dev/null | head -300 | sed 's/^/  /' || true
                echo ""
            fi

            # =================================================================
            # Offer to publish
            # =================================================================
            echo "  ── Publish to GitHub? ───────────────────────────────────────"
            echo ""
            echo "  Publishing commits seed.sql and pushes it to the remote repo."
            echo -e "  ${YELLOW}This repo may be PUBLIC. Review carefully before publishing.${NC}"
            echo "  Never publish private addresses, coordinates, or credentials."
            echo ""

            # Dirty-tree check: refuse publish if files OTHER than seed-related are modified
            DIRTY_OTHER="$(git -C "$APP_DIR" status --porcelain 2>/dev/null \
                | grep -v '^??' \
                | awk '{print $NF}' \
                | grep -v '^api/data/seed' \
                || true)"
            if [ -n "$DIRTY_OTHER" ]; then
                warn "Your working tree has other modified files — publish refused:"
                echo "$DIRTY_OTHER" | sed 's/^/    /'
                echo ""
                warn "Commit, stash, or discard those changes before publishing the seed."
                warn "Run: git status   to review"
                echo ""
                echo "  To publish the seed later:  ./menu.sh  → [7] Advanced tools → Seed workflow"
                echo ""
            else
                printf "  Publish seed.sql to GitHub now? [y/N] "
                PUB_CHOICE=""
                read -r PUB_CHOICE < /dev/tty || true
                echo ""
                if [[ "${PUB_CHOICE,,}" == "y" ]]; then
                    exec "$APP_DIR/scripts/commands/publish-seed.sh"
                else
                    info "Publish skipped."
                    echo ""
                    echo "  To publish later:  ./menu.sh  → [7] Advanced tools → Seed workflow"
                    echo ""
                fi
            fi
        else
            echo ""
            warn "Seed refresh did not complete cleanly."
            warn "Your database backup is still safe — check the output above."
            echo ""
        fi
        ;;
    *)
        echo ""
        info "Seed not refreshed. Run ./menu.sh → [7] Advanced tools to manage seed.sql."
        echo ""
        ;;
esac
