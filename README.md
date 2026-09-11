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
3. （可选）CodeGraph MCP 已配置（用于精准影响面分析）

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

## 快速开始

### 插件安装（推荐）

本项目是标准 Claude Code 插件。在任意机器的 Claude Code 里两条命令即可：

```
/plugin marketplace add asdf19910719/TestAgent
/plugin install testagent@testagent
```

安装后补上 Python 核心依赖（工具层需要）：

```bash
pip install pyyaml click
# 可选（WebUI E2E / API executor 才需要）：
pip install playwright requests
```

然后重启 Claude Code，在任意项目里用 `/testagent:qa` 触发：

```
/testagent:qa status                # 查看覆盖状态
/testagent:qa feature 登录          # L1 功能级测试
/testagent:qa release               # L3 发版门
```

> 插件机制自带版本管理：作者 bump `plugin.json` 的 `version` 后，用户 `/plugin update testagent` 即可获取更新，无需手工复制文件。

### 备选：源码目录直接使用

克隆仓库后在本项目内开发或调试：

```bash
git clone https://github.com/asdf19910719/TestAgent.git
cd TestAgent
pip install -e .                    # 装工具层（含 CLI 命令 qa）
claude --plugin-dir .               # 本地加载插件测试
```

首次在目标项目使用需初始化：

```bash
qa init   # 自动检测项目类型、框架、需求文档，生成 .qa-agent.yml
# 可编辑 .qa-agent.yml 确认自动检测，特别是 codegraph.mcp_tool_prefixes
```

### 接入项目

（已由上述步骤完成）

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

- **CodeGraph 模式**（基于代码图精准分析）
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

### ⭐ WebUI E2E 增强器（工业级）

**自动登录 + Smart XPath + 专业报告**（移植自 oec-infra webui-test-unified）

- ✅ **登录配方复用**：首次登录后自动保存选择器配方，下次跨会话复用
- ✅ **Smart XPath 生成**：2099 行 JS DOM 提取器，唯一性验证，替代 LLM 猜选择器
- ✅ **Sentinel 预算守卫**：防无限循环（3 轮 + 30 分钟墙钟 + 绝对上限 10 轮）
- ✅ **失败经验库**：自动提取失败经验（scope+pattern 去重，hit_count 递增）
- ✅ **专业 HTML 报告**：单文件（base64 内联），卡片式布局
- ✅ **自动触发**：system/acceptance 级别用例自动启用（可配置）

配置示例：
```yaml
# .qa-agent.yml
webui:
  e2e_enhancer:
    enabled: auto                     # auto | always | never
    trigger_levels: [system, acceptance]
    target_url: http://localhost:3000
    credentials:
      username: test@example.com
      password: test123
```

**价值对比**：

| 项目 | V1（之前） | V2（现在） |
|---|---|---|
| 选择器 | LLM 猜测 | Smart XPath（唯一性验证） |
| 登录 | 每次手写 | 自动登录 + 配方复用 |
| 脚本质量 | 永真断言通过 | 深度校验阻止执行 |
| 执行控制 | 可能无限循环 | Sentinel 预算守卫 |
| 报告 | Playwright 原生 | 专业单文件 HTML |

文档：`docs/WEBUI_MIGRATION.md`

### ⭐ API Test Executor（智能分析 + 自动修复）

**7 大失败分类 + 脚本自动修复 + 专业报告**（移植自 oec-infra api-test-executor）

- ✅ **智能分析引擎**：7 大失败分类（网络/HTTP/参数/响应/认证/脚本/环境）
- ✅ **脚本自动修复**：检测 SyntaxError/ImportError/NameError → 自动修复 → 重试（最多 1 次）
- ✅ **专业 HTML 报告**：紫色渐变统计栏 + 卡片式布局 + 搜索过滤 + 饼图统计
- ✅ **请求详情捕获**：完整 HTTP 请求/响应头体 + 断言结果结构化
- ✅ **401 鉴权处理**：自动处理认证失败
- ✅ **自动触发**：Backend Adapter 默认启用（可配置）

配置示例：
```yaml
# .qa-agent.yml
backend:
  use_api_executor: true              # 使用增强版执行器
  auto_fix_script_errors: true        # 脚本错误自动修复
  max_retry_on_script_error: 1        # 最多重试 1 次
  report_format: html                 # html | json | both
```

**价值对比**：

| 维度 | 原生 pytest | API Test Executor |
|---|---|---|
| 执行能力 | 基础 pytest 执行 | 401 鉴权 + 实时进度 |
| 失败分析 | ❌ 无 | ✅ 7 大分类 |
| 自动修复 | ❌ 无 | ✅ 脚本错误自动修复 |
| 报告格式 | JUnit XML（简陋） | 专业 HTML（可读性 10 倍） |
| 请求详情 | ❌ 无 | ✅ 完整头体 |

文档：`docs/API_EXECUTOR_MIGRATION.md`

### ✅ Gatekeeper 硬规则（5 条红线）

移植自 oec-infra，防止低质量用例通过：

1. **禁止永真断言**：`expect(true).toBe(true)` / `assert True`
2. **禁止占位断言**：`expect(page).toHaveTitle(/.*/)`
3. **禁止空白 try/except**：捕获异常但不处理
4. **禁止虚假等待**：`time.sleep()` / `page.waitForTimeout()`
5. **禁止硬编码凭据**：密码/token/secret 明文

多层级判定：硬规则 → 快速启发式 → LLM 深度分析
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
│   ├── webui/                  # WebUI E2E 会话数据（NEW）
│   │   ├── session/            # 当前会话
│   │   └── shared_assets/      # 登录配方、失败经验库
│   ├── backend/                # Backend API 报告（NEW）
│   │   ├── reports/            # HTML/JSON 报告
│   │   └── fix_history.jsonl  # 脚本修复历史
│   └── final_test_report.md    # 最新测试报告
└── tests/                      # 测试代码（Adapter 生成）
```

**核心代码结构**（qa_agent/ 内部）：

```
qa_agent/
├── adapters/
│   ├── web/
│   │   ├── adapter.py          # Web 前端适配器
│   │   └── e2e_enhancer.py     # E2E 增强器（NEW）
│   ├── backend/
│   │   ├── adapter.py          # Backend 适配器
│   │   └── api_executor/       # API 执行器（NEW）
│   │       ├── enhanced_execute_with_auth.py    # 智能执行器（617 行）
│   │       ├── report_template_fixed.py         # HTML 报告生成器（1905 行）
│   │       ├── conftest_plugin.py               # pytest 插件（1088 行）
│   │       └── script_auto_fixer.py             # 脚本自动修复（NEW）
│   └── mobile/
│       └── adapter.py          # Mobile 适配器
└── webui/                      # WebUI 工具集（NEW）
    ├── login/                  # 登录处理（5 个脚本）
    ├── explorer/               # DOM 探索（3 Python + 1 JS）
    ├── executor/               # 批量执行器（6 个脚本）
    ├── reporter/               # 报告生成（3 个脚本）
    └── validators/             # 校验器（4 个脚本）
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

## CodeGraph MCP 适配

本项目影响面分析默认用 CodeGraph。首次使用需在项目根目录建索引（之后自动同步，无需手动重建）：

```bash
npm i -g @colbymchenry/codegraph   # 安装 CLI（一次）
codegraph install                  # 连接到 Claude Code / Codex 等（一次）
codegraph init                     # 在本项目建索引（一次，之后自动同步）
```

如果本机的 CodeGraph MCP 服务名不是默认的 `codegraph`，需在 `.qa-agent.yml` 配置：

```yaml
codegraph:
  mcp_tool_prefixes: ['mcp__codegraph']  # 默认 mcp__codegraph
```

或临时通过环境变量切换：
```bash
export QA_CODEGRAPH_TOOL_PREFIX=mcp__codegraph
```

## License

MIT
