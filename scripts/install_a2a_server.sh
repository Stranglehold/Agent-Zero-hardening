#!/bin/bash
# Layer: A2A Compatibility Server (Organization Kernel Phase 4)
# Installs the A2A protocol adapter alongside Agent-Zero.
# Backs up any existing a2a_server directory before overwriting.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_DIR="$REPO_DIR/a2a_server"
TARGET_DIR="/a0/python/a2a_server"
ORG_DIR="/a0/usr/organizations"
CONFIG_PATH="$ORG_DIR/a2a_config.json"

echo "[A2A] Installing A2A compatibility server..."

# ── Dependencies ────────────────────────────────────────────────
echo "[A2A] Checking dependencies..."
if ! python3 -c "import aiohttp" 2>/dev/null; then
    echo "[A2A] Installing aiohttp..."
    pip install aiohttp --break-system-packages 2>/dev/null || pip install aiohttp
fi

# ── Backup existing installation ────────────────────────────────
if [ -d "$TARGET_DIR" ]; then
    BACKUP_DIR="$TARGET_DIR/../a2a_server_backup_$(date +%Y%m%d_%H%M%S)"
    cp -r "$TARGET_DIR" "$BACKUP_DIR"
    echo "[A2A] Backed up existing installation to $BACKUP_DIR"
fi

# ── Install server module ───────────────────────────────────────
mkdir -p "$TARGET_DIR"
cp "$SOURCE_DIR/__init__.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/config.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/agent_card.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/task_registry.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/translation.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/agent_bridge.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/server.py" "$TARGET_DIR/"
cp "$SOURCE_DIR/run.py" "$TARGET_DIR/"

echo "[A2A] Installed server module to $TARGET_DIR"

# ── Install default config (read-merge-write) ───────────────────
if [ ! -f "$CONFIG_PATH" ]; then
    mkdir -p "$ORG_DIR"
    cp "$SOURCE_DIR/a2a_config.default.json" "$CONFIG_PATH"
    echo "[A2A] Created default config at $CONFIG_PATH"
else
    echo "[A2A] Config already exists at $CONFIG_PATH (not overwriting)"
fi

# ── Clear pycache ────────────────────────────────────────────────
if [ -d "$TARGET_DIR/__pycache__" ]; then
    rm -rf "$TARGET_DIR/__pycache__"
    echo "[A2A] Cleared __pycache__"
fi

echo "[A2A] Done. Start with: python -m a2a_server.run"
echo "[A2A] Agent Card: http://localhost:8200/.well-known/agent.json"
