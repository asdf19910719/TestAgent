# QA Agent 安装脚本（Windows PowerShell）
# 用法: .\install.ps1 D:\MyProject

param(
    [Parameter(Mandatory=$false)]
    [string]$TargetPath = ".",

    [switch]$SkipInit
)

# 设置控制台 UTF-8 输出
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

Write-Host "=== QA Agent Install ===" -ForegroundColor Cyan

# 检查目标路径
$Target = Resolve-Path -Path $TargetPath -ErrorAction SilentlyContinue
if (-not $Target) {
    Write-Host "[ERROR] Target path not found: $TargetPath" -ForegroundColor Red
    exit 1
}

$TargetDir = $Target.Path
Write-Host "[1/4] Target: $TargetDir" -ForegroundColor Green

# 检查是否在 TestAgent 根目录
$ScriptDir = Split-Path -Parent $PSCommandPath
$ClaudeDir = Join-Path $ScriptDir ".claude"

if (-not (Test-Path $ClaudeDir)) {
    Write-Host "[ERROR] .claude/ not found. Run from TestAgent root" -ForegroundColor Red
    exit 1
}

# 步骤 1: 复制 .claude/
$TargetClaudeDir = Join-Path $TargetDir ".claude"
Write-Host "[2/4] Copying .claude/ extension..." -ForegroundColor Yellow

if (Test-Path $TargetClaudeDir) {
    $Choice = Read-Host ".claude/ exists. Overwrite? (y/N)"
    if ($Choice -eq "y" -or $Choice -eq "Y") {
        Remove-Item -Recurse -Force $TargetClaudeDir
        Copy-Item -Recurse $ClaudeDir $TargetClaudeDir
        Write-Host "  [OK] Overwritten" -ForegroundColor Green
    }
    else {
        Write-Host "  Skipped"
    }
}
else {
    Copy-Item -Recurse $ClaudeDir $TargetClaudeDir
    Write-Host "  [OK] Copied .claude/" -ForegroundColor Green
}

# 步骤 2: 安装 Python 包
Write-Host "[3/4] Installing Python package..." -ForegroundColor Yellow

$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[ERROR] python not found. Install Python 3.9+" -ForegroundColor Red
    exit 1
}

$PythonVersion = & python --version 2>&1
Write-Host "  Python: $PythonVersion"

Push-Location $ScriptDir
& python -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location
Write-Host "  [OK] Installed qa-agent" -ForegroundColor Green

# 步骤 3: 初始化项目
if (-not $SkipInit) {
    Write-Host "[4/4] Initializing project..." -ForegroundColor Yellow
    Push-Location $TargetDir

    $ConfigFile = Join-Path $TargetDir ".qa-agent.yml"
    if (Test-Path $ConfigFile) {
        Write-Host "  Already initialized (.qa-agent.yml exists)" -ForegroundColor Yellow
    }
    else {
        & qa init
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[WARNING] qa init failed, run manually" -ForegroundColor Yellow
        }
        else {
            Write-Host "  [OK] Generated .qa-agent.yml" -ForegroundColor Green
        }
    }

    Pop-Location
}
else {
    Write-Host "[4/4] Skipped init (--SkipInit)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Edit $TargetDir\.qa-agent.yml"
Write-Host "  2. Open $TargetDir in Claude Code"
Write-Host "  3. Run: /qa init"
Write-Host "  4. Run: /qa feature <name> or /qa bugfix <id>"
Write-Host ""
