#!/usr/bin/env bash
# ==============================================================================
# run_eval.sh — Interactive evaluation launcher for Agent-Zero model profiling
#
# Discovers locally running inference providers (LM Studio, Ollama),
# queries available models, and runs the eval framework with correct config.
#
# Usage:
#   ./run_eval.sh                          # fully interactive
#   ./run_eval.sh --provider ollama        # skip provider selection
#   ./run_eval.sh --modules tool_reliability --verbose
# ==============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colors ───────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m'

# ── Provider defaults ────────────────────────────────────────────────────────
LMSTUDIO_BASE="http://localhost:1234/v1"
OLLAMA_BASE="http://localhost:11434/v1"

# ── Parse CLI args ───────────────────────────────────────────────────────────
PROVIDER=""
MODEL_NAME=""
MODULES=""
FORCE_HARMONY=""
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --provider)     PROVIDER="$2"; shift 2 ;;
        --model-name)   MODEL_NAME="$2"; shift 2 ;;
        --modules)      shift; MODULES=""; while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do MODULES="$MODULES $1"; shift; done ;;
        --force-harmony) FORCE_HARMONY="--force-harmony"; shift ;;
        --verbose|-v)   VERBOSE="--verbose"; shift ;;
        *)              echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────
test_endpoint() {
    curl -s --max-time 3 "$1" > /dev/null 2>&1
}

get_models() {
    curl -s --max-time 5 "$1" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for m in data.get('data', []):
        print(m.get('id', ''))
except: pass
" 2>/dev/null
}

detect_family() {
    local name="${1,,}"  # lowercase
    if [[ "$name" == *"gpt-oss"* || "$name" == *"gptoss"* ]]; then echo "gpt-oss"
    elif [[ "$name" == *"qwen"* ]]; then echo "qwen"
    elif [[ "$name" == *"llama"* ]]; then echo "llama"
    elif [[ "$name" == *"deepseek"* ]]; then echo "deepseek"
    elif [[ "$name" == *"mistral"* || "$name" == *"mixtral"* ]]; then echo "mistral"
    else echo "unknown"
    fi
}

# ── Header ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║      Agent-Zero Model Evaluation Framework          ║${NC}"
echo -e "${CYAN}║      Interactive Launcher                           ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Discover provider ────────────────────────────────────────────────
SELECTED_PROVIDER=""
SELECTED_BASE=""

if [[ -n "$PROVIDER" ]]; then
    SELECTED_PROVIDER="$PROVIDER"
    case "$PROVIDER" in
        lmstudio) SELECTED_BASE="$LMSTUDIO_BASE" ;;
        ollama)   SELECTED_BASE="$OLLAMA_BASE" ;;
        *)        echo -e "${RED}Unknown provider: $PROVIDER${NC}"; exit 1 ;;
    esac
    echo -e "${GRAY}[SKIP] Using provider: $SELECTED_PROVIDER${NC}"
else
    echo -e "${CYAN}[DISCOVERY] Scanning for local inference providers...${NC}"

    AVAILABLE=()

    if test_endpoint "${LMSTUDIO_BASE}/models"; then
        echo -e "  LM Studio: ${GREEN}ONLINE${NC}"
        AVAILABLE+=("lmstudio")
    else
        echo -e "  LM Studio: ${GRAY}offline${NC}"
    fi

    if test_endpoint "${OLLAMA_BASE}/models"; then
        echo -e "  Ollama:    ${GREEN}ONLINE${NC}"
        AVAILABLE+=("ollama")
    else
        echo -e "  Ollama:    ${GRAY}offline${NC}"
    fi

    echo ""

    if [[ ${#AVAILABLE[@]} -eq 0 ]]; then
        echo -e "${RED}[ERROR] No inference providers detected.${NC}"
        echo -e "${RED}        Start LM Studio (port 1234) or Ollama (port 11434).${NC}"
        exit 1
    fi

    if [[ ${#AVAILABLE[@]} -eq 1 ]]; then
        SELECTED_PROVIDER="${AVAILABLE[0]}"
        echo -e "${GREEN}[AUTO] Using only available provider: $SELECTED_PROVIDER${NC}"
    else
        echo -e "${YELLOW}Which provider?${NC}"
        for i in "${!AVAILABLE[@]}"; do
            echo "  [$((i+1))] ${AVAILABLE[$i]}"
        done
        echo ""
        read -p "Select (1-${#AVAILABLE[@]}): " choice
        idx=$((choice - 1))
        SELECTED_PROVIDER="${AVAILABLE[$idx]}"
    fi

    case "$SELECTED_PROVIDER" in
        lmstudio) SELECTED_BASE="$LMSTUDIO_BASE" ;;
        ollama)   SELECTED_BASE="$OLLAMA_BASE" ;;
    esac
fi

echo -e "${GREEN}[PROVIDER] $SELECTED_PROVIDER at $SELECTED_BASE${NC}"

# ── Step 2: Select model ────────────────────────────────────────────────────
SELECTED_MODEL=""

if [[ -n "$MODEL_NAME" ]]; then
    SELECTED_MODEL="$MODEL_NAME"
    echo -e "${GREEN}[MODEL] Using specified: $SELECTED_MODEL${NC}"
else
    echo ""
    echo -e "${CYAN}[MODELS] Querying available models...${NC}"

    mapfile -t MODELS < <(get_models "${SELECTED_BASE}/models")

    if [[ ${#MODELS[@]} -eq 0 ]]; then
        echo -e "${RED}[ERROR] No models found. Is a model loaded?${NC}"
        exit 1
    fi

    if [[ ${#MODELS[@]} -eq 1 ]]; then
        SELECTED_MODEL="${MODELS[0]}"
        echo -e "${GREEN}[AUTO] Only one model: $SELECTED_MODEL${NC}"
    else
        echo ""
        echo -e "${YELLOW}Which model to evaluate?${NC}"
        for i in "${!MODELS[@]}"; do
            echo "  [$((i+1))] ${MODELS[$i]}"
        done
        echo ""
        read -p "Select (1-${#MODELS[@]}): " choice
        idx=$((choice - 1))
        SELECTED_MODEL="${MODELS[$idx]}"
    fi
fi

FAMILY=$(detect_family "$SELECTED_MODEL")
echo -e "${CYAN}[FAMILY] Detected: $FAMILY${NC}"

# ── Step 3: Select modules ──────────────────────────────────────────────────
ALL_MODULES="bst tool_reliability graph_compliance pace_calibration context_sensitivity memory_utilization"

if [[ -z "$MODULES" ]]; then
    echo ""
    echo -e "${YELLOW}Which evaluation modules?${NC}"
    echo "  [1] All modules (full profile)"
    echo "  [2] Tool reliability only (quick test)"
    echo "  [3] BST + Tool reliability (core)"
    echo "  [4] All modules"
    echo ""
    read -p "Select (1-4): " mchoice
    case "$mchoice" in
        1) MODULES="$ALL_MODULES" ;;
        2) MODULES="tool_reliability" ;;
        3) MODULES="bst tool_reliability" ;;
        4) MODULES="$ALL_MODULES" ;;
        *) MODULES="$ALL_MODULES" ;;
    esac
fi

MODULES=$(echo "$MODULES" | xargs)  # trim
echo -e "${GREEN}[MODULES] Running: $MODULES${NC}"

# ── Step 4: Harmony fixture check ───────────────────────────────────────────
if [[ "$FAMILY" == "gpt-oss" && -z "$FORCE_HARMONY" ]]; then
    echo ""
    echo -e "${YELLOW}[NOTE] GPT-OSS model detected. Use standard or Harmony fixtures?${NC}"
    echo "  [1] Standard (recommended)"
    echo "  [2] Harmony-native (experimental)"
    echo ""
    read -p "Select (1-2): " fchoice
    if [[ "$fchoice" == "2" ]]; then
        FORCE_HARMONY="--force-harmony"
        echo -e "${YELLOW}[FIXTURES] Harmony-native${NC}"
    else
        echo -e "${GREEN}[FIXTURES] Standard${NC}"
    fi
fi

# ── Step 5: Confirm and run ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Provider:  ${WHITE}$SELECTED_PROVIDER${NC}"
echo -e "  API Base:  ${WHITE}$SELECTED_BASE${NC}"
echo -e "  Model:     ${WHITE}$SELECTED_MODEL${NC}"
echo -e "  Family:    ${WHITE}$FAMILY${NC}"
echo -e "  Modules:   ${WHITE}$MODULES${NC}"
[[ -n "$FORCE_HARMONY" ]] && echo -e "  Fixtures:  ${YELLOW}Harmony-native${NC}" || echo -e "  Fixtures:  ${WHITE}Standard${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

read -p "Run evaluation? (Y/n): " confirm
if [[ "$confirm" =~ ^[nN] ]]; then
    echo -e "${RED}[CANCELLED]${NC}"
    exit 0
fi

# ── Execute ──────────────────────────────────────────────────────────────────
cd "$SCRIPT_DIR"

CMD="python eval_runner.py \
    --api-base $SELECTED_BASE \
    --model-name \"$SELECTED_MODEL\" \
    --provider $SELECTED_PROVIDER \
    --modules $MODULES \
    $FORCE_HARMONY \
    --verbose"

echo ""
echo -e "${GRAY}[RUN] $CMD${NC}"
echo ""

eval $CMD
