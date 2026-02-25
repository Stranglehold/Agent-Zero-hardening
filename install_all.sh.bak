#!/bin/bash
# install_all.sh
# Runs all hardening install scripts in correct dependency order.
# Safe to re-run at any time — all scripts are idempotent.
#
# Usage:
#   bash install_all.sh              Install all layers
#   bash install_all.sh --check-only Check for upstream conflicts only
#   bash install_all.sh --layer N    Install only layer N (1-6)
#
# Run from: /a0/usr/hardening/ (repo root)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_ONLY=false
LAYER_ONLY=""

for arg in "$@"; do
  case "$arg" in
    --check-only)  CHECK_ONLY=true ;;
    --layer=*)     LAYER_ONLY="${arg#*=}" ;;
  esac
done

# ── Color output ──────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_header()  { echo -e "\n${BOLD}${CYAN}━━━ $1 ━━━${NC}"; }
log_section() { echo -e "\n${YELLOW}  → $1${NC}"; }
log_ok()      { echo -e "${GREEN}    ✓ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}    ⚠ $1${NC}"; }
log_err()     { echo -e "${RED}    ✗ $1${NC}"; }
log_skip()    { echo -e "    ~ $1 (not found — skipped)"; }

# ── Layer registry ────────────────────────────────────────────────────────────
# Each entry: "LAYER_NUM|LABEL|SCRIPT_PATH"
# Multiple entries with same LAYER_NUM are sub-steps of that layer.

LAYERS=(
  "1|Framework message replacements      |fw-replacements/install_fw_replacements.sh"
  "2|Extensions — retry + watchdog       |extensions/install_extensions.sh"
  "2|Extensions — failure tracker        |extensions/install_failure_tracker.sh"
  "2|Extensions — error comprehension   |scripts/install_error_comprehension.sh"
  "2|Extensions — tool fallback chain   |scripts/install_tool_fallback.sh"
  "2|Extensions — meta-reasoning gate   |scripts/install_meta_gate.sh"
  "2|Extensions — organization kernel   |scripts/install_org_kernel.sh"
  "2|Extensions — supervisor loop       |scripts/install_supervisor_loop.sh"
  "3|Prompt patches                      |prompt-patches/install_prompt_patches.sh"
  "3|Personality loader                  |scripts/install_personalities.sh"
  "3|Communication protocol              |scripts/install_communication_protocol.sh"
  "4|Skills                              |install_skills.sh"
  "5|Translation layer (belief state BST)|translation-layer/install_translation_layer.sh"
  "5|Graph workflow engine              |scripts/install_graph_engine.sh"
  "6|A2A compatibility server           |scripts/install_a2a_server.sh"
  "7|Memory classification system       |scripts/install_memory_classification.sh"
  "8|Ontology layer                     |scripts/install_ontology.sh"
)

CHECK_SCRIPTS=(
  "fw-replacements/check_fw_upstream.sh"
  "extensions/check_extensions_upstream.sh"
  "prompt-patches/check_prompt_patches_upstream.sh"
  "check_skills_upstream.sh"
)

# ── Check-only mode ───────────────────────────────────────────────────────────

if [ "$CHECK_ONLY" = true ]; then
  log_header "Upstream Conflict Check"
  echo "  Comparing installed files against agent-zero upstream..."
  echo ""
  any_changed=0

  for script in "${CHECK_SCRIPTS[@]}"; do
    if [ -f "$SCRIPT_DIR/$script" ]; then
      log_section "$script"
      bash "$SCRIPT_DIR/$script" || any_changed=1
    else
      log_skip "$script"
    fi
  done

  echo ""
  if [ "$any_changed" -eq 0 ]; then
    echo -e "${GREEN}No upstream conflicts. Safe to re-run install_all.sh.${NC}"
  else
    echo -e "${YELLOW}Conflicts detected above. Review diffs before reinstalling.${NC}"
  fi
  exit 0
fi

# ── Install mode ──────────────────────────────────────────────────────────────

log_header "Agent-Zero Hardening Layer — Full Install"
echo "  Source : $SCRIPT_DIR"
echo "  Target : /a0/"
[ -n "$LAYER_ONLY" ] && echo "  Mode   : Layer $LAYER_ONLY only"
echo ""

failed=0
installed=0
skipped=0

for entry in "${LAYERS[@]}"; do
  layer_num="${entry%%|*}"
  rest="${entry#*|}"
  label="${rest%%|*}"
  label="$(echo "$label" | sed 's/[[:space:]]*$//')"   # trim trailing spaces
  script="${rest#*|}"

  # Filter if --layer=N was passed
  if [ -n "$LAYER_ONLY" ] && [ "$layer_num" != "$LAYER_ONLY" ]; then
    continue
  fi

  if [ ! -f "$SCRIPT_DIR/$script" ]; then
    log_skip "Layer $layer_num — $label"
    skipped=$((skipped + 1))
    continue
  fi

  log_section "Layer $layer_num — $label"

  if (cd "$SCRIPT_DIR/$(dirname "$script")" && bash "$(basename "$script")"); then
    log_ok "Completed"
    installed=$((installed + 1))
  else
    log_err "FAILED"
    failed=$((failed + 1))
  fi
done

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
log_header "Summary"
echo "  Completed : $installed"
[ "$skipped" -gt 0 ] && echo "  Skipped   : $skipped (scripts not found)"
[ "$failed"  -gt 0 ] && echo -e "  ${RED}Failed    : $failed${NC}"
echo ""

if [ "$failed" -eq 0 ]; then
  echo -e "${GREEN}${BOLD}All layers installed successfully.${NC}"
  echo ""
  echo "  Deployment map:"
  echo "    Layer 1  fw-replacements   → /a0/prompts/"
  echo "    Layer 2  extensions        → /a0/python/extensions/"
  echo "    Layer 2  org kernel        → /a0/python/extensions/ + /a0/usr/organizations/"
  echo "    Layer 2  supervisor loop   → /a0/python/extensions/message_loop_end/"
  echo "    Layer 3  prompt-patches    → /a0/prompts/"
  echo "    Layer 3  personalities     → /a0/prompts/ + /a0/usr/personalities/"
  echo "    Layer 4  skills            → /a0/skills/"
  echo "    Layer 5  translation-layer → /a0/python/extensions/before_main_llm_call/"
  echo "    Layer 5  graph engine      → /a0/python/extensions/before_main_llm_call/"
  echo "    Layer 6  A2A server        → /a0/python/a2a_server/"
  echo "    Layer 7  memory classify   → /a0/usr/extensions/ + /a0/usr/memory/"
  echo "    Layer 8  ontology layer    → /a0/usr/ontology/ + /a0/python/tools/"
  echo ""
  echo "  Restart agent-zero or start a fresh chat to load all changes."
  echo "  A2A server: python -m a2a_server.run (port 8200)"
else
  echo -e "${RED}${BOLD}$failed step(s) failed. Review output above before continuing.${NC}"
  exit 1
fi
