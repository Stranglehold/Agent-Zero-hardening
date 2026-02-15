#!/bin/bash
# install_fw_replacements.sh
# Copies hardened fw.* recovery messages into /a0/prompts/
# Backs up originals before overwriting
# Safe to re-run — will not double-backup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/fw-replacements"
TARGET_DIR="/a0/prompts"
BACKUP_DIR="$TARGET_DIR/.fw_originals"

if [ ! -d "$TARGET_DIR" ]; then
  echo "ERROR: $TARGET_DIR not found. Are you running inside the agent-zero container?"
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "ERROR: $SOURCE_DIR not found. Run this script from the repo root."
  exit 1
fi

mkdir -p "$BACKUP_DIR"

FILES=(
  "fw.msg_misformat.md"
  "fw.msg_repeat.md"
  "fw.msg_nudge.md"
  "fw.error.md"
  "fw.tool_not_found.md"
  "fw.warning.md"
)

echo "Installing hardened recovery messages..."
echo ""

for FILE in "${FILES[@]}"; do
  SOURCE="$SOURCE_DIR/$FILE"
  TARGET="$TARGET_DIR/$FILE"
  BACKUP="$BACKUP_DIR/$FILE"

  if [ ! -f "$SOURCE" ]; then
    echo "SKIP: $FILE not found in source dir"
    continue
  fi

  # Backup original only if backup doesn't already exist
  if [ -f "$TARGET" ] && [ ! -f "$BACKUP" ]; then
    cp "$TARGET" "$BACKUP"
    echo "BACKED UP: $FILE → .fw_originals/"
  fi

  cp "$SOURCE" "$TARGET"
  echo "INSTALLED: $FILE"
done

echo ""
echo "Done. Originals preserved in $BACKUP_DIR"
echo "To restore originals: cp $BACKUP_DIR/* $TARGET_DIR/"
