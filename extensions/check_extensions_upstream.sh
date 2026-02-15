#!/bin/bash
# check_extensions_upstream.sh
# After a docker image update, checks if upstream changed files
# in our target extension directories
# Run before re-running install_extensions.sh

TARGET_ROOT="/a0/python/extensions"
BACKUP_ROOT="$TARGET_ROOT/.hardening_originals"

# Extension points we've modified
EXT_POINTS=(
  "error_format"
  "before_main_llm_call"
)

if [ ! -d "$BACKUP_ROOT" ]; then
  echo "No backups found at $BACKUP_ROOT — install_extensions.sh has not been run yet."
  exit 0
fi

echo "Checking for upstream changes in target extension directories..."
echo ""

CHANGED=0

for EXT_POINT in "${EXT_POINTS[@]}"; do
  TARGET_DIR="$TARGET_ROOT/$EXT_POINT"
  BACKUP_DIR="$BACKUP_ROOT/$EXT_POINT"

  echo "--- $EXT_POINT ---"

  if [ ! -d "$BACKUP_DIR" ]; then
    echo "  No backups for this extension point."
    continue
  fi

  # Check our installed files against their backups
  for BACKUP_FILE in "$BACKUP_DIR"/*.py; do
    [ -f "$BACKUP_FILE" ] || continue
    FILENAME=$(basename "$BACKUP_FILE")
    CURRENT="$TARGET_DIR/$FILENAME"

    if [ ! -f "$CURRENT" ]; then
      echo "  MISSING: $FILENAME (was installed, now gone — upstream may have removed it)"
      CHANGED=1
      continue
    fi

    if ! diff -q "$CURRENT" "$BACKUP_FILE" > /dev/null 2>&1; then
      echo "  CHANGED: $FILENAME"
      diff "$BACKUP_FILE" "$CURRENT"
      CHANGED=1
    else
      echo "  UNCHANGED: $FILENAME"
    fi
  done

  # Also flag any new files upstream added to these directories
  for CURRENT_FILE in "$TARGET_DIR"/_*.py; do
    [ -f "$CURRENT_FILE" ] || continue
    FILENAME=$(basename "$CURRENT_FILE")
    if [ ! -f "$BACKUP_DIR/$FILENAME" ]; then
      echo "  NEW UPSTREAM FILE: $FILENAME (review before reinstalling)"
    fi
  done

  echo ""
done

if [ "$CHANGED" -eq 1 ]; then
  echo "WARNING: Changes detected. Review diffs above before re-running install."
else
  echo "All target files match originals. Safe to re-run install_extensions.sh"
fi
