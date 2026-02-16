#!/bin/bash
# install_all.sh
# Runs all hardening install scripts in correct order.
# Safe to re-run at any time — all scripts are idempotent.
# Usage: bash install_all.sh [--check-only]
# Run from: /a0/usr/hardening/ (repo root)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_ONLY=false

if [ "$1" = "--check-only" ]; then
  CHECK_ONLY=true
fi

# Color output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_section() { echo -e "\n${YELLOW}=== $1 ===${NC}"; }
log_ok()      { echo -e "${GREEN}  ✓ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}  ⚠ $1${NC}"; }
log_err()     { echo -e "${RED}  ✗ $1${NC}"; }

# Scripts listed with their paths relative to repo root
SCRIPTS=(
  "fw-replacements/install_fw_replacements.sh"
  "extensions/install_extensions.sh"
  "extensions/install_failure_tracker.sh"
  "prompt-patches/install_prompt_patches.sh"
  "install_skills.sh"
)

CHECK_SCRIPTS=(
  "fw-replacements/check_fw_upstream.sh"
  "extensions/check_extensions_upstream.sh"
  "prompt-patches/check_prompt_patches_upstream.sh"
  "check_skills_upstream.sh"
)

if [ "$CHECK_ONLY" = true ]; then
  log_section "Checking for upstream changes"

  for script in "${CHECK_SCRIPTS[@]}"; do
    if [ -f "$SCRIPT_DIR/$script" ]; then
      log_section "$script"
      bash "$SCRIPT_DIR/$script"
    else
      log_warn "Not found: $script"
    fi
  done

  echo ""
  echo "Check complete. Run without --check-only to install."
  exit 0
fi

log_section "Agent-Zero Hardening Layer — Full Install"
echo "Source: $SCRIPT_DIR"
echo "Target: /a0/"
echo ""

failed=0

for script in "${SCRIPTS[@]}"; do
  if [ -f "$SCRIPT_DIR/$script" ]; then
    log_section "$script"
    if bash "$SCRIPT_DIR/$script"; then
      log_ok "$script completed"
    else
      log_err "$script failed"
      failed=$((failed + 1))
    fi
  else
    log_warn "Not found (skipping): $script"
  fi
done

echo ""
if [ "$failed" -eq 0 ]; then
  echo -e "${GREEN}All hardening scripts completed successfully.${NC}"
  echo "Start a fresh agent chat to load updated prompts and extensions."
else
  echo -e "${RED}$failed script(s) failed. Review output above.${NC}"
  exit 1
fi
