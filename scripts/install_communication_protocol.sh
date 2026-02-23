#!/bin/bash
# Layer: Communication Protocol
# Installs the Exocortex communication protocol prompt patch.
# Deploys the trimmed protocol to /a0/prompts/ and adds the include
# line to agent.system.main.md if not already present.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TARGET_PROMPTS="/a0/prompts"
MAIN_PROMPT="$TARGET_PROMPTS/agent.system.main.md"
PROTOCOL_FILE="agent.system.main.communication_protocol.md"
INCLUDE_LINE='{{ include "agent.system.main.communication_protocol.md" }}'

echo "[CommProtocol] Installing communication protocol..."

# Deploy protocol file
cp "$REPO_DIR/prompts/$PROTOCOL_FILE" "$TARGET_PROMPTS/"
echo "[CommProtocol] Installed protocol prompt: $PROTOCOL_FILE"

# Add include line to agent.system.main.md if not present
if grep -qF "$PROTOCOL_FILE" "$MAIN_PROMPT"; then
    echo "[CommProtocol] Include already present in agent.system.main.md"
else
    # Insert after the role include line
    ROLE_LINE='{{ include "agent.system.main.role.md" }}'
    if grep -qF "$ROLE_LINE" "$MAIN_PROMPT"; then
        # Backup first
        if [ ! -f "$TARGET_PROMPTS/.prompt_patch_originals/agent.system.main.md" ]; then
            mkdir -p "$TARGET_PROMPTS/.prompt_patch_originals"
            cp "$MAIN_PROMPT" "$TARGET_PROMPTS/.prompt_patch_originals/agent.system.main.md"
            echo "[CommProtocol] Backed up original agent.system.main.md"
        fi
        # Insert include line after role include
        sed -i "/$ROLE_LINE/a\\$INCLUDE_LINE" "$MAIN_PROMPT"
        echo "[CommProtocol] Added include to agent.system.main.md (after role)"
    else
        echo "[CommProtocol] WARNING: Could not find role include line in agent.system.main.md"
        echo "[CommProtocol] Add manually: $INCLUDE_LINE"
    fi
fi

# Clear pycache
rm -rf "$TARGET_PROMPTS/__pycache__/" 2>/dev/null
echo "[CommProtocol] Cleared __pycache__"

echo "[CommProtocol] Done. Protocol active on next chat."
