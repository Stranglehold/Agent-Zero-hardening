<#
.SYNOPSIS
    Interactive evaluation launcher for Agent-Zero model profiling.

.DESCRIPTION
    Discovers locally running inference providers (LM Studio, Ollama),
    queries available models, and runs the eval framework with correct
    configuration. Eliminates the need to remember API ports, model
    names, or CLI flags.

.EXAMPLE
    .\run_eval.ps1
    .\run_eval.ps1 -SkipDiscovery -Provider ollama -ModelName "gpt-oss:20b"
    .\run_eval.ps1 -Modules "tool_reliability" -Verbose
#>

param(
    [switch]$SkipDiscovery,
    [string]$Provider,
    [string]$ModelName,
    [string[]]$Modules,
    [switch]$ForceHarmonyFixtures,
    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Provider definitions ─────────────────────────────────────────────────────

$Providers = @{
    "lmstudio" = @{
        DisplayName = "LM Studio"
        ApiBase     = "http://localhost:1234/v1"
        ModelsUrl   = "http://localhost:1234/v1/models"
        Notes       = "Translates Harmony via chat template. Tool calls returned in content field."
    }
    "ollama" = @{
        DisplayName = "Ollama"
        ApiBase     = "http://localhost:11434/v1"
        ModelsUrl   = "http://localhost:11434/v1/models"
        Notes       = "Native Harmony parser (harmonyparser.go). Tool calls returned as structured tool_calls array."
    }
}

# ── Helper functions ─────────────────────────────────────────────────────────

function Test-Endpoint {
    param([string]$Url)
    try {
        $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Get-Models {
    param([string]$Url)
    try {
        $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 5 -ErrorAction Stop
        $models = @()
        if ($response.data) {
            foreach ($m in $response.data) {
                $models += $m.id
            }
        }
        return $models
    } catch {
        return @()
    }
}

function Detect-ModelFamily {
    param([string]$Name)
    $lower = $Name.ToLower()
    if ($lower -match "gpt-oss|gptoss")   { return "gpt-oss" }
    if ($lower -match "qwen")             { return "qwen" }
    if ($lower -match "llama|meta-llama") { return "llama" }
    if ($lower -match "deepseek")         { return "deepseek" }
    if ($lower -match "gemma")            { return "gemma" }
    if ($lower -match "phi")              { return "phi" }
    if ($lower -match "mistral|mixtral")  { return "mistral" }
    if ($lower -match "glm|chatglm")      { return "glm" }
    return "unknown"
}

function Show-Header {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║      Agent-Zero Model Evaluation Framework          ║" -ForegroundColor Cyan
    Write-Host "║      Interactive Launcher                           ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Menu {
    param(
        [string]$Prompt,
        [string[]]$Options
    )
    Write-Host $Prompt -ForegroundColor Yellow
    for ($i = 0; $i -lt $Options.Count; $i++) {
        Write-Host "  [$($i + 1)] $($Options[$i])" -ForegroundColor White
    }
    Write-Host ""

    do {
        $input = Read-Host "Select (1-$($Options.Count))"
        $idx = 0
        $valid = [int]::TryParse($input, [ref]$idx) -and $idx -ge 1 -and $idx -le $Options.Count
        if (-not $valid) {
            Write-Host "  Invalid selection. Try again." -ForegroundColor Red
        }
    } while (-not $valid)

    return $idx - 1
}

# ── Available modules ────────────────────────────────────────────────────────

$AllModules = @(
    "bst",
    "tool_reliability",
    "graph_compliance",
    "pace_calibration",
    "context_sensitivity",
    "memory_utilization"
)

# ══════════════════════════════════════════════════════════════════════════════
# Main flow
# ══════════════════════════════════════════════════════════════════════════════

Show-Header

# ── Step 1: Discover or select provider ──────────────────────────────────────

$selectedProvider = $null
$selectedApiBase = $null

if ($SkipDiscovery -and $Provider) {
    $key = $Provider.ToLower().Replace(" ", "")
    if ($Providers.ContainsKey($key)) {
        $selectedProvider = $key
        $selectedApiBase = $Providers[$key].ApiBase
        Write-Host "[SKIP] Using provider: $($Providers[$key].DisplayName)" -ForegroundColor DarkGray
    } else {
        Write-Host "[ERROR] Unknown provider: $Provider" -ForegroundColor Red
        Write-Host "        Available: $($Providers.Keys -join ', ')" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[DISCOVERY] Scanning for local inference providers..." -ForegroundColor Cyan

    $available = @()
    foreach ($key in $Providers.Keys) {
        $p = $Providers[$key]
        $ok = Test-Endpoint $p.ModelsUrl
        $status = if ($ok) { "ONLINE" } else { "offline" }
        $color = if ($ok) { "Green" } else { "DarkGray" }

        Write-Host "  $($p.DisplayName): " -NoNewline
        Write-Host $status -ForegroundColor $color

        if ($ok) {
            $available += $key
        }
    }

    Write-Host ""

    if ($available.Count -eq 0) {
        Write-Host "[ERROR] No inference providers detected." -ForegroundColor Red
        Write-Host "        Start LM Studio (port 1234) or Ollama (port 11434) and try again." -ForegroundColor Red
        exit 1
    }

    if ($available.Count -eq 1) {
        $selectedProvider = $available[0]
        $selectedApiBase = $Providers[$selectedProvider].ApiBase
        Write-Host "[AUTO] Using only available provider: $($Providers[$selectedProvider].DisplayName)" -ForegroundColor Green
    } else {
        $options = $available | ForEach-Object { "$($Providers[$_].DisplayName) — $($Providers[$_].Notes)" }
        $idx = Show-Menu "Which provider?" $options
        $selectedProvider = $available[$idx]
        $selectedApiBase = $Providers[$selectedProvider].ApiBase
    }
}

Write-Host ""
Write-Host "[PROVIDER] $($Providers[$selectedProvider].DisplayName) at $selectedApiBase" -ForegroundColor Green

# ── Step 2: Query and select model ───────────────────────────────────────────

$selectedModel = $null

if ($ModelName) {
    $selectedModel = $ModelName
    Write-Host "[MODEL] Using specified model: $selectedModel" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[MODELS] Querying available models..." -ForegroundColor Cyan

    $models = Get-Models $Providers[$selectedProvider].ModelsUrl

    if ($models.Count -eq 0) {
        Write-Host "[ERROR] No models found. Is a model loaded in $($Providers[$selectedProvider].DisplayName)?" -ForegroundColor Red
        exit 1
    }

    if ($models.Count -eq 1) {
        $selectedModel = $models[0]
        Write-Host "[AUTO] Only one model available: $selectedModel" -ForegroundColor Green
    } else {
        Write-Host ""
        $idx = Show-Menu "Which model to evaluate?" $models
        $selectedModel = $models[$idx]
    }
}

$modelFamily = Detect-ModelFamily $selectedModel
Write-Host "[FAMILY] Detected model family: $modelFamily" -ForegroundColor Cyan

# ── Step 3: Select modules ───────────────────────────────────────────────────

$selectedModules = $null

if ($Modules -and $Modules.Count -gt 0) {
    $selectedModules = $Modules
    Write-Host "[MODULES] Using specified: $($selectedModules -join ', ')" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Which evaluation modules to run?" -ForegroundColor Yellow
    Write-Host "  [1] All modules (full profile)" -ForegroundColor White
    Write-Host "  [2] Tool reliability only (quick test)" -ForegroundColor White
    Write-Host "  [3] BST + Tool reliability (core capabilities)" -ForegroundColor White
    Write-Host "  [4] Custom selection" -ForegroundColor White
    Write-Host ""

    do {
        $choice = Read-Host "Select (1-4)"
        $validChoice = $choice -match "^[1-4]$"
        if (-not $validChoice) { Write-Host "  Invalid selection." -ForegroundColor Red }
    } while (-not $validChoice)

    switch ($choice) {
        "1" { $selectedModules = $AllModules }
        "2" { $selectedModules = @("tool_reliability") }
        "3" { $selectedModules = @("bst", "tool_reliability") }
        "4" {
            Write-Host ""
            Write-Host "Available modules:" -ForegroundColor Yellow
            for ($i = 0; $i -lt $AllModules.Count; $i++) {
                Write-Host "  [$($i + 1)] $($AllModules[$i])" -ForegroundColor White
            }
            Write-Host ""
            $picks = Read-Host "Enter module numbers separated by commas (e.g., 1,2,4)"
            $selectedModules = @()
            foreach ($p in ($picks -split ",")) {
                $p = $p.Trim()
                $pidx = 0
                if ([int]::TryParse($p, [ref]$pidx) -and $pidx -ge 1 -and $pidx -le $AllModules.Count) {
                    $selectedModules += $AllModules[$pidx - 1]
                }
            }
            if ($selectedModules.Count -eq 0) {
                Write-Host "[ERROR] No valid modules selected." -ForegroundColor Red
                exit 1
            }
        }
    }
}

Write-Host "[MODULES] Running: $($selectedModules -join ', ')" -ForegroundColor Green

# ── Step 4: Configure fixture strategy ───────────────────────────────────────

$fixtureFlag = ""

if ($ForceHarmonyFixtures) {
    $fixtureFlag = "--force-harmony"
    Write-Host "[FIXTURES] Harmony-native fixtures forced by flag" -ForegroundColor Yellow
} elseif ($modelFamily -eq "gpt-oss") {
    Write-Host ""
    Write-Host "[NOTE] GPT-OSS model detected." -ForegroundColor Yellow

    if ($selectedProvider -eq "ollama") {
        Write-Host "  Ollama's native Harmony parser may improve tool call accuracy." -ForegroundColor DarkGray
        Write-Host "  Standard fixtures recommended (Ollama handles Harmony at token level)." -ForegroundColor DarkGray
    } else {
        Write-Host "  LM Studio translates Harmony via chat template." -ForegroundColor DarkGray
        Write-Host "  Standard fixtures recommended (adapter handles response extraction)." -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "Use standard fixtures (recommended) or Harmony-native?" -ForegroundColor Yellow
    Write-Host "  [1] Standard fixtures (recommended)" -ForegroundColor White
    Write-Host "  [2] Harmony-native fixtures (experimental)" -ForegroundColor White
    Write-Host ""

    do {
        $fc = Read-Host "Select (1-2)"
        $validFc = $fc -match "^[1-2]$"
        if (-not $validFc) { Write-Host "  Invalid selection." -ForegroundColor Red }
    } while (-not $validFc)

    if ($fc -eq "2") {
        $fixtureFlag = "--force-harmony"
        Write-Host "[FIXTURES] Using Harmony-native fixtures" -ForegroundColor Yellow
    } else {
        Write-Host "[FIXTURES] Using standard fixtures" -ForegroundColor Green
    }
}

# ── Step 5: Confirmation and launch ──────────────────────────────────────────

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  Provider:  $($Providers[$selectedProvider].DisplayName)" -ForegroundColor White
Write-Host "  API Base:  $selectedApiBase" -ForegroundColor White
Write-Host "  Model:     $selectedModel" -ForegroundColor White
Write-Host "  Family:    $modelFamily" -ForegroundColor White
Write-Host "  Modules:   $($selectedModules -join ', ')" -ForegroundColor White
if ($fixtureFlag) {
    Write-Host "  Fixtures:  Harmony-native" -ForegroundColor Yellow
} else {
    Write-Host "  Fixtures:  Standard" -ForegroundColor White
}
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

$confirm = Read-Host "Run evaluation? (Y/n)"
if ($confirm -match "^[nN]") {
    Write-Host "[CANCELLED]" -ForegroundColor Red
    exit 0
}

# ── Build command ────────────────────────────────────────────────────────────

$cmd = @(
    "python", "eval_runner.py",
    "--api-base", $selectedApiBase,
    "--model-name", $selectedModel,
    "--modules"
)
$cmd += $selectedModules

$cmd += @("--provider", $selectedProvider)

if ($fixtureFlag) {
    $cmd += $fixtureFlag
}

if ($VerboseOutput) {
    $cmd += "--verbose"
} else {
    # Default to verbose for interactive use
    $cmd += "--verbose"
}

Write-Host ""
Write-Host "[RUN] $($cmd -join ' ')" -ForegroundColor DarkGray
Write-Host ""

# ── Execute ──────────────────────────────────────────────────────────────────

Push-Location $ScriptDir
try {
    & python eval_runner.py `
        --api-base $selectedApiBase `
        --model-name $selectedModel `
        --modules $selectedModules `
        --provider $selectedProvider `
        $(if ($fixtureFlag) { $fixtureFlag } else { "" }) `
        --verbose

    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

# ── Post-run summary ────────────────────────────────────────────────────────

Write-Host ""
if ($exitCode -eq 0) {
    $profileName = $selectedModel.Replace("/", "_").Replace("\", "_").Replace(":", "_")
    $profilePath = Join-Path $ScriptDir "profiles\$profileName.json"

    if (Test-Path $profilePath) {
        Write-Host "[DONE] Profile saved to: $profilePath" -ForegroundColor Green
        Write-Host ""

        # Show quick summary
        try {
            $profile = Get-Content $profilePath -Raw | ConvertFrom-Json
            $metrics = $profile.raw_metrics

            Write-Host "Quick Summary:" -ForegroundColor Cyan
            if ($metrics.tool_reliability) {
                $tr = $metrics.tool_reliability
                Write-Host "  Tool JSON validity:     $($tr.tool_json_validity_rate * 100)%" -ForegroundColor White
                Write-Host "  Tool param accuracy:    $($tr.tool_parameter_accuracy * 100)%" -ForegroundColor White
                Write-Host "  Tool selection:         $($tr.tool_selection_accuracy * 100)%" -ForegroundColor White
                Write-Host "  Recovery rate:          $($tr.tool_recovery_rate * 100)%" -ForegroundColor White
                if ($tr._adapter_model_family) {
                    Write-Host "  Adapter family:         $($tr._adapter_model_family)" -ForegroundColor DarkGray
                }
                if ($tr._fixture_source) {
                    Write-Host "  Fixture source:         $($tr._fixture_source)" -ForegroundColor DarkGray
                }
            }
            Write-Host ""
        } catch {
            # Silently skip summary on parse errors
        }
    }
} else {
    Write-Host "[ERROR] Evaluation failed with exit code: $exitCode" -ForegroundColor Red
}
