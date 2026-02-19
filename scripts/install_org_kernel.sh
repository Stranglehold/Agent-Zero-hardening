#!/bin/bash
# Layer: Organization Kernel
# Installs org dispatcher extension, role profiles, and org templates
#
# Deploys:
#   Extension  → /a0/python/extensions/before_main_llm_call/_12_org_dispatcher.py
#   Org data   → /a0/usr/organizations/roles/*.json
#   Org data   → /a0/usr/organizations/*.json (templates)
#   Directories→ /a0/usr/organizations/reports/ + archive/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_EXT="$REPO_DIR/extensions"
SOURCE_ORG="$REPO_DIR/organizations"
TARGET_EXT="/a0/python/extensions"
TARGET_ORG="/a0/usr/organizations"

echo "[OrgKernel] Installing organization kernel..."

# ── Dispatcher extension ────────────────────────────────────────
BEFORE_DIR="$TARGET_EXT/before_main_llm_call"
mkdir -p "$BEFORE_DIR"
if [ -f "$SOURCE_EXT/before_main_llm_call/_12_org_dispatcher.py" ]; then
    cp "$SOURCE_EXT/before_main_llm_call/_12_org_dispatcher.py" "$BEFORE_DIR/"
    echo "[OrgKernel] Installed dispatcher extension (_12_)"
fi

# ── Organization data directories ───────────────────────────────
mkdir -p "$TARGET_ORG/roles"
mkdir -p "$TARGET_ORG/reports/archive"

# ── Role profiles ──────────────────────────────────────────────
if [ -d "$SOURCE_ORG/roles" ]; then
    role_count=0
    for role_file in "$SOURCE_ORG/roles"/*.json; do
        [ -f "$role_file" ] || continue
        cp "$role_file" "$TARGET_ORG/roles/"
        role_count=$((role_count + 1))
    done
    echo "[OrgKernel] Installed $role_count role profiles"
fi

# ── Organization templates ─────────────────────────────────────
template_count=0
for org_file in "$SOURCE_ORG"/*.json; do
    [ -f "$org_file" ] || continue
    cp "$org_file" "$TARGET_ORG/"
    template_count=$((template_count + 1))
done
echo "[OrgKernel] Installed $template_count organization templates"

# ── Note: active.json is NOT created automatically ──────────────
# To activate an organization, copy a template:
#   cp /a0/usr/organizations/software_dev.json /a0/usr/organizations/active.json
# When no active.json exists, the dispatcher is a no-op (full backward compatibility).

echo "[OrgKernel] Done. Organization kernel ready."
echo "[OrgKernel] To activate: cp $TARGET_ORG/<template>.json $TARGET_ORG/active.json"
