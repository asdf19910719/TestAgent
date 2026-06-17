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

## 架构

```
┌─────────────────────────────────────────────┐
│ Claude Code（用户 LLM 入口）                 │
│  ↓ /qa feature 登录                         │
│ .claude/commands/qa.md（slash command）     │
│  ↓ Task tool 委派                          │
│ ├── .claude/agents/qa-test-engineer.md     │
│ │   （Designer+Runner subagent）           │
│ └── .claude/agents/qa-gatekeeper.md        │
│     （Gatekeeper subagent，独立上下文）     │
└─────────────────────────────────────────────┘
                  ↓ Bash 调用
┌─────────────────────────────────────────────┐
│ Python 工具层（qa_agent/）                  │
│  • engine / state_manager / impact_analysis│
│  • adapters/{web,backend,generic}          │
│  • yaml_serializer / report_parser         │
│                                             │
│  机械工作（不调 LLM）                        │
└─────────────────────────────────────────────┘
                  ↓ subprocess
┌─────────────────────────────────────────────┐
│ 测试框架（Playwright/Vitest/pytest 等）     │
└─────────────────────────────────────────────┘
```

## 五档运行模式

| 模式 | 触发场景 | 耗时 | 是否可发版 |
|---|---|---|---|
| **L0 Spot** | 单点小改快速 sanity | 10-30 秒 | ❌ |
| **L1 Feature** | 一个功能开发完 | 1-5 分钟 | ❌ |
| **L2 Module** | 一个模块/迭代完成 | 10-30 分钟 | ❌ |
| **L3 Release** | 准备发版 | 30-120 分钟 | ✅ **唯一发版凭据** |
| **L4 Bugfix** | 修复缺陷后 | 3-15 分钟 | ❌ |

## 快速开始

### 前置要求

1. **Claude Code** 已安装
2. **Python 3.11+** 已安装
3. （可选）GitNexus MCP 已配置（用于精准影响面分析）

### 安装

```bash
# 克隆项目（或作为子模块加入你的项目）
git clone <repo-url> qa-agent
cd qa-agent

# 安装 Python 工具
poetry install
# 或
pip install -e .
```

### 接入项目

把 `.claude/` 目录复制到你的项目根目录：

```bash
cp -r qa-agent/.claude /path/to/your/project/
```

然后在 Claude Code 中打开你的项目。

### 使用

在 Claude Code 中输入：

```
/qa init                          # 引导式初始化
/qa feature 用户登录              # L1 功能级测试
/qa module 订单                   # L2 模块级
/qa release                       # L3 发版门
/qa bugfix BUG-008                # L4 缺陷验证
/qa bugfix "登录后昵称未显示"      # 自然语言描述也支持
/qa retry                         # 重跑上次范围
/qa resume                        # 恢复中断的 L3
/qa status                        # 查看覆盖状态
```

### 命令行直跑（不经 Claude Code）

也支持纯 CLI 调用（仅算法判定，不含 LLM 推理）：

```bash
qa init
qa feature 用户登录
qa bugfix BUG-008
qa release
qa status
```

## 核心特性

### ✅ 影响面驱动

- **GitNexus 模式**（基于代码图精准分析）
- **Local 模式**（git diff + 文件名前缀匹配）
- 用户可扩充执行集，Agent 不可单方面缩减

### ✅ 两角色独立校验

- **Designer+Runner**：测试设计 + 脚本生成 + 执行
- **Gatekeeper**：独立上下文判定（防自审自验）

### ✅ 检查点恢复

- L3 支持 8 个 phase 检查点
- `/qa resume` 中断后恢复
- 24 小时内有效

### ✅ 灵活 bug 引用

```
qa bugfix BUG-008           # Bug ID
qa bugfix TC-LOGIN-003      # 用例 ID
qa bugfix #123              # Issue 编号
qa bugfix 登录后昵称         # 关键词
qa bugfix "用户登录后首页没显示昵称"  # 自然语言
```

### ✅ 非功能测试分级

默认开启（成本低）:
- 依赖漏洞扫描（npm audit / pip-audit）
- 静态安全扫描（bandit / semgrep）

按需开启（命令行参数）:
- `--with-dynamic-security` 动态安全扫描
- `--with-performance` 性能压测
- `--with-compatibility` 兼容性矩阵
- `--with-all-nonfunctional` 全开

## 项目结构

```
your-project/
├── .claude/                     # Claude Code 扩展入口
│   ├── commands/qa.md          # /qa slash command
│   └── agents/
│       ├── qa-test-engineer.md # Designer+Runner subagent
│       └── qa-gatekeeper.md    # Gatekeeper subagent
├── .qa-agent.yml               # 项目配置（qa init 自动生成）
├── qa/                         # QA 数据目录
│   ├── cases/                  # 用例库（YAML）
│   ├── bugs/                   # 缺陷记录
│   ├── run/                    # 执行历史
│   ├── waivers.yml             # 风险接受清单
│   └── final_test_report.md    # 最新测试报告
└── tests/                      # 测试代码（Adapter 生成）
```

## 文档

- [需求与方案文档 v3.0-rev2](docs/AI%20Test%20Engineer%20Agent%20需求与方案文档%20v3.0.md)
- [详细设计 v3.0-rev1](docs/design_v3.0.md)
- [实施总结](IMPLEMENTATION_SUMMARY.md)

## 支持的项目类型

| 类型 | 适配器 | 状态 | 框架 |
|---|---|---|---|
| Web 前端 | WebAdapter | ✅ 完整 | Playwright, Vitest, Jest |
| Python 后端 | BackendAdapter | ✅ 完整 | pytest |
| Go 后端 | BackendAdapter | ✅ 完整 | go test |
| Rust | BackendAdapter | ✅ 完整 | cargo test |
| **Android** | **MobileAdapter** | ✅ **完整** | **JUnit, Espresso, Robolectric** |
| **iOS** | **MobileAdapter** | ✅ **完整**（需配 scheme）| **XCTest, XCUITest** |
| **Flutter** | **MobileAdapter** | ✅ **完整** | **flutter_test, integration_test** |
| **React Native** | **MobileAdapter** | ✅ **完整** | **Jest, Detox** |
| 任意（自定义命令） | GenericAdapter | ✅ 完整 | 任意（Make/Bazel/...） |
| 桌面应用 | DesktopAdapter | 🔜 v1.5 | Electron, Tauri |
| 游戏 | GameAdapter | 🔜 v2.0 | Unity, Unreal |

## 支持的需求文档约定

零配置识别以下框架的产出：

| 框架/约定 | 路径 |
|---|---|
| 通用 docs | `docs/requirements.md`, `docs/design.md`, `docs/PRD.md` |
| **AI 工作流框架** | **`ai-docs/*.md`**（`requirements.md` / `design.md` / `spec.md` / 中文文档名） |
| BMAD | `.bmad/output/*.md` |
| spec-kit | `specs/*/spec.md`, `specs/*/acceptance.feature` |
| BDD | `features/*.feature` |
| 项目根 | `REQUIREMENTS.md`, `PRD.md`, `SPEC.md`, `DESIGN.md` |

显式配置（最高优先级）：

```yaml
# .qa-agent.yml
requirements:
  primary: my-docs/spec.md
  ai_docs_dir: ai-docs/      # 自定义文档目录
  bdd_dir: scenarios/
```

## GitNexus MCP 适配

如果本机的 GitNexus MCP 服务名是 `gitnexus22`（而非默认 `gitnexus`），需在 `.qa-agent.yml` 配置：

```yaml
gitnexus:
  mcp_tool_prefix: mcp__gitnexus22  # 默认 mcp__gitnexus
```

或临时通过环境变量切换：
```bash
export QA_GITNEXUS_TOOL_PREFIX=mcp__gitnexus22
```

## License

MIT
