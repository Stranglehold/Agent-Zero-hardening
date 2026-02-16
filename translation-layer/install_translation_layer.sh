#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAYER_DIR="$SCRIPT_DIR"
TARGET_DIR="/a0/python/extensions/before_main_llm_call"

echo "================================================================"
echo "Installing Translation Layer (Belief State Tracker)"
echo "================================================================"

# Verify source files exist
if [[ ! -f "$LAYER_DIR/_10_belief_state_tracker.py" ]]; then
    echo "ERROR: _10_belief_state_tracker.py not found in $LAYER_DIR"
    exit 1
fi

if [[ ! -f "$LAYER_DIR/slot_taxonomy.json" ]]; then
    echo "ERROR: slot_taxonomy.json not found in $LAYER_DIR"
    exit 1
fi

# Ensure target directory exists
mkdir -p "$TARGET_DIR"

# Backup existing files if present
timestamp=$(date +%Y%m%d_%H%M%S)
if [[ -f "$TARGET_DIR/_10_belief_state_tracker.py" ]]; then
    backup="$TARGET_DIR/_10_belief_state_tracker.py.backup_$timestamp"
    echo "→ Backing up existing BST to: $backup"
    cp "$TARGET_DIR/_10_belief_state_tracker.py" "$backup"
fi

if [[ -f "$TARGET_DIR/slot_taxonomy.json" ]]; then
    backup="$TARGET_DIR/slot_taxonomy.json.backup_$timestamp"
    echo "→ Backing up existing taxonomy to: $backup"
    cp "$TARGET_DIR/slot_taxonomy.json" "$backup"
fi

# Install files
echo "→ Installing _10_belief_state_tracker.py"
cp "$LAYER_DIR/_10_belief_state_tracker.py" "$TARGET_DIR/"

echo "→ Installing slot_taxonomy.json"
cp "$LAYER_DIR/slot_taxonomy.json" "$TARGET_DIR/"

# Clear Python cache to force reload
if [[ -d "$TARGET_DIR/__pycache__" ]]; then
    echo "→ Clearing Python cache"
    rm -rf "$TARGET_DIR/__pycache__"
fi

# Set permissions
chmod 644 "$TARGET_DIR/_10_belief_state_tracker.py"
chmod 644 "$TARGET_DIR/slot_taxonomy.json"

echo ""
echo "✓ Translation layer installed successfully"
echo ""
echo "Files installed to: $TARGET_DIR"
echo "  - _10_belief_state_tracker.py"
echo "  - slot_taxonomy.json"
echo ""
echo "Next: Start a fresh agent chat and send an ambiguous message like"
echo "      'refactor agent.py' to verify BST is running."
echo "      Check logs for [BST] lines."
echo ""
echo "================================================================"
