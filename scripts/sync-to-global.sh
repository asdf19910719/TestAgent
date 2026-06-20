#!/bin/bash
# TestAgent 全局同步脚本
# 用途：将本地 .claude/ 配置同步到全局 Claude 目录

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GLOBAL_CLAUDE="$HOME/.claude"

echo "=== TestAgent 全局同步 ==="
echo "项目根目录: $PROJECT_ROOT"
echo "全局目录: $GLOBAL_CLAUDE"
echo ""

# 1. 同步 agents
echo "[1/3] 同步 agents..."
cp -v "$PROJECT_ROOT/.claude/agents/"*.md "$GLOBAL_CLAUDE/agents/"
echo ""

# 2. 同步 commands
echo "[2/3] 同步 commands..."
cp -v "$PROJECT_ROOT/.claude/commands/"*.md "$GLOBAL_CLAUDE/commands/"
echo ""

# 3. 验证
echo "[3/3] 验证..."
echo "Agents:"
ls -lh "$GLOBAL_CLAUDE/agents/" | grep "qa-" | awk '{print "  " $5, $9}'
echo ""
echo "Commands:"
ls -lh "$GLOBAL_CLAUDE/commands/" | grep "qa" | awk '{print "  " $5, $9}'
echo ""

echo "=== 同步完成 ==="
