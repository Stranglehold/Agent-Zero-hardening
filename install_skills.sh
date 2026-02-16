#!/bin/bash
# install_skills.sh
# Deploys curated skill overrides from the hardening repo to /a0/skills/
# Backs up originals before overwriting. Safe to re-run.
#
# Layout expected in this repo:
#   skills/
#     create-skill/
#       SKILL.md
#     some-other-skill/
#       SKILL.md
#       helper_script.py
#
# Deployment target: /a0/skills/{skill-name}/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="$SCRIPT_DIR/skills"
SKILLS_DST="/a0/skills"
BACKUP_DIR="$SKILLS_DST/.hardening_originals"

if [ ! -d "$SKILLS_SRC" ]; then
  echo "No skills/ directory found in hardening repo. Nothing to install."
  exit 0
fi

echo "Installing hardening skills..."

installed=0

for skill_src_dir in "$SKILLS_SRC"/*/; do
  skill_name="$(basename "$skill_src_dir")"
  skill_dst_dir="$SKILLS_DST/$skill_name"
  backup_skill_dir="$BACKUP_DIR/$skill_name"

  if [ ! -f "$skill_src_dir/SKILL.md" ]; then
    echo "  SKIP: $skill_name (no SKILL.md found)"
    continue
  fi

  # Back up existing skill directory if present and not already backed up
  if [ -d "$skill_dst_dir" ] && [ ! -d "$backup_skill_dir" ]; then
    mkdir -p "$backup_skill_dir"
    cp -r "$skill_dst_dir/." "$backup_skill_dir/"
    echo "  Backed up: $skill_name → $backup_skill_dir"
  fi

  # Create destination directory and copy all files
  mkdir -p "$skill_dst_dir"
  cp -r "$skill_src_dir/." "$skill_dst_dir/"
  echo "  Installed: $skill_name"
  installed=$((installed + 1))
done

echo ""
echo "Skills installed: $installed"
echo "Backup location: $BACKUP_DIR"
