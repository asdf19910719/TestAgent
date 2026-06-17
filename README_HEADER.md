# AI Test Engineer Agent v3.0 Solo Edition

> **产品级质量 + 个人级流程**
> Claude Code 扩展（不需要 API key）

AI Test Engineer Agent 帮助个人开发者把 AI 产出的代码从"看起来能跑"升级为"经过测试和真实验证"的质量。

## 为什么是 Claude Code 扩展

本项目作为 Claude Code 的扩展运行：

* ✅ **不需要单独的 Claude API key**
* ✅ 复用 Claude Code 的 LLM 推理能力
* ✅ 在 Claude Code 中直接 `/qa feature 登录` 触发
* ✅ Subagent 委派机制（Designer+Runner / Gatekeeper 独立判定）

## 快速开始

### 一键安装（推荐）

**Windows PowerShell**：
```powershell
cd E:\AIProject\TestAgent
.\install.ps1 D:\YourProject
```

**Linux / macOS / Git Bash**：
```bash
cd /path/to/TestAgent
./install.sh /path/to/YourProject
```

脚本自动完成：
1. 复制 `.claude/` 扩展到目标项目
2. 安装 Python 包（`pip install -e .`）
3. 初始化项目（`qa init`）

### 手动安装

如果一键脚本失败，按以下步骤：

**1. 复制扩展**：
```bash
cp -r .claude /path/to/your/project/
```

**2. 安装 Python 包**：
```bash
cd TestAgent
pip install -e .
```

**3. 初始化项目**：
```bash
cd /path/to/your/project
qa init
# 自动检测项目类型、框架、需求文档
# 生成 .qa-agent.yml
```

**4. 检查配置（可选）**：
```yaml
# 编辑 .qa-agent.yml 确认自动检测正确
# 特别是 gitnexus.mcp_tool_prefixes（本机如用 gitnexus22 可调整）
```

然后在 Claude Code 中打开你的项目。

### 使用

**在 Claude Code 中**：
```
/qa init                          # 引导式初始化
/qa feature 用户登录              # L1 功能级测试
/qa module 订单                   # L2 模块级
/qa release                       # L3 发版门
/qa bugfix BUG-008                # L4 缺陷验证
/qa status                        # 查看覆盖状态
```

**命令行直跑（不经 Claude Code）**：
```bash
qa feature 用户登录
qa bugfix BUG-008
qa status
```
