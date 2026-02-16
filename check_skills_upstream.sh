#!/bin/bash
# check_skills_upstream.sh
# Diffs currently installed skills against backed-up originals.
# Run after docker pull to detect if upstream changed a skill you've overridden.

SKILLS_DST="/a0/skills"
BACKUP_DIR="$SKILLS_DST/.hardening_originals"

if [ ! -d "$BACKUP_DIR" ]; then
  echo "No backup directory found. Run install_skills.sh first."
  exit 0
fi

echo "Checking for upstream skill changes..."
echo ""

changed=0

for backup_skill_dir in "$BACKUP_DIR"/*/; do
  skill_name="$(basename "$backup_skill_dir")"
  installed_dir="$SKILLS_DST/$skill_name"

  if [ ! -d "$installed_dir" ]; then
    echo "  MISSING: $skill_name — skill directory no longer exists at $installed_dir"
    changed=$((changed + 1))
    continue
  fi

  # Diff each file in the backup against what's currently deployed
  while IFS= read -r -d '' backup_file; do
    rel_path="${backup_file#$backup_skill_dir}"
    installed_file="$installed_dir/$rel_path"

    if [ ! -f "$installed_file" ]; then
      echo "  NEW FILE in upstream: $skill_name/$rel_path"
      changed=$((changed + 1))
      continue
    fi

    if ! diff -q "$backup_file" "$installed_file" > /dev/null 2>&1; then
      echo "  CHANGED: $skill_name/$rel_path"
      diff "$backup_file" "$installed_file" | head -20
      echo "  ---"
      changed=$((changed + 1))
    fi
  done < <(find "$backup_skill_dir" -type f -print0)
done

echo ""
if [ "$changed" -eq 0 ]; then
  echo "All skills unchanged. Safe to reinstall."
else
  echo "$changed change(s) detected. Review diffs above before running install_skills.sh."
  echo "If upstream changes are improvements, merge them into your hardening/skills/ copies first."
fi
