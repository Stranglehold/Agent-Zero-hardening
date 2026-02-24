#!/usr/bin/env bash
# =============================================================================
# install_tool_format_adapter.sh
# Layer: Eval Framework (tool format compatibility)
#
# Deploys the tool format adapter and updated eval modules.
# Backward compatible â€" existing Qwen/Llama evals produce identical results.
# New behavior: GPT-OSS and other non-standard models get accurate tool scoring.
#
# Files:
#   tool_format_adapter.py  â†' eval_framework/          (new)
#   eval_runner.py          â†' eval_framework/          (updated: +chat_raw)
#   base_eval.py            â†' eval_framework/modules/  (updated: +call_model_raw)
#   tool_eval.py            â†' eval_framework/modules/  (updated: +adapter integration)
# =============================================================================

set -euo pipefail

EVAL_DIR="${1:-D:/Vibecode/Agent-Zero/Agent-Zero-Hardening/Agent-Zero-hardening/eval_framework}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[INSTALL] Tool Format Adapter â€" Eval Framework Compatibility Layer"
echo "[INSTALL] Target: ${EVAL_DIR}"

# Validate target
if [ ! -d "${EVAL_DIR}" ]; then
    echo "[ERROR] Eval framework directory not found: ${EVAL_DIR}"
    exit 1
fi

if [ ! -d "${EVAL_DIR}/modules" ]; then
    echo "[ERROR] Modules directory not found: ${EVAL_DIR}/modules"
    exit 1
fi

# Backup originals
BACKUP_DIR="${EVAL_DIR}/.backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${BACKUP_DIR}/modules"

echo "[INSTALL] Backing up originals to ${BACKUP_DIR}"

[ -f "${EVAL_DIR}/eval_runner.py" ] && cp "${EVAL_DIR}/eval_runner.py" "${BACKUP_DIR}/"
[ -f "${EVAL_DIR}/modules/base_eval.py" ] && cp "${EVAL_DIR}/modules/base_eval.py" "${BACKUP_DIR}/modules/"
[ -f "${EVAL_DIR}/modules/tool_eval.py" ] && cp "${EVAL_DIR}/modules/tool_eval.py" "${BACKUP_DIR}/modules/"

# Deploy new files
echo "[INSTALL] Deploying tool_format_adapter.py"
cp "${SCRIPT_DIR}/tool_format_adapter.py" "${EVAL_DIR}/tool_format_adapter.py"

echo "[INSTALL] Deploying updated eval_runner.py"
cp "${SCRIPT_DIR}/eval_runner.py" "${EVAL_DIR}/eval_runner.py"

echo "[INSTALL] Deploying updated base_eval.py"
cp "${SCRIPT_DIR}/base_eval.py" "${EVAL_DIR}/modules/base_eval.py"

echo "[INSTALL] Deploying updated tool_eval.py"
cp "${SCRIPT_DIR}/tool_eval.py" "${EVAL_DIR}/modules/tool_eval.py"

# Clear pycache
echo "[INSTALL] Clearing __pycache__"
find "${EVAL_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "[INSTALL] Done. Changes:"
echo "  + tool_format_adapter.py     (new â€" model family detection & response normalization)"
echo "  ~ eval_runner.py             (added chat_raw() to LMStudioClient)"
echo "  ~ modules/base_eval.py       (added call_model_raw() method)"
echo "  ~ modules/tool_eval.py       (uses adapter when available, falls back to legacy)"
echo ""
echo "[INSTALL] To verify: python eval_runner.py --modules tool_reliability --model-name gpt-oss-20b --verbose"
echo "[INSTALL] Expected: [ADAPTER] Model family detected: gpt-oss"
