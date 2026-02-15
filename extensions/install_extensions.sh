#!/bin/bash
# install_extensions.sh
# Copies hardening extensions into /a0/python/extensions/
# Creates target subdirectories if needed
# Backs up any existing files with the same name before overwriting
# Safe to re-run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/extensions"
TARGET_ROOT="/a0/python/extensions"
BACKUP_ROOT="$TARGET_ROOT/.hardening_originals"

if [ ! -d "$TARGET_ROOT" ]; then
  echo "ERROR: $TARGET_ROOT not found. Are you running inside the agent-zero container?"
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "ERROR: $SOURCE_DIR not found. Run this script from the repo root."
  exit 1
fi

echo "Installing hardening extensions..."
echo ""

INSTALLED=0
SKIPPED=0

# Walk source directory — each subfolder is an extension point
for EXT_POINT_DIR in "$SOURCE_DIR"/*/; do
  EXT_POINT=$(basename "$EXT_POINT_DIR")
  TARGET_DIR="$TARGET_ROOT/$EXT_POINT"
  BACKUP_DIR="$BACKUP_ROOT/$EXT_POINT"

  mkdir -p "$TARGET_DIR"
  mkdir -p "$BACKUP_DIR"

  for SOURCE_FILE in "$EXT_POINT_DIR"*.py; do
    [ -f "$SOURCE_FILE" ] || continue
    FILENAME=$(basename "$SOURCE_FILE")
    TARGET_FILE="$TARGET_DIR/$FILENAME"
    BACKUP_FILE="$BACKUP_DIR/$FILENAME"

    # Backup existing file only if backup doesn't already exist
    if [ -f "$TARGET_FILE" ] && [ ! -f "$BACKUP_FILE" ]; then
      cp "$TARGET_FILE" "$BACKUP_FILE"
      echo "BACKED UP: $EXT_POINT/$FILENAME → .hardening_originals/"
    fi

    cp "$SOURCE_FILE" "$TARGET_FILE"
    echo "INSTALLED: $EXT_POINT/$FILENAME"
    INSTALLED=$((INSTALLED + 1))
  done
done

echo ""
echo "Done. $INSTALLED extension(s) installed."
echo "Originals (if any) preserved in $BACKUP_ROOT"
echo "To restore: cp $BACKUP_ROOT/\$EXT_POINT/* $TARGET_ROOT/\$EXT_POINT/"
