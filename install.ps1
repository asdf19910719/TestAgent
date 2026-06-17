# QA Agent 一键安装脚本（Windows PowerShell）
# 用法: .\install.ps1 D:\MyProject

param(
    [Parameter(Mandatory=$false)]
    [string]$TargetPath = ".",

    [switch]$SkipInit
)

$ErrorActionPreference = "Stop"

Write-Host "=== QA Agent 安装脚本 ===" -ForegroundColor Cyan

# 检查目标路径
$Target = Resolve-Path -Path $TargetPath -ErrorAction SilentlyContinue
if (-not $Target) {
    Write-Host "[错误] 目标路径不存在: $TargetPath" -ForegroundColor Red
    exit 1
}

$TargetDir = $Target.Path
Write-Host "[1/4] 目标项目: $TargetDir" -ForegroundColor Green

# 检查是否在 TestAgent 根目录
$ScriptDir = Split-Path -Parent $PSCommandPath
$ClaudeDir = Join-Path $ScriptDir ".claude"
$QaAgentDir = Join-Path $ScriptDir "qa_agent"

if (-not (Test-Path $ClaudeDir)) {
    Write-Host "[错误] 未找到 .claude/ 目录，请在 TestAgent 根目录运行" -ForegroundColor Red
    exit 1
}

# 步骤 1: 复制 .claude/ 扩展
$TargetClaudeDir = Join-Path $TargetDir ".claude"
Write-Host "[2/4] 复制 Claude Code 扩展..." -ForegroundColor Yellow

if (Test-Path $TargetClaudeDir) {
    $Choice = Read-Host "目标项目已存在 .claude/ 目录，是否覆盖? (y/N)"
    if ($Choice -ne 'y' -and $Choice -ne 'Y') {
        Write-Host "跳过复制 .claude/"
    } else {
        Remove-Item -Recurse -Force $TargetClaudeDir
        Copy-Item -Recurse $ClaudeDir $TargetClaudeDir
        Write-Host "  ✓ 已覆盖 .claude/" -ForegroundColor Green
    }
} else {
    Copy-Item -Recurse $ClaudeDir $TargetClaudeDir
    Write-Host "  ✓ 已复制 .claude/" -ForegroundColor Green
}

# 步骤 2: 安装 Python 包
Write-Host "[3/4] 安装 Python 包..." -ForegroundColor Yellow

# 检查 Python
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[错误] 未找到 python，请先安装 Python 3.9+" -ForegroundColor Red
    exit 1
}

$PythonVersion = & python --version 2>&1
Write-Host "  Python 版本: $PythonVersion"

# 安装（开发模式）
Push-Location $ScriptDir
& python -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] Python 包安装失败" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location
Write-Host "  ✓ 已安装 qa-agent" -ForegroundColor Green

# 步骤 3: 初始化项目
if (-not $SkipInit) {
    Write-Host "[4/4] 初始化项目..." -ForegroundColor Yellow
    Push-Location $TargetDir

    # 检查是否已初始化
    $ConfigFile = Join-Path $TargetDir ".qa-agent.yml"
    if (Test-Path $ConfigFile) {
        Write-Host "  项目已初始化（存在 .qa-agent.yml），跳过" -ForegroundColor Yellow
    } else {
        & qa init
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[警告] qa init 失败，请手动运行" -ForegroundColor Yellow
        } else {
            Write-Host "  ✓ 已生成 .qa-agent.yml" -ForegroundColor Green
        }
    }

    Pop-Location
} else {
    Write-Host "[4/4] 跳过初始化（--SkipInit）" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 安装完成 ===" -ForegroundColor Cyan
Write-Host "下一步："
Write-Host "  1. 编辑 $TargetDir\.qa-agent.yml（检查自动检测的配置）"
Write-Host "  2. 在 Claude Code 中打开 $TargetDir"
Write-Host "  3. 运行 /qa init（如果需要重新初始化）"
Write-Host "  4. 运行 /qa feature <功能名> 或 /qa bugfix <Bug ID>"
Write-Host ""
