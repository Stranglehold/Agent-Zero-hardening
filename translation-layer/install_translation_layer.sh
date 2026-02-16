#!/usr/bin/env bash
# ============================================================
# install_translation_layer.sh
# Installs the Belief State Tracker (BST) translation layer
# into Agent-Zero as a hist_add_before extension.
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A0_ROOT="${A0_ROOT:-/a0}"
EXT_DIR="$A0_ROOT/python/extensions/before_main_llm_call"
BACKUP_DIR="$SCRIPT_DIR/backups/$(date +%Y%m%d_%H%M%S)"

log()  { echo "[BST-INSTALL] $*"; }
warn() { echo "[BST-INSTALL] WARN: $*"; }
fail() { echo "[BST-INSTALL] ERROR: $*" >&2; exit 1; }

# ── Validate environment ────────────────────────────────────────────────────

[ -d "$A0_ROOT" ]     || fail "Agent-Zero root not found at $A0_ROOT. Set A0_ROOT env var."
[ -d "$EXT_DIR" ]     || mkdir -p "$EXT_DIR" && log "Created extension dir: $EXT_DIR"

# Check source files exist
[ -f "$SCRIPT_DIR/belief_state_tracker.py" ] || fail "belief_state_tracker.py not found in $SCRIPT_DIR"
[ -f "$SCRIPT_DIR/slot_taxonomy.json" ]      || fail "slot_taxonomy.json not found in $SCRIPT_DIR"

# ── Backup existing files if present ────────────────────────────────────────

TARGET_PY="$EXT_DIR/_10_belief_state_tracker.py"
TARGET_JSON="$EXT_DIR/slot_taxonomy.json"

if [ -f "$TARGET_PY" ] || [ -f "$TARGET_JSON" ]; then
    mkdir -p "$BACKUP_DIR"
    [ -f "$TARGET_PY" ]   && cp "$TARGET_PY" "$BACKUP_DIR/"   && log "Backed up existing tracker"
    [ -f "$TARGET_JSON" ] && cp "$TARGET_JSON" "$BACKUP_DIR/" && log "Backed up existing taxonomy"
fi

# ── Install ──────────────────────────────────────────────────────────────────

cp "$SCRIPT_DIR/belief_state_tracker.py" "$TARGET_PY"
log "Installed belief_state_tracker.py → $TARGET_PY"

cp "$SCRIPT_DIR/slot_taxonomy.json" "$TARGET_JSON"
log "Installed slot_taxonomy.json → $TARGET_JSON"

# ── Verify Python syntax ─────────────────────────────────────────────────────

if command -v python3 &>/dev/null; then
    python3 -m py_compile "$TARGET_PY" && log "Python syntax OK" || warn "Syntax check failed — check the file"
else
    warn "python3 not found — skipping syntax check"
fi

# ── Verify JSON ───────────────────────────────────────────────────────────────

if command -v python3 &>/dev/null; then
    python3 -c "import json; json.load(open('$TARGET_JSON'))" && log "JSON valid" || fail "slot_taxonomy.json is invalid JSON"
fi

# ── Check for other hist_add_before extensions (ordering info) ───────────────

OTHER_EXTS=$(find "$EXT_DIR" -name "*.py" ! -name "_10_belief_state_tracker.py" | sort)
if [ -n "$OTHER_EXTS" ]; then
    log "Other before_main_llm_call extensions detected:"
    echo "$OTHER_EXTS" | while read -r ext; do
        log "  $ext"
    done
    log "BST is prefixed _10_ so it runs before _20_context_watchdog.py — no rename needed."
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
log "Translation layer installed successfully."
log ""
log "Files:"
log "  $TARGET_PY"
log "  $TARGET_JSON"
log ""
log "Hook: before_main_llm_call (runs as _10_, before existing _20_context_watchdog.py)"
log "To add new intent domains: edit slot_taxonomy.json only — no code changes required."
echo ""
