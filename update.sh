#!/bin/bash
# update.sh
# Pulls latest hardening layer from GitHub and redeploys everything.
# Single command to keep your agent-zero instance current.
# Usage: bash update.sh
#        bash update.sh --check-only   (diff upstream changes without installing)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_section() { echo -e "\n${YELLOW}=== $1 ===${NC}"; }
log_ok()      { echo -e "${GREEN}  ✓ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}  ⚠ $1${NC}"; }
log_err()     { echo -e "${RED}  ✗ $1${NC}"; }

CHECK_ONLY=false
if [ "$1" = "--check-only" ]; then
  CHECK_ONLY=true
fi

# ── Step 1: Git pull ──────────────────────────────────────────────────────────
log_section "Pulling latest from GitHub"

cd "$SCRIPT_DIR"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  log_err "Not a git repository: $SCRIPT_DIR"
  echo "Run setup_github.sh first to initialize the remote."
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BEFORE="$(git rev-parse HEAD)"

git fetch origin "$BRANCH"
AFTER="$(git rev-parse origin/$BRANCH)"

if [ "$BEFORE" = "$AFTER" ]; then
  log_ok "Already up to date ($(git rev-parse --short HEAD))"
else
  git pull origin "$BRANCH"
  log_ok "Updated: $(git rev-parse --short $BEFORE) → $(git rev-parse --short HEAD)"
  echo ""
  echo "Changes pulled:"
  git log --oneline "$BEFORE".."$AFTER"
fi

# ── Step 2: Optional upstream check ─────────────────────────────────────────
if [ "$CHECK_ONLY" = true ]; then
  bash "$SCRIPT_DIR/install_all.sh" --check-only
  exit 0
fi

# ── Step 3: Run full install ──────────────────────────────────────────────────
bash "$SCRIPT_DIR/install_all.sh"
