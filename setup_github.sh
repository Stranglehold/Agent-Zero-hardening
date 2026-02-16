#!/bin/bash
# setup_github.sh
# One-time setup: connects /a0/usr/hardening to GitHub remote.
# Run once after first docker pull or fresh container.
# Usage: bash setup_github.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_URL="https://github.com/Stranglehold/Agent-Zero-hardening.git"
BRANCH="main"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
log_warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
log_err()  { echo -e "${RED}  ✗ $1${NC}"; }

cd "$SCRIPT_DIR"

echo "Setting up GitHub remote for Agent-Zero hardening layer..."
echo "Directory: $SCRIPT_DIR"
echo "Remote:    $REMOTE_URL"
echo ""

# ── Initialize git if needed ──────────────────────────────────────────────────
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  git init
  git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH"
  log_ok "Git repository initialized"
else
  log_ok "Git repository already initialized"
fi

# ── Set remote ────────────────────────────────────────────────────────────────
if git remote get-url origin > /dev/null 2>&1; then
  EXISTING="$(git remote get-url origin)"
  if [ "$EXISTING" = "$REMOTE_URL" ]; then
    log_ok "Remote 'origin' already set correctly"
  else
    log_warn "Remote 'origin' exists with different URL: $EXISTING"
    echo "  Updating to: $REMOTE_URL"
    git remote set-url origin "$REMOTE_URL"
    log_ok "Remote updated"
  fi
else
  git remote add origin "$REMOTE_URL"
  log_ok "Remote 'origin' added"
fi

# ── Configure git identity if not set ─────────────────────────────────────────
if ! git config user.email > /dev/null 2>&1; then
  git config user.email "agent-zero@local"
  git config user.name "Agent-Zero Hardening"
  log_ok "Git identity configured (local)"
fi

# ── Stage and commit any uncommitted changes ──────────────────────────────────
if ! git diff --quiet HEAD 2>/dev/null || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  git add .
  git commit -m "sync: local state before github push" 2>/dev/null || true
  log_ok "Local changes committed"
fi

# ── Pull remote state ─────────────────────────────────────────────────────────
echo ""
echo "Fetching remote..."
if git fetch origin "$BRANCH" 2>/dev/null; then
  # Check if remote has commits we don't have
  REMOTE_COMMITS=$(git rev-list HEAD..origin/"$BRANCH" --count 2>/dev/null || echo "0")
  if [ "$REMOTE_COMMITS" -gt 0 ]; then
    log_warn "Remote has $REMOTE_COMMITS commit(s) not in local branch."
    echo "  Merging remote history..."
    git pull origin "$BRANCH" --allow-unrelated-histories -m "merge: initial github sync"
    log_ok "Merged remote history"
  fi
else
  log_warn "Remote fetch failed — repo may be empty. Will push on first sync."
fi

# ── Push ──────────────────────────────────────────────────────────────────────
echo ""
echo "Pushing to GitHub..."
echo "Note: You may be prompted for credentials."
echo "      Use a Personal Access Token (PAT) as the password."
echo "      Generate one at: https://github.com/settings/tokens"
echo "      Scopes needed: repo"
echo ""

if git push -u origin "$BRANCH"; then
  log_ok "Pushed to $REMOTE_URL"
else
  log_err "Push failed. Check credentials above."
  echo ""
  echo "To push manually after setting credentials:"
  echo "  cd $SCRIPT_DIR && git push -u origin $BRANCH"
  exit 1
fi

echo ""
echo -e "${GREEN}Setup complete.${NC}"
echo "Future workflow:"
echo "  bash update.sh          — pull latest from GitHub and redeploy"
echo "  bash install_all.sh     — redeploy without pulling"
echo ""
echo "To push local changes to GitHub:"
echo "  cd $SCRIPT_DIR"
echo "  git add . && git commit -m 'your message'"
echo "  git push"
