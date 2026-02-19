#!/bin/bash
# Layer: Memory Classification System (Hardening Layer 7)
# Installs the four-axis memory classification engine and relevance filter.
# Backs up any existing files before overwriting.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Source directories
CLASSIFIER_SRC="$REPO_DIR/extensions/monologue_end"
FILTER_SRC="$REPO_DIR/extensions/message_loop_prompts_after"

# Target directories
EXT_ROOT="/a0/usr/extensions"
CLASSIFIER_TARGET="$EXT_ROOT/monologue_end"
FILTER_TARGET="$EXT_ROOT/message_loop_prompts_after"
MEMORY_DIR="/a0/usr/memory"
CONFIG_TARGET="$MEMORY_DIR/classification_config.json"

echo "[MEM-CLASS] Installing memory classification system..."

# ── Create target directories ─────────────────────────────────────
mkdir -p "$CLASSIFIER_TARGET"
mkdir -p "$FILTER_TARGET"
mkdir -p "$MEMORY_DIR"

# ── Backup existing files ─────────────────────────────────────────
backup_if_exists() {
    local target="$1"
    if [ -f "$target" ]; then
        local backup="${target}.bak.$(date +%Y%m%d_%H%M%S)"
        cp "$target" "$backup"
        echo "[MEM-CLASS] Backed up: $target"
    fi
}

# ── Install classifier extension ──────────────────────────────────
backup_if_exists "$CLASSIFIER_TARGET/_55_memory_classifier.py"
cp "$CLASSIFIER_SRC/_55_memory_classifier.py" "$CLASSIFIER_TARGET/"
echo "[MEM-CLASS] Installed: monologue_end/_55_memory_classifier.py"

# ── Install relevance filter extension ────────────────────────────
backup_if_exists "$FILTER_TARGET/_55_memory_relevance_filter.py"
cp "$FILTER_SRC/_55_memory_relevance_filter.py" "$FILTER_TARGET/"
echo "[MEM-CLASS] Installed: message_loop_prompts_after/_55_memory_relevance_filter.py"

# ── Install config (read-merge-write) ─────────────────────────────
if [ ! -f "$CONFIG_TARGET" ]; then
    cp "$CLASSIFIER_SRC/memory_classification_config.json" "$CONFIG_TARGET"
    echo "[MEM-CLASS] Created default config: $CONFIG_TARGET"
else
    echo "[MEM-CLASS] Config already exists: $CONFIG_TARGET (not overwriting)"
fi

# ── Clear pycache ─────────────────────────────────────────────────
for d in "$CLASSIFIER_TARGET/__pycache__" "$FILTER_TARGET/__pycache__"; do
    if [ -d "$d" ]; then
        rm -rf "$d"
        echo "[MEM-CLASS] Cleared: $d"
    fi
done

echo "[MEM-CLASS] Done."
echo "[MEM-CLASS] Classification runs automatically after memory storage (monologue_end)"
echo "[MEM-CLASS] Relevance filter runs automatically after recall (message_loop_prompts_after)"
echo "[MEM-CLASS] Config: $CONFIG_TARGET"
