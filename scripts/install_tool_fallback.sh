#!/bin/bash
# Layer: Tool Fallback Chain
# Installs tool failure classification and fallback advisory extensions

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_EXT="$REPO_DIR/extensions"
TARGET_EXT="/a0/python/extensions"

echo "[ToolFallback] Installing tool fallback chain..."

# tool_execute_after — failure logger
AFTER_DIR="$TARGET_EXT/tool_execute_after"
mkdir -p "$AFTER_DIR"
if [ -f "$SOURCE_EXT/tool_execute_after/_30_tool_fallback_logger.py" ]; then
    cp "$SOURCE_EXT/tool_execute_after/_30_tool_fallback_logger.py" "$AFTER_DIR/"
    echo "[ToolFallback] Installed failure logger"
fi

# tool_execute_before — fallback advisor
BEFORE_DIR="$TARGET_EXT/tool_execute_before"
mkdir -p "$BEFORE_DIR"
if [ -f "$SOURCE_EXT/tool_execute_before/_30_tool_fallback_advisor.py" ]; then
    cp "$SOURCE_EXT/tool_execute_before/_30_tool_fallback_advisor.py" "$BEFORE_DIR/"
    echo "[ToolFallback] Installed fallback advisor"
fi

echo "[ToolFallback] Done. Failure classification and fallback advisory active."
