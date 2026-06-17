# QA Agent Installation Script for Windows PowerShell
# Usage: .\install.ps1 D:\MyProject [-Global]

param(
    [Parameter(Mandatory=$false)]
    [string]$TargetPath = ".",
    [switch]$SkipInit,
    [switch]$NoGlobal
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== QA Agent Install ===" -ForegroundColor Cyan

# Check target path
$Target = Resolve-Path -Path $TargetPath -ErrorAction SilentlyContinue
if (-not $Target) {
    Write-Host "[ERROR] Target path not found: $TargetPath" -ForegroundColor Red
    exit 1
}

$TargetDir = $Target.Path
Write-Host "[1/5] Target: $TargetDir" -ForegroundColor Green

# Check TestAgent root
$ScriptDir = Split-Path -Parent $PSCommandPath
$ClaudeDir = Join-Path $ScriptDir ".claude"
if (-not (Test-Path $ClaudeDir)) {
    Write-Host "[ERROR] .claude/ not found" -ForegroundColor Red
    exit 1
}

# Step 1: Copy .claude/ to project (for Claude Code official)
$TargetClaudeDir = Join-Path $TargetDir ".claude"
Write-Host "[2/5] Copying .claude/ to project..." -ForegroundColor Yellow

if (Test-Path $TargetClaudeDir) {
    $Choice = Read-Host ".claude/ exists in project. Overwrite? (y/N)"
    if ($Choice -eq "y" -or $Choice -eq "Y") {
        Remove-Item -Recurse -Force $TargetClaudeDir
        Copy-Item -Recurse $ClaudeDir $TargetClaudeDir
        Write-Host "  [OK] Overwritten" -ForegroundColor Green
    } else {
        Write-Host "  Skipped"
    }
} else {
    Copy-Item -Recurse $ClaudeDir $TargetClaudeDir
    Write-Host "  [OK] Copied" -ForegroundColor Green
}

# Step 2: Copy to global ~/.claude/ (for CCM and other Claude variants)
if (-not $NoGlobal) {
    Write-Host "[3/5] Installing globally (for CCM compatibility)..." -ForegroundColor Yellow
    $UserClaudeDir = Join-Path $env:USERPROFILE ".claude"
    $GlobalCommandsDir = Join-Path $UserClaudeDir "commands"
    $GlobalAgentsDir = Join-Path $UserClaudeDir "agents"

    if (-not (Test-Path $GlobalCommandsDir)) {
        New-Item -ItemType Directory -Path $GlobalCommandsDir -Force | Out-Null
    }
    if (-not (Test-Path $GlobalAgentsDir)) {
        New-Item -ItemType Directory -Path $GlobalAgentsDir -Force | Out-Null
    }

    Copy-Item -Force (Join-Path $ClaudeDir "commands\qa.md") (Join-Path $GlobalCommandsDir "qa.md")
    Copy-Item -Force (Join-Path $ClaudeDir "agents\qa-test-engineer.md") (Join-Path $GlobalAgentsDir "qa-test-engineer.md")
    Copy-Item -Force (Join-Path $ClaudeDir "agents\qa-gatekeeper.md") (Join-Path $GlobalAgentsDir "qa-gatekeeper.md")
    
    Write-Host "  [OK] Installed to $UserClaudeDir" -ForegroundColor Green
} else {
    Write-Host "[3/5] Skipped global install (-NoGlobal)" -ForegroundColor Yellow
}

# Step 3: Install Python package
Write-Host "[4/5] Installing Python package..." -ForegroundColor Yellow

$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[ERROR] python not found" -ForegroundColor Red
    exit 1
}

$PythonVersion = & python --version 2>&1
Write-Host "  Python: $PythonVersion"

Push-Location $ScriptDir
try {
    & python -m pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed"
    }
} catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location
Write-Host "  [OK] Installed qa-agent" -ForegroundColor Green

# Step 4: Initialize project
if (-not $SkipInit) {
    Write-Host "[5/5] Initializing project..." -ForegroundColor Yellow
    Push-Location $TargetDir
    
    try {
        $ConfigFile = Join-Path $TargetDir ".qa-agent.yml"
        if (Test-Path $ConfigFile) {
            Write-Host "  Already initialized" -ForegroundColor Yellow
        } else {
            & qa init
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[WARNING] qa init failed" -ForegroundColor Yellow
            } else {
                Write-Host "  [OK] Initialized" -ForegroundColor Green
            }
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[5/5] Skipped init" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Restart Claude Code / CCM session"
Write-Host "  2. Open $TargetDir in Claude Code"
Write-Host "  3. Run: /qa status"
Write-Host ""
