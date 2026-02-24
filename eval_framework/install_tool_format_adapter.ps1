# =============================================================================
# install_tool_format_adapter.ps1
# Layer: Eval Framework (tool format compatibility)
#
# Deploys the tool format adapter and updated eval modules.
# Backward compatible - existing Qwen/Llama evals produce identical results.
# New behavior: GPT-OSS and other non-standard models get accurate tool scoring.
# =============================================================================

param(
    [string]$EvalDir = "D:\Vibecode\Agent-Zero\Agent-Zero-Hardening\Agent-Zero-hardening\eval_framework"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[INSTALL] Tool Format Adapter - Eval Framework Compatibility Layer" -ForegroundColor Cyan
Write-Host "[INSTALL] Target: $EvalDir"

# Validate target
if (-not (Test-Path $EvalDir)) {
    Write-Host "[ERROR] Eval framework directory not found: $EvalDir" -ForegroundColor Red
    exit 1
}

$ModulesDir = Join-Path $EvalDir "modules"
if (-not (Test-Path $ModulesDir)) {
    Write-Host "[ERROR] Modules directory not found: $ModulesDir" -ForegroundColor Red
    exit 1
}

# Backup originals
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $EvalDir ".backups\$Timestamp"
$BackupModDir = Join-Path $BackupDir "modules"
New-Item -ItemType Directory -Path $BackupModDir -Force | Out-Null

Write-Host "[INSTALL] Backing up originals to $BackupDir"

$filesToBackup = @(
    @{ Src = (Join-Path $EvalDir "eval_runner.py"); Dst = $BackupDir }
    @{ Src = (Join-Path $ModulesDir "base_eval.py"); Dst = $BackupModDir }
    @{ Src = (Join-Path $ModulesDir "tool_eval.py"); Dst = $BackupModDir }
)

foreach ($f in $filesToBackup) {
    if (Test-Path $f.Src) {
        Copy-Item $f.Src -Destination $f.Dst
        Write-Host "  Backed up: $(Split-Path -Leaf $f.Src)" -ForegroundColor DarkGray
    }
}

# Deploy new files
Write-Host "[INSTALL] Deploying tool_format_adapter.py" -ForegroundColor Green
Copy-Item (Join-Path $ScriptDir "tool_format_adapter.py") -Destination (Join-Path $EvalDir "tool_format_adapter.py")

Write-Host "[INSTALL] Deploying updated eval_runner.py" -ForegroundColor Green
Copy-Item (Join-Path $ScriptDir "eval_runner.py") -Destination (Join-Path $EvalDir "eval_runner.py")

Write-Host "[INSTALL] Deploying updated base_eval.py" -ForegroundColor Green
Copy-Item (Join-Path $ScriptDir "base_eval.py") -Destination (Join-Path $ModulesDir "base_eval.py")

Write-Host "[INSTALL] Deploying updated tool_eval.py" -ForegroundColor Green
Copy-Item (Join-Path $ScriptDir "tool_eval.py") -Destination (Join-Path $ModulesDir "tool_eval.py")

# Clear pycache
Write-Host "[INSTALL] Clearing __pycache__"
Get-ChildItem -Path $EvalDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[INSTALL] Done. Changes:" -ForegroundColor Cyan
Write-Host "  + tool_format_adapter.py     (new - model family detection & response normalization)"
Write-Host "  ~ eval_runner.py             (added chat_raw() to LMStudioClient)"
Write-Host "  ~ modules/base_eval.py       (added call_model_raw() method)"
Write-Host "  ~ modules/tool_eval.py       (uses adapter when available, falls back to legacy)"
Write-Host ""
Write-Host "[INSTALL] To verify:" -ForegroundColor Yellow
Write-Host "  python eval_runner.py --modules tool_reliability --model-name gpt-oss-20b --verbose"
Write-Host "  Expected: [ADAPTER] Model family detected: gpt-oss"
