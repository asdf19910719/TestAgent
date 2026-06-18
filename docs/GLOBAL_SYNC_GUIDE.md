# 全局 Claude 目录同步指南

## 概述

TestAgent 的核心指令和 Agent 需要同步到全局 Claude 目录（`~/.claude/`），使所有项目都能使用 `/qa` 命令。

---

## 同步目标

| 源文件（本项目） | 目标位置（全局） | 作用 |
|---|---|---|
| `.claude/agents/qa-gatekeeper.md` | `~/.claude/agents/qa-gatekeeper.md` | Gatekeeper Agent |
| `.claude/agents/qa-test-engineer.md` | `~/.claude/agents/qa-test-engineer.md` | Designer + Runner Agent |
| `.claude/commands/qa.md` | `~/.claude/commands/qa.md` | /qa 命令入口 |
| 全局 CLAUDE.md 中的 TestAgent 段落 | `~/.claude/CLAUDE.md` | 使用说明 |

---

## 同步命令

### 一键同步（在 TestAgent 项目根目录执行）

```bash
# Windows (Git Bash)
cp .claude/agents/qa-gatekeeper.md "$HOME/.claude/agents/"
cp .claude/agents/qa-test-engineer.md "$HOME/.claude/agents/"
cp .claude/commands/qa.md "$HOME/.claude/commands/"
```

### 验证同步结果

```bash
echo "Agents:"
ls -lh "$HOME/.claude/agents/" | grep "qa-"
echo "Commands:"
ls -lh "$HOME/.claude/commands/" | grep "qa"
```

---

## 何时需要同步

以下情况需要重新执行同步：

1. **修改了 `.claude/agents/qa-gatekeeper.md`**（新增/修改硬规则）
2. **修改了 `.claude/agents/qa-test-engineer.md`**（修改测试策略）
3. **修改了 `.claude/commands/qa.md`**（修改命令定义）

简单判断：**如果本次修改涉及 `.claude/` 目录下的文件，就需要同步。**

---

## 注意事项

### 不要同步的内容

- ❌ 不要把整个项目复制到 `~/.claude/`
- ❌ 不要同步 `~/.claude/projects/TestAgent/`（这不是全局指令路径）
- ❌ 不要同步 Python 代码到全局目录（工具层通过 pip install 安装）

### 全局 CLAUDE.md 维护

`~/.claude/CLAUDE.md` 中有一段 TestAgent 的使用说明。如果修改了使用方式，需要手动更新这段内容。当前内容包括：

- 使用方式（/qa 命令示例）
- 注册的全局资源表
- 前置要求
- 核心防护机制列表
- 工具层安装说明

### 冲突处理

如果全局目录已有同名文件：
- `qa-gatekeeper.md` / `qa-test-engineer.md` / `qa.md` → 直接覆盖（以本项目为准）
- `CLAUDE.md` → 只更新 TestAgent 段落，不覆盖其他内容

---

## 全局目录结构说明

```
~/.claude/
├── CLAUDE.md                  # 全局指令（含 TestAgent 使用说明）
├── agents/                    # 全局 Agent 定义
│   ├── qa-gatekeeper.md      # ← 从本项目同步
│   ├── qa-test-engineer.md   # ← 从本项目同步
│   └── (其他项目的 agents)
├── commands/                  # 全局命令定义
│   ├── qa.md                 # ← 从本项目同步
│   └── (其他项目的 commands)
└── (其他 Claude Code 系统文件)
```

---

## 工具层安装（可选）

如需 Python 工具层完整功能（影响面分析、覆盖率检查等）：

```bash
cd E:\AIProject\TestAgent
pip install -e .
```

安装后可在任何目录使用 CLI：

```bash
qa init
qa feature 用户登录
qa release
qa status
```
