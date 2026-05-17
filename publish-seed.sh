#!/bin/bash
# =============================================================================
# Event Map — Publish seed data to GitHub
#
# Run this after creating a seed snapshot (via the Admin panel or
# ./update-seed.sh) to review and push the updated seed to GitHub.
#
# Usage:
#   ./publish-seed.sh
#
# What this does:
#   1. Verifies you are in the repo root
#   2. Verifies api/data/seed.sql exists
#   3. Shows git status and git diff for seed.sql
#   4. Asks for a commit message (default provided)
#   5. Commits ONLY seed-related files unless you choose otherwise
#   6. Asks before pushing to the remote
#   7. Never force-pushes
#
# What this does NOT do:
#   - Delete volumes or containers
#   - Run migrations
#   - Restart services
#   - Force-push
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()  { echo -e "\n${BOLD}--- $1 ---${NC}"; }

echo ""
echo "================================================"
echo "   Event Map — Publish Seed to GitHub"
echo "================================================"
echo ""

# =============================================================================
# Step 1: Verify repo root
# =============================================================================
step "Step 1: Verify location"

if [ ! -f "api/data/seed.sql" ] || [ ! -f "docker-compose.yml" ]; then
    error "Run this script from the repo root (the directory containing docker-compose.yml)."
fi
info "Repo root confirmed."

SEED_FILE="api/data/seed.sql"

# =============================================================================
# Step 2: Verify seed file
# =============================================================================
step "Step 2: Verify seed file"

if [ ! -s "$SEED_FILE" ]; then
    error "$SEED_FILE is missing or empty. Run the Admin seed snapshot first."
fi

SEED_BYTES=$(wc -c < "$SEED_FILE")
info "Seed file: $SEED_FILE ($SEED_BYTES bytes)"

# Check git is available
if ! command -v git &>/dev/null; then
    error "git is not installed or not in PATH."
fi

# =============================================================================
# Step 3: Show git status and diff
# =============================================================================
step "Step 3: Current git status"

git status --short

echo ""
step "Step 4: Changes in seed.sql"

if git diff --quiet -- "$SEED_FILE" && git diff --cached --quiet -- "$SEED_FILE"; then
    warn "seed.sql has no uncommitted changes relative to HEAD."
    warn "If you just ran the Admin snapshot, you may need to rebuild the container"
    warn "with the data volume mounted to see the changes on disk."
    echo ""
    read -r -p "  Continue anyway? [y/N] " CONT
    [[ "${CONT,,}" == "y" ]] || { echo "Cancelled."; exit 0; }
else
    git diff -- "$SEED_FILE"
fi

# =============================================================================
# Step 5: Confirm commit
# =============================================================================
step "Step 5: Commit"

echo ""
echo "  Files to stage and commit:"
echo "    $SEED_FILE"
echo ""
echo "  Default commit message:"
echo "    Update Mollie seed data"
echo ""
read -r -p "  Enter commit message (or press Enter for default): " MSG
MSG="${MSG:-Update Mollie seed data}"

echo ""
echo "  Commit message: $MSG"
echo "  Files: $SEED_FILE"
echo ""
read -r -p "  Stage and commit? [y/N] " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { echo "Cancelled."; exit 0; }

git add "$SEED_FILE"

# Also offer to include any other staged/modified files
OTHER_STAGED=$(git diff --cached --name-only | grep -v "^api/data/seed.sql$" || true)
if [ -n "$OTHER_STAGED" ]; then
    echo ""
    warn "Other files are already staged:"
    echo "$OTHER_STAGED" | sed 's/^/    /'
    read -r -p "  Include them in this commit? [y/N] " INCL_OTHER
    if [[ "${INCL_OTHER,,}" != "y" ]]; then
        # Unstage others
        echo "$OTHER_STAGED" | xargs git restore --staged --
        warn "Unstaged other files. Committing seed.sql only."
    fi
fi

git commit -m "$MSG

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

info "Committed."

# =============================================================================
# Step 6: Push
# =============================================================================
step "Step 6: Push to GitHub"

REMOTE=$(git remote | head -1 || true)
if [ -z "$REMOTE" ]; then
    warn "No git remote configured. Skipping push."
    echo "  Add a remote with: git remote add origin <URL>"
    exit 0
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
info "Remote: $REMOTE, branch: $BRANCH"

echo ""
read -r -p "  Push to $REMOTE/$BRANCH? [y/N] " PUSH
[[ "${PUSH,,}" == "y" ]] || { echo "  Push skipped. Run: git push $REMOTE $BRANCH"; exit 0; }

if ! git push "$REMOTE" "$BRANCH" 2>&1; then
    echo ""
    error "Push failed. Check your GitHub credentials or network connection."
fi

echo ""
echo "================================================"
echo -e "${GREEN}  Seed published to GitHub.${NC}"
echo "================================================"
echo ""
echo "  Branch: $BRANCH → $REMOTE"
echo "  File:   $SEED_FILE"
echo ""
echo "  Tip: future fresh installs will start with this seed."
echo ""
