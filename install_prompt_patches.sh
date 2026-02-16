#!/bin/bash
# install_prompt_patches.sh
# Copies patched prompt files into /a0/prompts/
# Backs up originals before overwriting
# Safe to re-run — will not double-backup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/prompt-patches"
TARGET_DIR="/a0/prompts"
BACKUP_DIR="$TARGET_DIR/.prompt_patch_originals"

if [ ! -d "$TARGET_DIR" ]; then
  echo "ERROR: $TARGET_DIR not found. Are you running inside the agent-zero container?"
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "ERROR: $SOURCE_DIR not found. Run this script from the repo root."
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Installing prompt patches..."
echo ""

INSTALLED=0

for SOURCE_FILE in "$SOURCE_DIR"/*.md; do
  [ -f "$SOURCE_FILE" ] || continue
  FILENAME=$(basename "$SOURCE_FILE")
  TARGET_FILE="$TARGET_DIR/$FILENAME"
  BACKUP_FILE="$BACKUP_DIR/$FILENAME"

  if [ ! -f "$TARGET_FILE" ]; then
    echo "SKIP: $FILENAME not found in $TARGET_DIR (unexpected — check filename)"
    continue
  fi

  # Backup original only if backup doesn't already exist
  if [ ! -f "$BACKUP_FILE" ]; then
    cp "$TARGET_FILE" "$BACKUP_FILE"
    echo "BACKED UP: $FILENAME → .prompt_patch_originals/"
  fi

  cp "$SOURCE_FILE" "$TARGET_FILE"
  echo "INSTALLED: $FILENAME"
  INSTALLED=$((INSTALLED + 1))
done

echo ""
echo "Done. $INSTALLED patch(es) installed."
echo "Originals preserved in $BACKUP_DIR"
echo "To restore: cp $BACKUP_DIR/* $TARGET_DIR/"
