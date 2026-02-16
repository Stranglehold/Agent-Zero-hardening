#!/bin/bash
# check_prompt_patches_upstream.sh
# After a docker image update, checks if upstream changed any of our patched files
# Run before re-running install_prompt_patches.sh

TARGET_DIR="/a0/prompts"
BACKUP_DIR="$TARGET_DIR/.prompt_patch_originals"

FILES=(
  "agent.system.main.solving.md"
  "agent.system.main.tips.md"
  "agent.system.tool.response.md"
  "agent.system.tool.skills.md"
)

if [ ! -d "$BACKUP_DIR" ]; then
  echo "No backups found at $BACKUP_DIR — install_prompt_patches.sh has not been run yet."
  exit 0
fi

echo "Checking for upstream changes to patched prompt files..."
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
    diff "$BACKUP" "$CURRENT"
    echo ""
    CHANGED=1
  else
    echo "UNCHANGED: $FILE"
  fi
done

echo ""
if [ "$CHANGED" -eq 1 ]; then
  echo "WARNING: Changes detected. Review diffs above before re-running install."
else
  echo "All patched files match originals. Safe to re-run install_prompt_patches.sh"
fi
