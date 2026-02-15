#!/bin/bash
# check_fw_upstream.sh
# After a docker image update, shows if upstream changed any of our target files
# Run this before re-running install_fw_replacements.sh

TARGET_DIR="/a0/prompts"
BACKUP_DIR="$TARGET_DIR/.fw_originals"

FILES=(
  "fw.msg_misformat.md"
  "fw.msg_repeat.md"
  "fw.msg_nudge.md"
  "fw.error.md"
  "fw.tool_not_found.md"
  "fw.warning.md"
)

if [ ! -d "$BACKUP_DIR" ]; then
  echo "No backups found at $BACKUP_DIR — install_fw_replacements.sh has not been run yet."
  exit 0
fi

echo "Checking for upstream changes to target files..."
echo ""

CHANGED=0
for FILE in "${FILES[@]}"; do
  CURRENT="$TARGET_DIR/$FILE"
  BACKUP="$BACKUP_DIR/$FILE"

  if [ ! -f "$BACKUP" ]; then
    echo "NO BACKUP: $FILE — skipping"
    continue
  fi

  if ! diff -q "$CURRENT" "$BACKUP" > /dev/null 2>&1; then
    echo "CHANGED UPSTREAM: $FILE"
    echo "--- original (backed up)"
    echo "+++ current (may be your replacement or upstream update)"
    diff "$BACKUP" "$CURRENT"
    echo ""
    CHANGED=1
  else
    echo "UNCHANGED: $FILE"
  fi
done

echo ""
if [ "$CHANGED" -eq 1 ]; then
  echo "WARNING: Some files changed. Review diffs above before re-running install."
  echo "If upstream changed the base logic, update fw-replacements/ accordingly."
else
  echo "All target files match originals. Safe to re-run install_fw_replacements.sh"
fi
