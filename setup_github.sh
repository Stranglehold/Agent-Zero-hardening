#!/bin/bash
# setup_github.sh
# One-time setup: connects /a0/usr/hardening to GitHub remote.
# Reads GitHub credentials from /a0/usr/secrets.env — never prompts interactively.
# Run once after first docker pull or fresh container.
# Usage: bash setup_github.sh
#
# Required entries in /a0/usr/secrets.env:
#   GITHUB_USER=your_github_username
#   GITHUB_PAT=your_personal_access_token
#
# Generate a PAT at: https://github.com/settings/tokens
# Required scope: repo

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_FILE="/a0/usr/secrets.env"
REPO_PATH="Stranglehold/Agent-Zero-hardening"
BRANCH="main"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
log_warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
log_err()  { echo -e "${RED}  ✗ $1${NC}"; }

echo "Setting up GitHub remote for Agent-Zero hardening layer..."
echo ""

# ── Read credentials from secrets.env ────────────────────────────────────────
if [ ! -f "$SECRETS_FILE" ]; then
  log_err "Secrets file not found: $SECRETS_FILE"
  echo ""
  echo "Create it and add your GitHub credentials:"
  echo "  echo 'GITHUB_USER=your_username' >> $SECRETS_FILE"
  echo "  echo 'GITHUB_PAT=your_token'     >> $SECRETS_FILE"
  echo ""
  echo "Generate a PAT at: https://github.com/settings/tokens (scope: repo)"
  exit 1
fi

# Parse KEY=VALUE pairs, ignoring comments and blank lines
_read_secret() {
  grep -E "^$1=" "$SECRETS_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '\r\n'
}

GITHUB_USER="$(_read_secret GITHUB_USER)"
GITHUB_PAT="$(_read_secret GITHUB_PAT)"

if [ -z "$GITHUB_USER" ]; then
  log_err "GITHUB_USER not found in $SECRETS_FILE"
  echo "  Add: GITHUB_USER=your_github_username"
  exit 1
fi

if [ -z "$GITHUB_PAT" ]; then
  log_err "GITHUB_PAT not found in $SECRETS_FILE"
  echo "  Add: GITHUB_PAT=your_personal_access_token"
  echo "  Generate at: https://github.com/settings/tokens (scope: repo)"
  exit 1
fi

log_ok "Credentials loaded from secrets.env"

# Build authenticated remote URL — token embedded, never echoed
REMOTE_URL="https://${GITHUB_USER}:${GITHUB_PAT}@github.com/${REPO_PATH}.git"
DISPLAY_URL="https://${GITHUB_USER}:***@github.com/${REPO_PATH}.git"

echo "  Remote: $DISPLAY_URL"
echo ""

# ── Initialize git if needed ──────────────────────────────────────────────────
cd "$SCRIPT_DIR"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  git init
  git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH"
  log_ok "Git repository initialized"
else
  log_ok "Git repository already initialized"
fi

# ── Configure git identity ────────────────────────────────────────────────────
git config user.email "${GITHUB_USER}@users.noreply.github.com"
git config user.name "$GITHUB_USER"

# Suppress credential prompts — if token is wrong, fail immediately
git config credential.helper ""
log_ok "Git identity configured"

# ── Set remote with embedded credentials ─────────────────────────────────────
if git remote get-url origin > /dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
  log_ok "Remote 'origin' updated"
else
  git remote add origin "$REMOTE_URL"
  log_ok "Remote 'origin' added"
fi

# ── Stage and commit any uncommitted changes ──────────────────────────────────
git add .
git diff --cached --quiet || git commit -m "sync: local state $(date +%Y-%m-%d)" 2>/dev/null || true

# ── Pull remote state if it has history ───────────────────────────────────────
echo ""
echo "Syncing with GitHub..."

if git fetch origin "$BRANCH" 2>/dev/null; then
  REMOTE_COMMITS=$(git rev-list HEAD..origin/"$BRANCH" --count 2>/dev/null || echo "0")
  if [ "$REMOTE_COMMITS" -gt 0 ]; then
    git pull origin "$BRANCH" --allow-unrelated-histories -m "merge: initial github sync" 2>/dev/null || true
    log_ok "Merged $REMOTE_COMMITS remote commit(s)"
  else
    log_ok "Remote already in sync"
  fi
else
  log_warn "Remote fetch failed or repo is empty — will push fresh"
fi

# ── Push ──────────────────────────────────────────────────────────────────────
if git push -u origin "$BRANCH" 2>/dev/null; then
  log_ok "Pushed to github.com/${REPO_PATH}"
else
  log_err "Push failed — check that GITHUB_PAT has 'repo' scope"
  echo "  Regenerate at: https://github.com/settings/tokens"
  exit 1
fi

echo ""
echo -e "${GREEN}Setup complete.${NC}"
echo ""
echo "Future workflow:"
echo "  bash update.sh        — pull from GitHub + redeploy everything"
echo "  bash install_all.sh   — redeploy without pulling"
echo ""
echo "To push local changes:"
echo "  cd $SCRIPT_DIR"
echo "  git add . && git commit -m 'your message' && git push"
