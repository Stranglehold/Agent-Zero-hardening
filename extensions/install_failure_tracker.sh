#!/bin/bash
# install_failure_tracker.sh
# Installs failure tracker extensions into agent-zero extension points
# Safe to re-run — backs up existing files before overwriting

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTENSIONS_DIR="/a0/python/extensions"
BACKUP_DIR="$EXTENSIONS_DIR/.hardening_originals"

EXTENSIONS=(
  "error_format/_30_failure_tracker.py"
  "tool_execute_after/_20_reset_failure_counter.py"
)

echo "Installing failure tracker extensions..."

mkdir -p "$BACKUP_DIR/error_format"
mkdir -p "$BACKUP_DIR/tool_execute_after"

for ext in "${EXTENSIONS[@]}"; do
  src="$SCRIPT_DIR/extensions/$ext"
  dst="$EXTENSIONS_DIR/$ext"
  dst_dir="$(dirname "$dst")"

  if [ ! -f "$src" ]; then
    echo "  ERROR: Source not found: $src"
    exit 1
  fi

  mkdir -p "$dst_dir"

  # Backup existing file if present and not already backed up
  backup="$BACKUP_DIR/$ext"
  if [ -f "$dst" ] && [ ! -f "$backup" ]; then
    cp "$dst" "$backup"
    echo "  Backed up: $ext"
  fi

  cp "$src" "$dst"
  echo "  Installed: $ext"
done

echo ""
echo "Failure tracker installed (${#EXTENSIONS[@]} extensions)."
echo "Backup location: $BACKUP_DIR"
