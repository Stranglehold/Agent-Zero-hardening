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

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_section() { echo -e "\n${YELLOW}=== $1 ===${NC}"; }
log_ok()      { echo -e "${GREEN}  ✓ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}  ⚠ $1${NC}"; }
log_err()     { echo -e "${RED}  ✗ $1${NC}"; }

# Each entry is "subdirectory|script_name"
# install_all.sh cds into the subdirectory before running so SCRIPT_DIR
# inside each sub-script resolves to its own directory correctly.
# Use ".|script_name" for scripts that live at repo root.
SCRIPTS=(
  "fw-replacements|install_fw_replacements.sh"
  "extensions|install_extensions.sh"
  "extensions|install_failure_tracker.sh"
  "prompt-patches|install_prompt_patches.sh"
  ".|install_skills.sh"
)

CHECK_SCRIPTS=(
  "fw-replacements|check_fw_upstream.sh"
  "extensions|check_extensions_upstream.sh"
  "prompt-patches|check_prompt_patches_upstream.sh"
  ".|check_skills_upstream.sh"
)

run_script() {
  local subdir="$1"
  local script="$2"
  local target_dir

  if [ "$subdir" = "." ]; then
    target_dir="$SCRIPT_DIR"
  else
    target_dir="$SCRIPT_DIR/$subdir"
  fi

  if [ ! -f "$target_dir/$script" ]; then
    log_warn "Not found (skipping): $subdir/$script"
    return 0
  fi

  (cd "$target_dir" && bash "$script")
}

if [ "$CHECK_ONLY" = true ]; then
  log_section "Checking for upstream changes"

  for entry in "${CHECK_SCRIPTS[@]}"; do
    subdir="${entry%%|*}"
    script="${entry##*|}"
    log_section "$subdir/$script"
    run_script "$subdir" "$script"
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

for entry in "${SCRIPTS[@]}"; do
  subdir="${entry%%|*}"
  script="${entry##*|}"
  log_section "$subdir/$script"
  if run_script "$subdir" "$script"; then
    log_ok "$script completed"
  else
    log_err "$script failed"
    failed=$((failed + 1))
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
