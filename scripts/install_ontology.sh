#!/usr/bin/env bash
# ━━━ Ontology Layer — Install ━━━
# Deploys ontology core files to Agent-Zero paths.
# Extensions (_58, _59) are handled by install_all.sh.
# This script covers:
#   - Ontology core (config, schema, engines) → /a0/usr/ontology/
#   - Connectors → /a0/usr/ontology/connectors/
#   - Investigation tools → /a0/python/tools/
#   - Intelligence analyst role → /a0/usr/organizations/roles/
#   - Runtime directories and empty JSONL files
#   - Python syntax validation
#   - __pycache__ clearing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SCRIPT_DIR}"

if [[ -d "${REPO_DIR}/ontology" ]]; then
    ONT_SRC="${REPO_DIR}/ontology"
elif [[ -f "${REPO_DIR}/resolution_engine.py" ]]; then
    ONT_SRC="${REPO_DIR}"
    REPO_DIR="$(dirname "${REPO_DIR}")"
else
    echo "ERROR: Cannot find ontology source files."
    echo "Run from repo root or ontology/ directory."
    exit 1
fi

ONT_DEST="/a0/usr/ontology"
TOOLS_SRC="${REPO_DIR}/tools"
TOOLS_DEST="/a0/python/tools"
ROLES_SRC="${REPO_DIR}/organizations/roles"
ROLES_DEST="/a0/usr/organizations/roles"
EXT_DIR="/a0/python/extensions"
ERRORS=0

echo ""
echo "━━━ Ontology Layer — Install ━━━"
echo "  Source : ${ONT_SRC}"
echo "  Target : ${ONT_DEST}"
echo ""

install_file() {
    local src="$1" dest="$2" label="${3:-$(basename "$1")}"
    if [[ -f "${dest}" ]]; then
        cp "${dest}" "${dest}.bak_$(date +%Y%m%d_%H%M%S)"
        echo "    BACKED UP: ${label}"
    fi
    cp "${src}" "${dest}"
    echo "    INSTALLED: ${label}"
}

echo "  → Creating directory structure"
mkdir -p "${ONT_DEST}/connectors"
mkdir -p "${ONT_DEST}/investigations"
mkdir -p "${ROLES_DEST}"
echo "    ✓ Directories created"

echo ""
echo "  → Validating Python syntax"
SYNTAX_OK=true
for pyfile in \
    "${ONT_SRC}/resolution_engine.py" \
    "${ONT_SRC}/relationship_extractor.py" \
    "${ONT_SRC}/ontology_store.py" \
    "${ONT_SRC}/connectors/csv_connector.py" \
    "${ONT_SRC}/connectors/json_connector.py" \
    "${ONT_SRC}/connectors/html_connector.py" \
    "${TOOLS_SRC}/investigation_tools.py"; do
    if [[ -f "$pyfile" ]]; then
        if python3 -m py_compile "$pyfile" 2>/dev/null; then
            echo "    ✓ $(basename "$pyfile")"
        else
            echo "    ✗ SYNTAX ERROR: $pyfile"
            python3 -m py_compile "$pyfile" 2>&1 | head -5
            SYNTAX_OK=false
            ERRORS=$((ERRORS + 1))
        fi
    fi
done
if [[ "$SYNTAX_OK" != "true" ]]; then
    echo "  ⚠ Syntax errors found. Fix before restarting agent."
fi

echo ""
echo "  → Deploying ontology core"
for f in ontology_config.json ontology_schema.json resolution_engine.py relationship_extractor.py ontology_store.py; do
    if [[ -f "${ONT_SRC}/${f}" ]]; then
        install_file "${ONT_SRC}/${f}" "${ONT_DEST}/${f}" "${f}"
    else
        echo "    MISSING: ${f}"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "  → Deploying connectors"
if [[ -d "${ONT_SRC}/connectors" ]]; then
    for f in "${ONT_SRC}"/connectors/*.py; do
        [[ -f "$f" ]] || continue
        install_file "$f" "${ONT_DEST}/connectors/$(basename "$f")" "connectors/$(basename "$f")"
    done
else
    echo "    MISSING: connectors directory"
    ERRORS=$((ERRORS + 1))
fi
touch "${ONT_DEST}/__init__.py"
touch "${ONT_DEST}/connectors/__init__.py"

echo ""
echo "  → Initializing runtime files"
for f in ingestion_queue.jsonl relationships.jsonl resolution_audit.jsonl review_queue.jsonl; do
    if [[ ! -f "${ONT_DEST}/${f}" ]]; then
        touch "${ONT_DEST}/${f}"
        echo "    CREATED: ${f}"
    else
        echo "    EXISTS: ${f} (preserved)"
    fi
done

echo ""
echo "  → Deploying investigation tools"
if [[ -f "${TOOLS_SRC}/investigation_tools.py" ]]; then
    install_file "${TOOLS_SRC}/investigation_tools.py" "${TOOLS_DEST}/investigation_tools.py" "investigation_tools.py"
else
    echo "    MISSING: investigation_tools.py"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "  → Deploying intelligence analyst role"
if [[ -f "${ROLES_SRC}/intelligence_analyst.json" ]]; then
    install_file "${ROLES_SRC}/intelligence_analyst.json" "${ROLES_DEST}/intelligence_analyst.json" "intelligence_analyst.json"
else
    echo "    MISSING: intelligence_analyst.json"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "  → Clearing __pycache__"
for d in message_loop_prompts_after monologue_end before_main_llm_call; do
    if [[ -d "${EXT_DIR}/${d}/__pycache__" ]]; then
        rm -rf "${EXT_DIR}/${d}/__pycache__"
        echo "    CLEARED: ${d}/__pycache__"
    fi
done

echo ""
echo "  → Verifying deployment"
FOUND=0
TOTAL=0
for f in \
    "${ONT_DEST}/ontology_config.json" \
    "${ONT_DEST}/ontology_schema.json" \
    "${ONT_DEST}/resolution_engine.py" \
    "${ONT_DEST}/relationship_extractor.py" \
    "${ONT_DEST}/ontology_store.py" \
    "${ONT_DEST}/connectors/csv_connector.py" \
    "${ONT_DEST}/connectors/json_connector.py" \
    "${ONT_DEST}/connectors/html_connector.py" \
    "${ONT_DEST}/ingestion_queue.jsonl" \
    "${ONT_DEST}/relationships.jsonl" \
    "${ONT_DEST}/resolution_audit.jsonl" \
    "${ONT_DEST}/review_queue.jsonl" \
    "${TOOLS_DEST}/investigation_tools.py" \
    "${ROLES_DEST}/intelligence_analyst.json" \
    "${EXT_DIR}/message_loop_prompts_after/_58_ontology_query.py" \
    "${EXT_DIR}/monologue_end/_59_ontology_maintenance.py"; do
    TOTAL=$((TOTAL + 1))
    if [[ -f "$f" ]]; then
        FOUND=$((FOUND + 1))
    else
        echo "    ✗ MISSING: ${f}"
    fi
done
echo "    Files: ${FOUND}/${TOTAL}"

echo ""
echo "━━━ Summary ━━━"
echo "  Core files  → ${ONT_DEST}/"
echo "  Connectors  → ${ONT_DEST}/connectors/"
echo "  Runtime     → ${ONT_DEST}/*.jsonl"
echo "  Tools       → ${TOOLS_DEST}/investigation_tools.py"
echo "  Roles       → ${ROLES_DEST}/intelligence_analyst.json"
echo "  Extensions  → installed by install_all.sh (_58, _59)"
echo ""
if [[ $ERRORS -gt 0 ]]; then
    echo "  ⚠ Completed with ${ERRORS} warning(s)."
else
    echo "  ✓ Ontology layer deployed successfully."
fi
echo ""
echo "  Restart agent-zero to load changes."
echo "  Test: check docker logs for [ONT-QUERY] and [ONT-MAINT]"
echo ""
