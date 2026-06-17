#!/usr/bin/env bash
# QA Agent 一键安装脚本（Linux / macOS / Git Bash）
# 用法: ./install.sh /path/to/target

set -euo pipefail

TARGET_PATH="${1:-.}"
SKIP_INIT="${2:-}"

echo "=== QA Agent 安装脚本 ==="

# 检查目标路径
if [[ ! -d "$TARGET_PATH" ]]; then
    echo "[错误] 目标路径不存在: $TARGET_PATH" >&2
    exit 1
fi

TARGET_DIR="$(cd "$TARGET_PATH" && pwd)"
echo "[1/4] 目标项目: $TARGET_DIR"

# 检查是否在 TestAgent 根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$SCRIPT_DIR/.claude"
QA_AGENT_DIR="$SCRIPT_DIR/qa_agent"

if [[ ! -d "$CLAUDE_DIR" ]]; then
    echo "[错误] 未找到 .claude/ 目录，请在 TestAgent 根目录运行" >&2
    exit 1
fi

# 步骤 1: 复制 .claude/ 扩展
TARGET_CLAUDE_DIR="$TARGET_DIR/.claude"
echo "[2/4] 复制 Claude Code 扩展..."

if [[ -d "$TARGET_CLAUDE_DIR" ]]; then
    read -p "目标项目已存在 .claude/ 目录，是否覆盖? (y/N): " CHOICE
    if [[ "$CHOICE" =~ ^[Yy]$ ]]; then
        rm -rf "$TARGET_CLAUDE_DIR"
        cp -r "$CLAUDE_DIR" "$TARGET_CLAUDE_DIR"
        echo "  ✓ 已覆盖 .claude/"
    else
        echo "  跳过复制 .claude/"
    fi
else
    cp -r "$CLAUDE_DIR" "$TARGET_CLAUDE_DIR"
    echo "  ✓ 已复制 .claude/"
fi

# 步骤 2: 安装 Python 包
echo "[3/4] 安装 Python 包..."

# 检查 Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "[错误] 未找到 python，请先安装 Python 3.9+" >&2
    exit 1
fi

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

PYTHON_VERSION="$($PYTHON_CMD --version)"
echo "  Python 版本: $PYTHON_VERSION"

# 安装（开发模式）
(cd "$SCRIPT_DIR" && $PYTHON_CMD -m pip install -e . --quiet)
echo "  ✓ 已安装 qa-agent"

# 步骤 3: 初始化项目
if [[ "$SKIP_INIT" != "--skip-init" ]]; then
    echo "[4/4] 初始化项目..."
    cd "$TARGET_DIR"

    # 检查是否已初始化
    CONFIG_FILE="$TARGET_DIR/.qa-agent.yml"
    if [[ -f "$CONFIG_FILE" ]]; then
        echo "  项目已初始化（存在 .qa-agent.yml），跳过"
    else
        if qa init; then
            echo "  ✓ 已生成 .qa-agent.yml"
        else
            echo "[警告] qa init 失败，请手动运行" >&2
        fi
    fi
else
    echo "[4/4] 跳过初始化（--skip-init）"
fi

echo ""
echo "=== 安装完成 ==="
echo "下一步："
echo "  1. 编辑 $TARGET_DIR/.qa-agent.yml（检查自动检测的配置）"
echo "  2. 在 Claude Code 中打开 $TARGET_DIR"
echo "  3. 运行 /qa init（如果需要重新初始化）"
echo "  4. 运行 /qa feature <功能名> 或 /qa bugfix <Bug ID>"
echo ""
