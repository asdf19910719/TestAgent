# AI Test Engineer Agent 需求与方案文档

> 版本：v3.0-rev2 Solo Edition
> 修订日期：2026-06-17
> 文档定位：面向**个人开发者**的产品级测试 Agent 规范
> **架构定位**：Claude Code 扩展（不需要 Anthropic API key）

## 0. v3.0-rev2 关键修订（架构纠偏）

**v3.0-rev1 → v3.0-rev2 的根本性变化**：

| 维度 | rev1 错误方向 | rev2 正确方向 |
|---|---|---|
| LLM 调用方 | Python + anthropic SDK | Claude Code（slash command + subagent）|
| API key | 需要单独配置 | 不需要 |
| 用户入口 | `qa feature ...`（终端）| `/qa feature ...`（Claude Code）|
| 月成本 | $20-100 | $0（Claude Code 订阅已含）|
| Designer/Gatekeeper | Python 类内调用 LLM | `.claude/agents/*.md` subagent |
| 提示词位置 | `prompts/*.txt` | subagent 定义文件内 |

### 新架构

```
Claude Code（用户 LLM 入口）
   ↓ /qa feature 登录
.claude/commands/qa.md（slash command）
   ↓ Task tool 委派
├── .claude/agents/qa-test-engineer.md（Designer+Runner）
└── .claude/agents/qa-gatekeeper.md（Gatekeeper，独立上下文）
   ↓ Bash 调用
qa_agent/ Python 工具层（机械工作，不调 LLM）
   ↓ subprocess
测试框架（Playwright/Vitest/pytest 等）
```

### Python 工具层职责变化

不再"自己调 LLM"，改为"提供机械工作 + 输出结构化任务"：

* **DesignerRunner**：加载/保存用例库、调用 Adapter 真实执行、收集失败、持久化
* **Gatekeeper**：算法判定（L0/L4 足够）+ 报告框架；L1-L3 标记 `needs_subagent_review` 由 subagent 接管
* **CLI 新增 subagent 子命令**：`prepare` / `scaffold` / `execute` / `judge` / `resolve-bugfix`，供 subagent 通过 Bash 调用

### 文件结构

新增：
- `.claude/commands/qa.md` - 用户入口 slash command
- `.claude/agents/qa-test-engineer.md` - Designer+Runner subagent
- `.claude/agents/qa-gatekeeper.md` - Gatekeeper subagent（独立上下文）

删除：
- `anthropic` SDK 依赖（pyproject.toml）
- `jinja2` 依赖（提示词不再渲染模板）
- `prompts/*.txt`（提示词移到 subagent 定义文件内）

> 后文（§1 起）保留 v3.0-rev1 的所有约束、红线、模式定义、影响面算法等内容。
> rev2 是**架构纠偏**，不是规范变更——所有质量保证机制原样保留。

---
> 质量目标：产品级（经过测试和验收的质量）
> 流程目标：个人级（最小化仪式，最大化价值）

---

## 0. Solo Edition 定位

### 为什么需要 Solo Edition

v2.1 企业版有 162 条强制约束，适合多人团队协作。但个人开发者的需求不同：

* **团队规模**：一个人
* **质量目标**：产品级（不接受"看起来能跑"就算完成）
* **需求管理**：使用 BMAD / spec-kit，需求文档完整
* **核心痛点**：AI 经常"功能看起来能跑"就宣布完成，缺少真实验证

Solo Edition = **产品级质量 + 个人级流程**。

### v3.0 相对 v2.1 的简化

| 维度 | v2.1 企业版 | v3.0 Solo Edition |
|---|---|---|
| 强制约束数 | 162 条 | 68 条 |
| 角色数 | 3（Designer / Runner / Gatekeeper） | 2（Designer+Runner 合并 / Gatekeeper 独立） |
| 配置文件行数 | 80 行起步 | 10 行起步 |
| Waiver 流程 | commit 作者白名单 + 签字 + PoC 证据 | 标记 + 过期时间 |
| 需求同步 | 段落语义指纹（SimHash） | LLM 直接比对 |
| 自检清单 | 16 项 | 8 项 |

**保留**：所有质量保证机制（反伪造红线、L3 全量、影响面分析、mutation/flaky、对抗式 review、失败循环防护）。

**删除**：组织协作仪式（commit 白名单、KPI 回流、异质模型、人/Agent 触发区分）。

### v3.0-rev1 相对 v3.0 的修订（15 项）

经过设计审查发现并修复的关键漏洞：

**P0 级修复（7 项）**：

1. **需求文档自动扫描路径明确**（§12.1 新增）：默认按约定路径扫描，找不到才反向梳理
2. **L4 影响面深度=3 + 说明**（§8.1）：动态语言项目可在配置中覆盖
3. **Gatekeeper 校验 requirement_ids**（§3.3）：用 LLM 语义比对，不一致标 review
4. **Generic Adapter 兜底**（§14.4 新增）：支持 Rust/Go/C++ 等非标准项目
5. **非功能测试分级**（§15.6 重写）：依赖漏洞 + 静态安全默认开；动态安全/性能/兼容默认关
6. **修复轮触发模式**（§5.7 + §11）：manual（默认）/ auto-dev / auto-fixer 三档
7. **所有模式都有修复轮**（§18.3）：不只 L3，L0/L1/L2/L4 也有，受 5 轮上限保护

**P1 级修复（4 项）**：

8. **Gatekeeper LLM 成本优化**（§3.3 + §11）：L0/L4 算法判定 + 默认 Haiku + 缓存
9. **targets 自动维护触发时机**（§9.2）：每次增量 + rename 检测 + `/qa reindex`
10. **Mutation 工具降级**（§5.6）：不自动安装 + 优雅跳过 + 报告标注
11. **L3 检查点恢复**（§18.5 新增）：按 phase 检查点 + `/qa resume`

**P2 级优化（4 项）**：

12. **引导式初始化**（§18.1 重写）：`/qa init` 自动检测 + 生成草稿 + 交互引导
13. **灵活 bug 引用**（§7.2）：支持 BUG-XXX / TC-XXX / #issue / 关键词 / 自然语言
14. **智能下一步提示**（§13.6 新增）：每次执行后输出"建议下一步"
15. **GitNexus 降级交互**（§8.4）：不可用时提供选项菜单（重试/local/手动/取消）

---

## 1. 背景

AI 辅助开发的现状：

```text
AI 写完代码 → 看起来能跑 → 口头宣布完成
```

问题：

* AI 不会真正执行和验证
* AI 经常假设"用户会手动测"
* 失败时 AI 倾向于删除失败测试或弱化断言来"修复"

本 Agent 的目标：让 AI 产出的代码达到**真实验证过**的质量。

---

## 2. Agent 总目标

把 AI 开发从"口头宣布完成"升级为：

```text
AI 写完代码
↓
按场景选择运行模式（L0–L4）
↓
Designer+Runner 生成/更新用例库 + 执行
↓
Gatekeeper 独立判定 PASS / FAIL / BLOCKED
↓
仅 L3 输出发布质量门结论
```

### 2.1 KPI（当前不追踪，预留接口）

Solo 项目初期不追踪 KPI，但预留接口：

* **缺陷逃逸率**：验收/上线后发现的缺陷数 / 总缺陷数
* **误报率**：被标为 fail 实为测试代码问题的比例

数据来源：`qa/feedback/` 目录（手工标注，当前版本不强制）。

---

## 3. Agent 角色拆分（两角色）

### 3.1 为什么拆分

单角色问题："Designer 写了个错的断言 → Runner 跑过了 → 自己说通过" = 自己批改自己作业。

### 3.2 两角色方案

| 角色 | 职责 | 独立性 |
|---|---|---|
| **Designer+Runner** | 测试设计 + 脚本生成 + 执行 + 收集失败 | 同一上下文（效率优先） |
| **Gatekeeper** | 回归选择 + 判定 PASS/FAIL/BLOCKED + 签发结论 | **独立上下文**（防止确认偏差） |

**Gatekeeper 必须独立**：它不能看到 Designer 的推理过程，必须基于：
1. 原始需求文档（从 `docs/` 直接读，不 trust Designer 的摘录）
2. 用例库（`qa/cases/`）
3. 执行结果（`qa/run/last.json`）

来独立判定。这是 Solo Edition **唯一保留的角色拆分**，因为它服务于质量，不是组织协作。

### 3.3 Gatekeeper 独立校验算法（P0-3）

Gatekeeper 不能直接信任 Designer+Runner 写的 `requirement_ids` 关联。校验流程：

1. **读取原始需求文档**（按 §12.1 自动扫描路径）
2. **读取用例库**（`qa/cases/`）
3. **LLM 语义比对**：对每条用例，让 LLM 独立判断"这条用例验证的是哪个需求"
4. **对比 Designer 的关联**：

```python
designer_says = case.requirement_ids  # [REQ-101]
gatekeeper_infers = llm_infer_requirements(case, requirements_doc)  # [REQ-102]

if set(designer_says) != set(gatekeeper_infers):
    case.state = 'review'  # 标记需要人工复审
    report_inconsistency(case.id, designer_says, gatekeeper_infers)
```

5. **输出不一致清单**：在 `release_gate_report.md` 中列出所有 Designer 与 Gatekeeper 推断不一致的用例
6. **L3 质量门**：存在不一致 → 结论降级为 `CONDITIONAL PASS`，必须人工复审

### 3.4 Gatekeeper LLM 成本优化（P1-1）

为降低 Solo 项目长期使用成本，Gatekeeper 采用三层优化：

**层级 1：算法判定（无 LLM 调用）**

L0 / L4 / 简单 L1 默认走纯算法：

```text
L0：所有 P0 用例 PASS → 通过；任何 P0 fail → 失败
L4：原失败用例 PASS + 回归全 PASS → verified
    出现新失败 → 升级到 LLM 判定
```

**层级 2：默认使用 Haiku（便宜模型）**

```yaml
# .qa-agent.yml 默认值
roles:
  gatekeeper_model: claude-haiku-4-5  # 比 Opus 便宜 10x
```

L3 发版门可显式覆盖为 Opus（更可靠的判定）：

```yaml
roles:
  gatekeeper_model_l3: claude-opus-4-7
```

**层级 3：判定结果缓存**

如果（需求 hash + 用例库 hash + 执行结果 hash）未变 → 直接复用上次 Gatekeeper 判定。

### 3.5 修复角色

修复默认由用户手动完成（参见 §5.7 修复轮触发模式）。若启用 `auto-dev` 模式由外部 Dev Agent 完成；若启用 `auto-fixer` 由独立上下文 QA-Fixer 执行（高风险，不推荐）。无论哪种，修复后必须重新触发 Runner + Gatekeeper，不允许 Fixer 自己宣布通过。

---

## 4. 适用范围

该 Agent 设计为通用测试工程师核心能力，可用于不同项目类型：

| 类型 | 适用性 |
|---|---|
| Web 前端 | ✅ 完整支持 |
| 后端 API | ✅ 完整支持 |
| 全栈 | ✅ 完整支持 |
| 移动端 | ⚠️ 基础支持（v1.5 完整） |
| 桌面应用 | ⚠️ 基础支持（v1.5 完整） |
| 游戏 | ⚠️ 基础支持（v2.0 完整） |
| CLI 工具 | ✅ 完整支持 |

**个人项目通常场景**：Web / 后端 / CLI 工具。这些在 v1.0 已完整支持。

---

## 5. 核心设计原则

### 5.1 测试用例不是"阶段产物"

测试用例是**长期资产**，结构化存储在 `qa/cases/`，版本管理，增量演进。不是每次重新生成的中间产物。

### 5.2 测试必须沉淀为可执行脚本

不允许只有"测试计划"或"测试步骤描述"。必须生成实际可运行的自动化脚本，并记录在 `automation.file` 字段。

### 5.3 需求决定测什么

测试用例必须关联需求。使用 BMAD / spec-kit 时，需求来自 `docs/requirements.md` / `docs/acceptance_criteria.md` / `specs/*/spec.md`。

### 5.4 测试必须分层

| 测试层级 | 目标 |
|---|---|
| 单元测试 | 验证单个函数、类、模块、状态机、纯逻辑 |
| 集成测试 | 验证多个模块之间是否正确协作 |
| 系统测试 | 验证整个系统或应用是否能完整运行 |
| 验收测试 | 验证功能是否满足需求和验收标准 |
| 冒烟测试 | 验证核心流程是否可启动、可进入、无阻塞错误 |

回归测试不在此表中，它是测试目的而非层级。

### 5.5 反伪造红线（强制）

禁止以下行为，任何一项触发即视为 Agent 违约：

1. 删除失败测试来伪造通过
2. 降低断言标准来伪造通过
3. 跳过失败测试但仍宣布完成
4. 没有运行测试就声称测试通过
5. 只运行程序不做断言
6. 只手动体验一次就认为完成
7. 未记录失败原因就直接修改代码
8. 修复后不做回归测试
9. **L0 / L1 / L4 模式的结果作为发版依据**
10. **Agent 自行降档运行模式**（必须由用户显式指令）
11. **Agent 自行缩减用例选择范围**（用户可扩充，Agent 不可单方面缩减）
12. **以"省成本"为由缩减执行集**（成本不构成合法理由；上下文窗口物理上限触发时按"熔断暂停 + 拆分"处理）

### 5.6 测试代码自身的质量保障

测试代码不是免检产物：

* 每个测试必须至少一个**有效断言**（不是 `assert True` 或仅打印）
* 覆盖率门槛由项目级配置（默认 P0 相关代码行覆盖 ≥ 80%）
* **Mutation testing（仅 L3 + 仅 diff）**：默认**仅 L3** 启用，且**只对本次 diff 涉及的源文件**做变异（不全量）
* **对抗式 review（仅 L2/L3）**：Designer+Runner 完成用例后，由 Gatekeeper 独立上下文执行——尝试构造"实现错误但用例仍 PASS"的反例
* **Flaky 检测（仅对失败用例）**：单条用例**失败**才触发隔离重跑（默认 5 次），全 PASS 才视为偶发并标 flaky 候选。**通过用例不重复跑**

#### Mutation 工具降级策略（P1-3）

如果 mutmut / Stryker 等 mutation 工具不存在：

* ❌ **不自动安装**（避免改变用户环境）
* ✅ **优雅跳过**：在执行报告中显式标注 `mutation: skipped (tool not found)`
* ✅ **不阻断 L3 通过**：mutation 是质量提升项，不是硬阈值
* ✅ Adapter capabilities 中 `mutation: false` 时，Core 自动跳过相关阶段

```yaml
# .qa-agent.yml 配置
mutation:
  enabled: true                 # true | false | auto（默认 auto，工具存在才跑）
  scope: diff                   # 仅 diff 涉及源文件
  enabled_modes: [L3]
  on_tool_missing: skip         # skip（默认） | warn | fail
```

### 5.7 失败循环防护与修复轮触发模式（P0-6）

防止 AI 陷入"失败 → 改 → 再失败"无限循环：

* 单条用例自动修复尝试上限：**3 次**
* 单次 QA 流程内的整体修复轮次上限：**5 轮**
* 超限后必须停止，输出 `BLOCKED` 并升级人工
* 同一断言连续失败两次，禁止继续修改测试代码本身（说明问题在被测代码或需求）

#### 修复轮的三种触发模式

| 模式 | 触发方式 | 适用场景 | 风险 |
|---|---|---|---|
| **manual**（默认） | Runner 失败 → 报告退出 → 你修代码 → 你跑 `/qa retry` | 个人开发者自己修代码 | 低 |
| **auto-dev** | Runner 失败 → 自动调用 Dev Agent 修 → 重跑 | 配合 BMAD/spec-kit Dev Agent | 中（Dev Agent 改坏） |
| **auto-fixer** | Runner 失败 → QA-Fixer 自己修 → 重跑 | 不推荐（自审自验） | 高 |

**Solo Edition 默认 manual**。配置切换：

```yaml
# .qa-agent.yml
repair_loop:
  mode: manual                    # manual（默认） | auto-dev | auto-fixer
  per_case_attempts: 3
  total_rounds: 5
```

#### Manual 模式的工作流（最常用）

```text
Step 1: 你跑 /qa bugfix BUG-008
        ↓
Step 2: Runner 跑 TC-LOGIN-003 → fail
        ↓
Step 3: Agent 输出失败报告 + 退出
        ❌ TC-LOGIN-003 fail
           错误：Expected 'alice', got undefined
           位置：src/api/auth.ts:42
           已记录到 qa/bugs/BUG-009.yml
           
        请修复后运行：/qa retry  或  /qa bugfix BUG-008
        ↓
Step 4: 你修代码
        ↓
Step 5: 你跑 /qa retry
        ↓
Step 6: Runner 重跑 TC-LOGIN-003 + 受影响范围
        ↓
Step 7: PASS → Gatekeeper 判定 verified
        FAIL → 回到 Step 3
        ↓
Step 8: 累计 5 轮失败 → BLOCKED，必须人工介入
```

**关键约束**：

* Agent 不会主动监听 git 变化偷偷重跑（避免打断心流）
* 修复轮**仅在同一次 `/qa` 命令的执行内部**生效（auto-* 模式）
* `/qa retry` 是新的 `/qa` 命令，会使用上次的 selection 重新执行
* 所有模式（L0/L1/L2/L3/L4）都有修复轮，受 5 轮上限保护

### 5.8 Waiver / 风险接受机制（个人项目简化版）

"已知不修复但允许放行"的失败用例，必须在 `qa/waivers.yml` 中显式登记：

```yaml
- case_id: TC-LOGIN-003
  reason: 边界输入校验，非核心流程
  waived_until: 2026-07-15
  severity: low
```

**简化点**：
* 无需 `approved_by` 字段和 commit 作者白名单（个人项目只有一个人）
* 无需 PoC 不可达性证据（除非安全用例）
* **安全用例（critical/high）仍禁止 waiver**
* 过期自动失效

### 5.9 需求变更与用例同步（LLM 比对版）

* 每条用例必须关联**需求 ID**
* 需求文档变更时，Designer 必须用 LLM 直接比对需求段落：
  * **完全一致或语义等价** → 用例继续 active
  * **微调（增加细节但核心不变）** → 标 `state: review`，由 Designer 快速复审
  * **核心变化** → 标 `state: stale`
* 任何 `stale` 用例不计入"已通过"，必须先复审或重设计后才能再执行

**Solo 简化**：不使用 SimHash 语义指纹，直接用 LLM 比对（个人项目需求变更频率低，LLM 比对成本可接受）。

---

## 6. 与 BMAD / Spec Kit 的关系

该 Agent 不替代 BMAD 或 Spec Kit：

```text
BMAD / Spec Kit：需求、规格、架构、任务、验收标准
AI Test Engineer Agent：测试计划、测试用例、自动化测试、测试报告、缺陷修复、回归测试
```

**Solo 项目关键点**：因为使用 BMAD/spec-kit，需求文档完整，**反向梳理流程基本不会触发**（反向梳理是为没有需求文档的项目准备的兜底方案）。

---

## 7. 运行模式 L0–L4（核心成本控制）

不允许每次改动都跑全流程。Agent 提供 5 档运行模式，由用户**显式指令**触发。

### 7.1 模式定义

| 模式 | 触发场景 | 设计阶段 | 执行阶段 | 产出 | 发版依据 |
|---|---|---|---|---|---|
| **L0 Spot** | 单点小改 / 快速 sanity | 不做设计，命中现有受影响用例 | 仅跑受影响单测 + 关联冒烟 | 终端一行摘要 | ❌ |
| **L1 Feature** | 一个功能开发完 | 增量补该功能用例 | 跑该功能全部分层用例 + 邻接回归 | 功能级测试报告 | ❌ |
| **L2 Module** | 一个模块/迭代完成 | 复核该模块所有用例完整性 | 跑该模块全部用例 + 跨模块集成 + 抽样 mutation | 模块级测试报告 + 缺陷清单 | ❌ |
| **L3 Release** | 准备发版 / 验收 | 校验需求追踪矩阵 100% 覆盖 | 全量分层 + 非功能（性能/安全/兼容） + flaky 检测 + mutation（仅 diff） | 完整测试结论 + 质量门决策 | ✅ **唯一发版依据** |
| **L4 Bugfix** | 修复某个缺陷后 | 不做设计，定位失败用例 | 跑该缺陷复现用例 + 影响面回归 | 缺陷验证报告 | ❌ |

### 7.2 触发方式（灵活 bug 引用 P2-2）

#### 基本指令

* `/qa L0` —— 单点 sanity
* `/qa feature 用户登录` —— L1
* `/qa module 订单` —— L2
* `/qa release` —— L3
* `/qa bugfix <reference>` —— L4
* `/qa retry` —— 重跑上次的 selection（用于修复后再验证）
* `/qa resume` —— 恢复中断的 L3 运行（参见 §18.5）
* `/qa init` —— 首次接入项目时的引导式初始化（参见 §18.1）
* `/qa reindex` —— 手动触发 targets 全量重建

Agent 接到指令后**先回报预估**，等用户回复 `yes` 才执行。

#### `/qa bugfix` 的灵活引用

`<reference>` 支持多种形式，Agent 自动解析：

| 引用形式 | 示例 | 说明 |
|---|---|---|
| Bug ID | `/qa bugfix BUG-008` | 已登记的 bug |
| 用例 ID | `/qa bugfix TC-LOGIN-003` | Agent 反查关联 bug |
| Issue 编号 | `/qa bugfix #123` | GitHub/GitLab issue |
| 关键词 | `/qa bugfix 登录后昵称` | 模糊匹配 bug 标题 |
| 自然语言 | `/qa bugfix "用户登录后首页没显示昵称"` | 自动新建 bug 记录 |

Agent 内部解析顺序：

1. 匹配 `BUG-\d+` → 直接加载
2. 匹配 `TC-[A-Z]+-\d+` → 反查关联 bug
3. 匹配 `#\d+` → 关联 issue tracker（若配置）
4. 短文本（< 30 字符） → 模糊搜索 `qa/bugs/`
5. 长描述 → 自动创建新 bug 记录

### 7.3 强制规则

* **L3 不允许省略**：发版/验收前必须完整执行一次 L3
* **Agent 不得自行降档**：用户要求 L3，Agent 不能因"看上去用例不多"自动改成 L1
* **升级路径单向**：
  * L0 在同一变更上累计失败 ≥ 2 次 → 强制升 L1
  * L1 在同一功能上累计失败 ≥ 2 次 → 强制升 L2

### 7.4 执行预算

* **不设 token 上限**
* **单次执行用例数上限**：默认 L0=10、L1=80、L2=500、L3=不限、L4=20，可在 `.qa-agent.yml` 覆盖
* 上限触发时**熔断暂停**："当前选择超过模式上限，是否继续 / 拆分 / 切换模式？" 由用户决定

---

## 8. 影响面分析（执行裁剪算法）

执行阶段"跑哪些用例"由影响面分析决定。本规范**默认依赖 GitNexus**，仅在用户显式禁用时才回退到本地 diff。

### 8.1 默认实现（GitNexus 模式）

1. 取本次变更的 diff
2. 调用 GitNexus 工具：
   * `mcp__gitnexus__detect_changes`：拿到变更涉及的符号列表
   * 对每个变更符号调用 `mcp__gitnexus__impact`，方向 `upstream`，深度按下表
3. 把受影响符号集合反查 `qa/cases/*.yml` 中 `targets:` 字段，命中即纳入执行集
4. **补集兜底**：命中用例的 `feature_id` 集合 → 纳入同 `feature_id` 的所有用例（L2/L3 全开；L1 仅 P0/P1）
5. 历史 flaky / 易失败用例额外纳入
6. 输出执行集 + 选择理由（写入 `qa/run/selection.md`）

#### 影响面深度策略（P0-2）

| 模式 | 深度 | 理由 |
|---|---|---|
| L0 | 2 | 最快反馈，仅直接调用链 + 一层 |
| L1 | 3 | 功能级，覆盖主要调用路径 |
| L2 | 3 | 模块级，与 L1 同深度但选中范围更广 |
| L3 | -1（不限） | 发版级，追溯到最顶层 UI/入口 |
| L4 | 3 | 缺陷验证，覆盖主要影响面但不全量 |

**为什么 L4 是 3？**

* depth=1-2：容易漏测深层调用链的破坏
* depth=3：覆盖 80% 的实际影响面
* depth=-1：接近全量回归，失去"快速验证"意义，应该用 L3

**动态语言/反射项目调优**：Python/JS/Ruby 等深层间接调用多的项目可在配置覆盖：

```yaml
# .qa-agent.yml
gitnexus:
  upstream_depth:
    L0: 2
    L1: 3
    L2: 3
    L3: -1
    L4: 5     # 默认 3，动态语言项目建议提到 5
```

### 8.2 Local 模式（GitNexus 不可用时）

基于 git diff 与用例 `targets.files` 字段字符串匹配：

1. `git diff --name-only` 拿到变更文件列表
2. 遍历 `qa/cases/` 所有用例，匹配 `targets.files` 前缀
3. 加上 feature_id 补集、历史关联失败

### 8.3 用户扩充

* 用户必须能追加用例 ID 或 tag
* Agent 不得单方面缩减用户提供的执行集

### 8.4 GitNexus 不可用时的处理（P2-4 交互式降级）

GitNexus 工具调用失败 → Agent **不得静默回退**，必须明确告知并提供选项菜单：

```text
[Agent] 正在分析影响面...
❌ GitNexus 工具不可用：连接超时（已重试 2 次）

可选操作：
  1. 等待 GitNexus 恢复（重试：/qa retry）
  2. 切换到本地 diff 模式（快速但精度低：会标注"影响面分析为粗粒度近似"）
  3. 手动指定执行范围（精确但慢：/qa feature 登录 --cases TC-LOGIN-*）
  4. 取消本次运行

选择 1-4：_
```

#### 持久化降级策略

```yaml
# .qa-agent.yml
impact_analysis: gitnexus       # gitnexus（默认） | local
impact_fallback: prompt         # prompt（默认） | local | fail

# prompt: 交互式询问（默认）
# local: 不可用时自动回退到本地 diff，但报告中显著标注
# fail: 不可用时直接失败退出
```

#### Local 模式的报告标注

回退到 local 模式时，`qa/run/selection.md` 必须在头部加显著警告：

```markdown
> ⚠️ **本次未使用 GitNexus 代码图**
> 影响面分析为粗粒度文件名前缀匹配，可能漏选用例
> 建议尽快恢复 GitNexus 后重跑 /qa retry
```

---

## 9. 测试资产管理（长期沉淀）

测试用例 / 缺陷是**长期资产**，不是每次重生成的中间产物。

### 9.1 存储格式

* 用例：`qa/cases/<feature_id>/<case_id>.yml`，每条一个文件
* 缺陷：`qa/bugs/<bug_id>.yml`
* 历史：`qa/run/history.json`

### 9.2 用例 YAML Schema（Solo 精简版）

```yaml
id: TC-LOGIN-001
title: 用户使用正确账号密码登录成功
state: active            # active | review | stale | flaky | retired
feature_id: F-LOGIN
requirement_ids: [REQ-101]
level: system            # unit | integration | system | acceptance | smoke | performance | security
purpose: functional      # functional | exception | boundary | regression
priority: P0             # P0 | P1 | P2 | P3

preconditions:
  - 用户账号已存在

test_data:
  username: alice
  password: "${env:TEST_PASSWORD}"    # 机密字段必须用引用

steps:
  - 打开登录页
  - 输入账号密码
  - 点击登录

expected:
  - 跳转首页
  - 显示用户昵称

assertions:
  - selector: "[data-testid=username-display]"
    equals: "alice"

automation:
  status: implemented    # implemented | scaffolded | manual | not_applicable
  framework: playwright
  file: tests/system/login.spec.ts
  test_id: login_with_valid_credentials

targets:                 # 由 Adapter/Indexer 自动维护，Designer 不手填
  files: [src/pages/login.tsx, src/api/auth.ts]
  symbols: [LoginPage, authenticate]
  generated_by: adapter-web@0.5.0
  generated_at: 2026-06-16T10:00:00+08:00

regression_tags: [auth, smoke]
notes: ""
```

**字段计数**：18 个（相比 v2.1 的 30 个字段精简了 40%）。

### 9.3 增量演进规则

* 首次接入项目跑一次 L2/L3 建立用例库
* 之后只对**新需求 / 改动需求**做增量设计
* 用例的 `state` 必须显式管理：`stale` 用例不计入 PASS
* 用例下线必须改 `state: retired` + 注明原因，**不得直接删除文件**

### 9.4 targets 自动维护触发时机（P1-2）

`targets.{files, symbols}` 由 Adapter/Indexer 自动维护，Designer 不手填。三层触发：

| 触发方式 | 范围 | 频率 |
|---|---|---|
| **每次跑 `/qa` 时**（增量） | 仅 diff 涉及的文件对应的用例 | 每次 |
| **git rename / move 检测** | 受 rename 影响的用例 | 自动（每次执行前） |
| **手动 `/qa reindex`** | 全量重建 | 按需 |

#### 增量索引算法

```python
def smart_index_targets():
    diff_files = git_diff_name_only('HEAD~1', 'HEAD')
    
    # 步骤 1: 检测 rename
    renames = git_detect_renames('HEAD~1', 'HEAD')
    for old_path, new_path in renames:
        update_cases_targeting_file(old_path, new_path)
    
    # 步骤 2: 增量重新索引：仅涉及变更的用例
    for case in load_all_cases():
        if any(f in case.targets.files for f in diff_files):
            adapter.index_targets_for_case(case)
```

#### 全量重建（`/qa reindex`）

适用场景：
* 大规模重构后
* Adapter 升级后
* 用例库迁移后

```bash
/qa reindex                 # 全量
/qa reindex --feature LOGIN # 仅特定 feature
```

---

## 10. 推荐项目目录结构

```text
project/
  docs/
    requirements.md      # BMAD / spec-kit 产出
    acceptance_criteria.md
    design.md

  specs/
    feature-001/
      spec.md
      acceptance.feature

  qa/
    test_plan.md                    # 视图，可重新生成
    test_traceability_matrix.md     # 视图，由 cases 聚合生成
    final_test_report.md            # 视图
    release_gate_report.md          # 视图（仅 L3 生成）
    waivers.yml                     # 风险接受清单
    cases/                          # 权威源
      F-LOGIN/
        TC-LOGIN-001.yml
    bugs/                           # 权威源
      BUG-007.yml
    run/                            # 执行历史
      last.json
      history.json
      selection.md

  tests/
    unit/
    integration/
    system/
    acceptance/

  .qa-agent.yml                     # 项目级配置
  AGENTS.md
```

如果项目已有自己的目录结构，Agent 应在不破坏原结构的前提下适配（参见下一节）。

---

## 10A. 渐进式接入（已有项目）

个人项目通常已有 `tests/` 和配置。Agent 不允许"清空重写"，必须按以下顺序：

1. **盘点现状**：调用 Adapter `detect()` 识别现有测试
2. **协商映射**：把现有目录映射到测试层级，写入 `.qa-agent.yml`
3. **建立用例库**：在 `qa/cases/` 下生成对应 YAML，`automation.file` 指向**现有测试文件**
4. **增量改造**：不强制迁移现有测试，Adapter 按 `paths.layers:` 解析现有路径
5. **补齐缺口**：由用户决定补哪几层

**强制约束**：
* 禁止批量移动现有测试文件
* 禁止修改现有测试的断言（除非 orphan 且用户签字）
* `qa/` 目录引入不得破坏原有路径

---

## 11. 项目级配置 `.qa-agent.yml`（Solo 精简版）

每个项目根放一份，覆盖默认行为。**极简启动**：无配置时基于 BMAD/spec-kit 产物自动推断。

### 核心配置（10 行起步）

```yaml
project_type: web                   # web | backend | fullstack | mobile | desktop
language: typescript
frameworks:
  unit: vitest
  integration: vitest
  e2e: playwright

impact_analysis: gitnexus           # gitnexus（默认） | local

mode_limits:
  L0: 10
  L1: 80
  L2: 500
  L3: -1                            # 不限
  L4: 20
```

### 可选扩展

```yaml
coverage_thresholds:
  p0_line: 0.80
  p0_branch: 0.70

# 三角色模型选择（P1-1：Gatekeeper LLM 成本优化）
roles:
  designer_runner_model: claude-opus-4-7      # 默认 Opus（设计/执行需要高能力）
  gatekeeper_model: claude-haiku-4-5          # 默认 Haiku（判定逻辑较简单，省成本）
  gatekeeper_model_l3: claude-opus-4-7        # L3 发版门可选 Opus（更可靠）
  gatekeeper_skip_llm_for: [L0, L4]           # L0/L4 用算法判定，跳过 LLM
  gatekeeper_cache: true                      # 缓存判定结果（基于输入 hash）

mutation:
  enabled: auto                               # true | false | auto（默认 auto）
  scope: diff                                 # 仅 diff 涉及源文件
  enabled_modes: [L3]                         # 默认仅 L3
  on_tool_missing: skip                       # skip（默认） | warn | fail

flaky:
  retry_failed_only: true                     # 仅失败用例重跑
  retry_runs: 5
  block_as_pass: true                         # flaky 用例不计入 PASS

waivers:
  forbid_security_waiver_severity: [critical, high]
  max_expiry_days_low_severity: 7

# 修复轮触发模式（P0-6）
repair_loop:
  mode: manual                                # manual（默认） | auto-dev | auto-fixer
  per_case_attempts: 3
  total_rounds: 5

# 非功能测试分级（P0-5）：默认仅低成本项开启
nonfunctional:
  # 默认开启（成本极低，价值高）
  dependency_audit:
    enabled: true                             # 默认 true
    modes: [L3]
    
  static_security:
    enabled: true                             # 默认 true
    modes: [L3]
    tool: bandit                              # bandit（Python） | semgrep | eslint-plugin-security
  
  # 默认关闭（成本高，按需开启）
  dynamic_security_scan:
    enabled: false                            # 默认 false
    modes: [L3]
    tool: zap
    
  performance:
    enabled: false                            # 默认 false
    modes: [L3]
    tool: k6
    thresholds:
      p95_ms: 500
      qps_min: 100
      
  compatibility:
    enabled: false                            # 默认 false
    modes: [L3]
    matrix: [chromium, firefox]               # 可加 webkit, edge

production_guard:
  patterns:
    - "*.prod.example.com"
    - "*-production.*"

secrets:
  resolver: env                               # env | dotenv
  env_prefix: QA_

# 影响面分析深度调优（P0-2）
gitnexus:
  upstream_depth:
    L0: 2
    L1: 3
    L2: 3
    L3: -1
    L4: 3                                     # 动态语言项目可调高至 5

# GitNexus 不可用时降级策略（P2-4）
impact_fallback: prompt                       # prompt（默认） | local | fail
```

---

## 12. Agent 输入

Designer+Runner 必须读取：

* 需求文档（按 §12.1 自动发现）
* 架构设计（`docs/architecture.md` / `docs/design.md`，可选）
* 已有用例库（`qa/cases/`）
* 已有测试代码（`tests/`）
* BDD 文件（`*.feature`，若存在）

Gatekeeper 必须**独立读取**：

* 原始需求文档（不 trust Designer 的摘录）
* 用例库（`qa/cases/`）
* 执行结果（`qa/run/last.json`）
* Waivers（`qa/waivers.yml`）

### 12.1 需求文档自动发现规则（P0-1）

Agent 按以下优先级自动查找需求文档（从高到低）：

#### 优先级 1：显式配置（最高优先级）

`.qa-agent.yml` 中显式指定：

```yaml
requirements:
  primary: docs/requirements.md
  acceptance: docs/acceptance_criteria.md
  bdd_dir: features/
  spec_kit_dir: specs/
```

#### 优先级 2：约定路径自动扫描（默认行为）

按以下顺序尝试，**找到第一个就停止**：

1. `docs/requirements.md`
2. `docs/acceptance_criteria.md`
3. `specs/*/spec.md`（递归）
4. `specs/*/acceptance.feature`
5. `features/*.feature`
6. `.bmad/output/*.md`（BMAD 默认产出）
7. `REQUIREMENTS.md`（根目录）
8. `PRD.md`（根目录）
9. `README.md` 的 "Requirements" / "验收标准" 章节

#### 优先级 3：反向梳理兜底（§6.4）

如果上述路径都不存在 → 触发反向梳理流程：

1. Agent 扫描代码和测试
2. 推断需求条目
3. 生成 `docs/requirements_inferred.md`
4. **必须由用户签字确认**才能作为测试基线（`qa/signoff/requirements.signed`）

#### 特殊场景：BMAD / spec-kit

* BMAD 默认产出在 `.bmad/output/` → 自动识别
* spec-kit 默认产出在 `specs/` → 自动识别
* **Solo 项目零配置即可**（用户用 BMAD/spec-kit 时无需在 `.qa-agent.yml` 写需求路径）

#### 找不到时的行为

| 模式 | 行为 |
|---|---|
| L0 / L4 | 只跑受影响用例，不检查需求覆盖 |
| L1 / L2 | 警告"需求文档缺失"，允许继续（增量补用例模式） |
| L3 | **强制要求需求文档存在**，否则 BLOCKED |

---

## 13. Agent 输出

所有"报告"类文件均为**视图文件**，由结构化数据聚合生成；权威数据在 `qa/cases/`、`qa/bugs/`、`qa/run/` 中。

### 13.1 测试计划 `qa/test_plan.md`

* 测试目标、范围、风险分析
* 测试层级、优先级
* 自动化策略、手动测试策略
* 非功能测试策略
* 发布质量门标准

### 13.2 需求追踪矩阵 `qa/test_traceability_matrix.md`

| 需求编号 | 功能点 | 验收标准 | 测试用例 | 测试层级 | 自动化状态 | 当前状态 |
|---|---|---|---|---|---|---|

### 13.3 测试报告 `qa/final_test_report.md`

* 运行模式（L0–L4）
* 总数 / 通过 / 失败 / 跳过 / Flaky
* 未覆盖需求清单
* 高风险问题、阻塞问题
* **未能验证的事项**（Gatekeeper 必填）
* 是否建议通过验收 / 发布（仅 L3 生效）

### 13.4 缺陷报告（权威：`qa/bugs/<bug_id>.yml`，视图：`qa/bug_report.md`）

```yaml
id: BUG-007
title: 登录后昵称未渲染
state: open                # open | fixed | verified | wont_fix
severity: high             # blocker | high | medium | low
priority: P1
related_cases: [TC-LOGIN-001]
related_requirements: [REQ-101]
repro_steps: [...]
expected: ...
actual: ...
logs: ...
suspected_cause: ...
needs_regression: true
regression_scope_hint: [F-LOGIN, smoke]
created_at: 2026-06-16T10:00:00+08:00
```

### 13.5 发布质量门报告 `qa/release_gate_report.md`（仅 L3）

结论必须是以下之一：

```text
PASS              允许进入验收或发布
CONDITIONAL PASS  允许继续，但存在非阻塞问题（必须列出 waiver 引用）
FAIL              不允许发布，存在阻塞问题
BLOCKED           测试无法完成，需要补充环境、需求或配置
```

### 13.6 智能下一步提示（P2-3）

每次 `/qa` 执行完毕后，终端必须输出"建议下一步"，引导用户工作流。

#### PASS 时的提示

```text
✅ L1 完成：登录功能测试通过

执行统计：
  总数 8 / 通过 8 / 失败 0
  耗时：2 分 30 秒

建议下一步：
  ✓ 继续开发其他功能 → 完成后运行 /qa feature <功能名>
  ✓ 模块开发完成 → 运行 /qa module 订单 验证模块完整性
  ✓ 准备发版 → 运行 /qa release 进入发版质量门

详细报告：qa/final_test_report.md
```

#### FAIL 时的提示

```text
❌ L1 失败：登录功能存在 2 个问题

失败用例：
  - TC-LOGIN-003: 登录后昵称未渲染 (BUG-008)
    位置：src/api/auth.ts:42
  - TC-LOGIN-004: 登录超时 (BUG-009)
    位置：src/api/auth.ts:67

建议操作：
  1. 查看缺陷详情：qa/bugs/BUG-008.yml、BUG-009.yml
  2. 修复代码后运行：/qa retry 重跑相同范围
  3. 单独验证某个 bug：/qa bugfix BUG-008
  4. 需要调试时：/qa debug BUG-008 查看详细日志
```

#### BLOCKED 时的提示

```text
⚠️ L3 阻塞：环境/需求问题导致无法完成

阻塞原因：
  - 集成测试：数据库连接失败（环境失败）
  - 需求未签字：docs/requirements_inferred.md 缺少 approval

建议操作：
  1. 启动数据库：docker-compose up -d postgres
  2. 签字确认反向梳理产物：echo "approved" > qa/signoff/requirements.signed
  3. 然后运行：/qa resume 从中断处继续
```

---

## 14. 平台适配器接口契约

所有 Adapter 必须实现下列方法。Core 不假设接口"行为统一"，而是按 **capabilities 能力声明**决策。

```text
interface TestAdapter:
  detect() -> ProjectFingerprint
      # 返回项目类型、语言、框架、运行命令、capabilities

  scaffold(plan) -> void
      # 创建/补齐测试目录、配置

  generate(case_yaml) -> AutomationFile
      # 生成可执行测试脚本

  index_targets() -> TargetIndex
      # 自动维护用例 targets.{files,symbols}

  run(selection, mode) -> RunResult
      # 执行用例集合

  parse_report(raw_output) -> NormalizedResult
      # 归一化结果

  collect_artifacts(run_id) -> ArtifactBundle
      # 收集失败截图、日志、覆盖率

  classify_failure(case_result) -> FailureKind
      # 区分 env_failure / test_failure
```

### 14.1 Capabilities 能力声明矩阵

每个 Adapter 的 `detect()` 必须返回一份能力位声明：

| 能力位 | 含义 | Core 行为（false 时） |
|---|---|---|
| `headless` | 是否支持无头执行 | E2E/UI 类用例转 manual |
| `parallel` | 是否支持并行执行 | 串行回退 |
| `coverage` | 是否能产出覆盖率 | 跳过覆盖率门槛 |
| `mutation` | 是否支持 mutation testing | 跳过 mutation 抽样 |
| `screenshot` | 失败截图能力 | 不强制要求截图 |

### 14.2 Web Adapter

* 推荐工具：Playwright、Vitest、Jest
* 选择器优先 `data-testid` / `aria-role`；缺失时输出 ImprovementHint（不阻断）

### 14.3 Backend Adapter

* 推荐工具：pytest、JUnit、go test
* 集成测试优先使用 Testcontainers / docker-compose

### 14.4 Generic Adapter（P0-4：兜底实现）

当 auto_detect 失败（项目不在 web/backend/mobile/desktop/game 之列）时，使用通用 Adapter 兜底。

#### 适用场景

* Rust CLI 工具（`cargo test`）
* Go 微服务非标准布局
* C/C++ 嵌入式（`make test`）
* LaTeX/文档生成器
* 任何"有现成测试命令、但没有专用 Adapter"的项目

#### 启用方式

`.qa-agent.yml` 中显式指定：

```yaml
project_type: generic
language: rust                    # 任意标识
test_command: cargo test          # 必填：测试执行命令
test_output_format: tap           # tap | junit_xml | plain
build_command: cargo build        # 可选
lint_command: cargo clippy        # 可选

# 用例 YAML 中的 automation.framework = 'cargo'
# Generic Adapter 不生成脚本，只执行现有测试
```

#### Capabilities（自动声明）

| 能力位 | Generic 默认 | 说明 |
|---|---|---|
| `headless` | true | 通常 CLI 工具默认无头 |
| `parallel` | false | 不并行（保守） |
| `coverage` | false | 不要求覆盖率 |
| `mutation` | false | 不支持 mutation |
| `screenshot` | false | 无 GUI |

#### 限制

* ❌ 不能自动生成测试脚本（`automation.status` 仅 `manual` / `scaffolded`）
* ❌ 不能自动维护 `targets`（需要人工填写或回退到 local 影响面）
* ❌ 不能 `classify_failure`（全部视为 `test`）
* ✅ 可以执行现有测试
* ✅ 可以解析输出（支持 TAP / JUnit XML / 纯文本）
* ✅ 可以收集基本产物（stdout/stderr 日志）

#### 报告标注

使用 Generic Adapter 时，所有报告必须在头部加显著提示：

```markdown
> ℹ️ 本项目使用 Generic Adapter
> 限制：测试脚本由人工维护、影响面分析降级为 local、无 mutation/覆盖率
> 建议：长期接入时考虑开发专用 Adapter
```

---

## 15. 测试层级定义

### 15.1 单元测试

目标：验证单个函数、类、组件、状态机、纯逻辑。
特点：快、稳定、易定位，应频繁执行。

### 15.2 集成测试

目标：验证多个模块、组件、服务之间协作。
适合：数据库读写、API 调用、消息队列、缓存、鉴权集成。

### 15.3 系统测试

目标：验证整个系统或应用完整运行。
适合：端到端流程、完整业务场景、真实环境配置。

### 15.4 验收测试

目标：验证是否满足需求和验收标准。
适合：用户故事验收、BDD 场景、发布前质量门。

### 15.5 回归测试

回归是**测试目的**，不是层级；范围由影响面分析（第 8 章）决定。

### 15.6 非功能测试分级（P0-5）

非功能测试按"成本/价值比"分两档，**默认低成本档开启、高成本档关闭**。

#### 默认开启（成本低、价值高）

| 类型 | 工具示例 | 成本 | 价值 |
|---|---|---|---|
| **依赖漏洞扫描** | `npm audit` / `pip-audit` / `cargo audit` | 5–30 秒 | 高（捕获已公开 CVE） |
| **静态安全扫描** | `bandit` / `semgrep` / `eslint-plugin-security` | 1–3 分钟 | 中（捕获代码层常见漏洞） |

这两项**默认在 L3 跑**。

#### 默认关闭（成本高、按需开启）

| 类型 | 工具示例 | 成本 | 适用场景 |
|---|---|---|---|
| **动态安全扫描** | OWASP ZAP | 30 分钟+ | 公开 Web 服务、含敏感数据 |
| **性能压测** | k6 / Locust / JMeter | 1 小时+ | 高并发 API、用户量大的项目 |
| **兼容性矩阵** | Playwright 多浏览器 | 30 分钟+ | 公开 Web/桌面、用户跨平台 |

这三项**默认关闭**，需要在 `.qa-agent.yml` 显式 `enabled: true` 或命令行 `--with-*` 临时开启。

#### 命令行临时开启

```bash
# 默认 L3：功能 + 依赖漏洞 + 静态安全（10–30 分钟）
/qa release

# 临时开启动态安全扫描
/qa release --with-dynamic-security

# 临时开启性能测试
/qa release --with-performance

# 临时开启兼容性矩阵
/qa release --with-compatibility

# 全开（最完整，1–2 小时）
/qa release --with-all-nonfunctional
```

#### 与 L3 维度切片的区别

* **L3 维度切片**（`--skip`）：减少 L3 执行的维度（适用于"我已配置但本次想跳过"）
* **--with-* 临时开启**：增加 L3 执行的维度（适用于"默认关闭但本次想开"）

两者可同时使用：

```bash
/qa release --with-performance --skip compatibility
```

#### 执行环境隔离要求

* 动态安全扫描：**只允许在隔离环境**运行，命中生产标识立即中止
* 性能压测：建议独立环境，避免影响其他服务
* 静态安全 / 依赖审计：可在任何环境（仅扫描代码或依赖文件）

---

## 16. 测试环境与数据策略

### 16.1 环境

* 单元测试：进程内，不依赖外部服务
* 集成测试：默认使用 Testcontainers / docker-compose
* 系统/E2E 测试：本机或沙箱，禁止指向生产
* 凭据：通过 `.env` 或引用语法注入；Agent 不得把凭据写入用例 YAML

### 16.2 测试数据

* 每条用例自带或引用独立测试数据
* 数据库测试使用独立 schema / 事务回滚
* 不允许用例之间通过执行顺序传递状态

### 16.3 生产保护红线

* Agent 执行前检查目标 endpoint / DSN，包含生产标识时**直接中止**
* 可在 `.qa-agent.yml` 配置 `production_guard.patterns`

---

## 17. BDD 支持

Agent 支持 BDD，但不强制。

* 项目已有 BDD/Gherkin → 读取并生成对应用例 YAML
* 项目无 BDD → 可将验收标准转换为 Gherkin 草稿
* BDD 文档不是终点，必须继续生成用例与自动化映射

---

## 18. Agent 工作流

### 18.1 引导式初始化 `/qa init`（P2-1）

首次接入项目时运行 `/qa init`，零配置体验：

```text
$ /qa init

[Agent] 检测到这是首次使用 QA Agent。正在初始化...

[Agent] 扫描项目...
  ✓ 检测到 package.json
  ✓ 检测到 TypeScript（tsconfig.json）
  ✓ 检测到 Playwright（playwright.config.ts）
  ✓ 检测到 Vitest（vitest.config.ts）
  ✓ 检测到 GitNexus MCP 工具
  ✓ 检测到需求文档：docs/requirements.md
  ✓ 检测到 BMAD 产出：.bmad/output/
  ✓ 检测到 8 个已有 vitest 测试 / 3 个 Playwright 测试

[Agent] 已生成 .qa-agent.yml 草稿：

  project_type: web
  language: typescript
  frameworks:
    unit: vitest
    e2e: playwright
  impact_analysis: gitnexus
  
  paths:
    layers:
      "src/__tests__": unit
      "tests/system": system
      "e2e": acceptance

[Agent] 已生成 qa/ 目录结构（cases/ bugs/ run/ 等）

[Agent] 接入路径：渐进式
  - 现有 11 个测试已登记为 orphan（qa/orphan_tests.md）
  - 你可以选择：
    a) 先把现有测试逐个映射为用例（推荐）
    b) 直接基于需求生成新用例库
    c) 稍后处理

[Agent] 下一步建议：
  /qa feature 用户登录    # 生成第一个 feature 的测试
  /qa guide               # 查看完整使用指南
  /qa status              # 查看当前测试覆盖状态

是否立即运行一次完整项目扫描（L2）以建立用例库？(yes / no / 稍后)：
```

#### 关键设计

* **不要求用户理解 5 档模式**——只展示"试试 /qa feature ..."
* **自动生成配置草稿**——用户复审而非空白填写
* **承认现有测试**——orphan 列表，不强制重写
* **明确"下一步"**——避免无所适从

#### 失败检测时的引导

如果 detect 失败（项目类型未知）：

```text
[Agent] ⚠️ 无法识别项目类型。可能原因：
  - 项目语言/框架未在内置 Adapter 列表
  - 缺少标识文件（package.json / pyproject.toml / Cargo.toml ...）

可选操作：
  1. 使用 Generic Adapter（手动指定测试命令）：/qa init --generic
  2. 手动选择项目类型：/qa init --type web
  3. 查看支持列表：/qa adapters

选择 1-3：_
```

### 18.2 L3 完整流程

```text
[Designer+Runner]
  读取需求 / 设计 / 验收标准
  生成或更新用例 YAML
  生成 test_plan.md / 矩阵
  调用 Adapter.generate() 补齐自动化脚本
  调用影响面分析 → selection.md（L3 全量）
  调用 Adapter.run(selection, mode=L3)
  收集失败 → 写入 qa/bugs/
  flaky 检测（仅失败用例重跑）
  抽样 mutation testing（仅 diff）
  非功能测试（按 §15.6 配置）
    ↓
[失败 → 修复轮（受 5.7 上限保护）]
  按 repair_loop.mode：
    - manual: 报告退出，等用户修后跑 /qa retry
    - auto-dev: 调用 Dev Agent 修 → Runner 重跑
    - auto-fixer: QA-Fixer 修 → Runner 重跑
  最多 5 轮，超限 → BLOCKED
    ↓
[Gatekeeper]
  独立从原始需求重新摘录（参见 §3.3）
  LLM 校验 requirement_ids 关联（不一致标 review）
  选回归集（基于本轮 fixed bug）
  Runner 跑回归
  校验：P0 通过？覆盖率达标？无 active flaky？manual 用例签字？安全测试无失败？waivers 无过期？
  输出 release_gate_report.md：PASS / CONDITIONAL PASS / FAIL / BLOCKED
  必填："未能验证的事项"
```

### 18.3 L0 / L1 / L2 / L4 简化分支（P0-7：所有模式都有修复轮）

| 模式 | Designer 阶段 | Runner 阶段 | 修复轮 | Gatekeeper 阶段 |
|---|---|---|---|---|
| **L0** | 跳过 | 受影响单测 + 关联冒烟 | ✅（受 5 轮上限） | 算法判定（不调 LLM） |
| **L1** | 增量补该功能用例 | 该功能全部分层 + 邻接回归 | ✅（受 5 轮上限） | LLM 判定（功能级） |
| **L2** | 复核该模块所有用例 | 该模块全部 + 跨模块集成 + mutation 抽样 + 对抗式 review | ✅（受 5 轮上限） | LLM 判定（模块级） |
| **L4** | 跳过 | 缺陷复现用例 + 影响面回归 | ✅（受 5 轮上限） | 算法判定 + 出现新失败时升级 LLM |

#### 修复轮在所有模式下都生效

```text
任何模式失败时：
  ↓
按 repair_loop.mode 处理：
  
[manual 模式（默认）]
  ↓
  Agent 输出失败报告 + 退出
  你修代码
  你跑 /qa retry → 重跑相同 selection
  
[auto-dev 模式]
  ↓
  调用 Dev Agent，传入 bug YAML
  Dev Agent 修代码
  Runner 自动重跑（同一 /qa 命令内）
  最多 5 轮
  
[auto-fixer 模式]
  ↓
  QA-Fixer 修代码（高风险，不推荐）
  Runner 自动重跑
  最多 5 轮
```

**关键约束**：

* 修复轮仅在同一次 `/qa` 命令的 auto-* 模式下自动循环
* manual 模式下，每次 `/qa retry` 都算单独命令（但 selection 复用）
* 所有 5 个模式（L0/L1/L2/L3/L4）都受 5 轮上限保护

### 18.4 模式切换的强制提示

每次接到指令时，打印：

```text
将以 [L?] 模式执行
设计阶段：[新增/复核 N 条用例 | 跳过]
执行阶段：[选中 M 条用例（P0=a, P1=b, P2=c）]
影响面来源：[GitNexus | local]
非功能测试：[启用 / 跳过]
修复轮模式：[manual | auto-dev | auto-fixer]
单次上限：[X 条]
是否继续？(yes / 修改 / 取消)
```

用户回复 yes 才执行。

### 18.5 检查点恢复 `/qa resume`（P1-4）

L3 完整跑可能需要 30 分钟–2 小时（启用全部非功能后），中途可能：

* 笔记本休眠 → Agent 进程被 kill
* 网络断了 → LLM 调用失败
* 用户按 Ctrl+C 想暂停

#### 检查点机制

L3 流程划分为 8 个 phase，每个 phase 完成后写检查点到 `qa/run/last.json`：

```text
Phase 1: Designer 生成用例     → checkpoint #1
Phase 2: Runner 单元测试       → checkpoint #2
Phase 3: Runner 集成测试       → checkpoint #3
Phase 4: Runner 系统测试       → checkpoint #4
Phase 5: Runner 验收测试       → checkpoint #5
Phase 6: 非功能测试            → checkpoint #6
Phase 7: Mutation              → checkpoint #7
Phase 8: Gatekeeper 判定       → 完成
```

#### 中断时的行为

```text
用户按 Ctrl+C：

[Agent] 中断信号收到，正在保存检查点...
[Agent] 已保存到 checkpoint #3 (集成测试完成)
[Agent] qa/run/last.json 已更新（status: paused）
[Agent] 下次运行 /qa resume 可从此处继续
```

#### 恢复执行

```text
$ /qa resume

[Agent] 检测到未完成的 L3 运行（run_20260616_100000）
[Agent] 已完成阶段：
  ✓ Phase 1: Designer（8 用例）
  ✓ Phase 2: 单元测试（12 PASS / 0 FAIL）
  ✓ Phase 3: 集成测试（8 PASS / 0 FAIL）

[Agent] 待执行阶段：
  ○ Phase 4: 系统测试（24 用例待跑）
  ○ Phase 5: 验收测试
  ○ Phase 6: 非功能测试
  ○ Phase 7: Mutation
  ○ Phase 8: Gatekeeper 判定

是否继续？(yes / 重新开始 / 取消)：
```

#### 恢复的限制

* 仅 L3 支持检查点恢复（其他模式耗时短，重跑成本低）
* 恢复时检测 git diff 是否变化：
  * 未变 → 直接续跑
  * 已变 → 警告并要求用户确认（可能影响已完成 phase 的有效性）
* 24 小时内的检查点有效，超时自动失效（避免代码大幅变化后续跑误判）

---

## 19. 测试执行顺序与失败分类

### 19.1 执行顺序

```text
1. 静态检查 / Lint
2. 单元测试
3. 集成测试
4. 冒烟测试
5. 系统测试
6. 验收测试
7. 非功能测试（仅 L3）
8. 回归测试（针对修复轮）
```

### 19.2 失败分类与阻断策略

不能把"层级全部失败"一律当作代码问题。Runner 必须分类：

| 类别 | 触发特征 | 阻断行为 |
|---|---|---|
| **环境失败** | 依赖未装、端口占用、容器启动失败、数据库连不上 | **不阻断后续层**；当前层标 `BLOCKED` |
| **测试失败** | 测试代码本身抛异常或断言失败 | 仅当该层 ≥ 80% 用例 fail 时停止下层 |

Adapter `parse_report()` 必须把每条 fail 的 `failure_kind` 归一为 `env | test | unknown`。

---

## 20. 优先级规则

### P0（必须自动化，除非 not_applicable）

应用启动、登录/核心入口、核心业务主流程、数据保存、支付/订单/权限、关键状态流转、阻塞性 bug 回归。

### P1（应尽量自动化）

常用功能、重要异常路径、重要边界条件、主要模块集成。

### P2（可自动化也可手动）

低频功能、视觉细节、辅助功能。

### P3（通常手动或低优先级）

罕见场景、探索性测试。

---

## 21. 与开发 Agent 的交互协议

```text
Dev Agent 开发功能 → 完成
  ↓
触发 L1：QA-Designer+Runner 生成/更新用例 + 执行 + Gatekeeper 判定
  ↓ 失败
QA 输出缺陷 → qa/bugs/*.yml
  ↓
Dev Agent 读取 bugs/ 并修复
  ↓
触发 L4：QA-Runner 验证修复 + Gatekeeper 决定 verified
  ↓
模块完成 → 触发 L2
  ↓
发版前 → 触发 L3 → release_gate_report.md
```

**强制约束**：

* Dev Agent 修复时不得直接修改 `qa/cases/`（除非用例本身错误）
* Dev Agent 不得在 `bugs/<id>.yml` 中把状态从 `open` 改到 `verified`，verified 只能由 Gatekeeper 写入

---

## 22. AGENTS.md 推荐规则（项目级红线汇总）

```markdown
# QA Gate Rules（v3.0 Solo Edition）

## 触发

- 单点小改：/qa L0
- 一个功能完成：/qa feature <name>（L1）
- 一个模块完成：/qa module <name>（L2）
- 修复缺陷后：/qa bugfix <bug_id>（L4）
- 发版前：/qa release（L3，唯一发版凭据）

## 禁止

1. 未运行测试就标记完成
2. 删除失败测试来伪造通过
3. 降低断言标准来伪造通过
4. 跳过 P0 测试
5. 只运行程序不做断言
6. 只靠手动观察或 AI 口头判断宣布通过
7. 修复 bug 后不执行回归测试
8. 用 L0 / L1 / L4 的"PASS"作为发版凭据
9. Agent 自行降档
10. Agent 自行缩减用户提供的执行集
11. 直接删除用例文件（必须改 state: retired）
12. 把状态 open → verified（必须由 Gatekeeper 写入）

## 质量门（仅 L3 适用）

- 全部 P0 用例通过；否则 FAIL
- 核心冒烟测试通过；否则 FAIL
- 项目可启动；否则 BLOCKED
- final_test_report、release_gate_report 齐备；否则 BLOCKED
- 待人工签字的 manual 用例已签字；否则 BLOCKED
- waivers.yml 中无过期项；否则 BLOCKED
- 覆盖率 / mutation 达标；否则 CONDITIONAL PASS 或 FAIL
```

---

## 23. Agent 创建提示词

```text
你现在要创建一个名为 AI Test Engineer 的 Agent（Solo Edition）。

它由两个角色组成：
- Designer+Runner：测试设计 + 脚本生成 + 执行 + 收集失败（同一上下文）
- Gatekeeper：回归选择 + 判定 PASS/FAIL/BLOCKED（独立上下文）

它必须支持 5 档运行模式：
- L0 Spot / L1 Feature / L2 Module / L3 Release / L4 Bugfix
模式由用户显式指令触发，不得自行降档；L3 是唯一发版依据。

它必须遵守的红线（见文档第 5.5、22 章）：
- 不得伪造、不得降档、不得缩减执行集、不得删除失败测试、不得绕过断言、不得在生产环境运行、只有 Gatekeeper 能 verified。

影响面分析默认依赖 GitNexus，调用失败时不得静默回退，必须报告并请示。

预算：
- 不设 token 上限
- 单次执行用例数上限按模式，超限熔断暂停请示用户

它采用通用核心 + 平台适配器结构：
- qa-core：流程、模式、影响面、预算、对抗式 review、决策
- qa-web / qa-backend：实现 detect / scaffold / generate / run / parse_report / collect_artifacts / index_targets / classify_failure

请根据当前项目 .qa-agent.yml 自动选择测试框架并创建所需目录、模板、脚本和执行流程。
如 .qa-agent.yml 不存在，先生成草稿请用户确认，再继续。
```

---

## 24. 路线图：MVP → v0.5 → v1.0

### 24.1 MVP（v0.1）—— 两角色、L1/L4、Web 或 Backend 之一

目标：先把闭环跑通。

* 两角色（Designer+Runner 合并 / Gatekeeper 独立）
* 仅支持 L1 / L4 两档
* 影响面用 local 模式即可
* 用例 YAML 精简版（18 字段）
* 适配器：**Web 或 Backend 二选一**完整实现
* 红线（5.5、5.7）必须就位
* 自检清单 8 项

完成判据：

```text
对一个真实小项目（Web 或 Backend）：
  能在 L1 模式下生成/复用用例库 + 自动化脚本 + 通过/失败结论
  能在 L4 模式下验证一次修复 + 影响面回归
  红线触发可被检出
```

### 24.2 v0.5 —— L0/L2 + GitNexus 默认

* 增加 L0、L2 模式
* 影响面默认 GitNexus，缺失时按 8.4 处理
* 增加对抗式 review（仅 L2）
* 用例 `targets` 由 indexer 自动产出
* 适配器：**Web + Backend 两个完整实现**

### 24.3 v1.0 —— L3 + 非功能

* 新增 L3 模式与发布质量门报告
* 完整非功能测试支持：性能、安全、兼容
* Flaky 检测（仅失败用例）、mutation（仅 L3 + 仅 diff）正式生效
* Waiver 流程上线
* 适配器：**Web + Backend 完整、Mobile/Desktop/Game stub**

---

## 25. 反伪造检查清单（Agent 自检）

每次 QA 流程结束前，Agent **必须**逐项自检：

```text
[ ] 所有 P0 用例已实际执行（不是被 skip）
[ ] 所有 fail 用例都生成了 qa/bugs/<id>.yml
[ ] 没有用例文件被删除（retired 不算删除）
[ ] 没有断言被弱化
[ ] flaky 用例未被计入 PASS
[ ] 安全用例（critical/high）无 waiver
[ ] waivers.yml 无过期项
[ ] 运行模式已声明，且与触发指令一致；未自行降档
```

任何一项未通过 → 报告状态不得为 PASS。

---

## 26. 最终目标

把 AI 开发从：

```text
AI 写完代码 → 看起来能跑 → 口头宣布完成
```

升级为：

```text
AI 写完代码
↓
按场景选择运行模式（L0–L4）
↓
Designer+Runner 增量更新用例库 + 执行
↓
Gatekeeper 独立判定 PASS / FAIL / BLOCKED
↓
仅 L3 输出发布质量门结论
↓
允许或拒绝验收 / 发布
```

关键词：**结构化资产 + 影响面裁剪 + 独立判定 + 分档运行**。

---

## 附录 A. 团队协作扩展（Solo 项目不需要）

以下机制在 v3.0 Solo Edition 中**已删除**，仅保留说明供企业团队参考。

### A.1 三角色严格独立上下文

企业版 v2.1 要求 Designer / Runner / Gatekeeper 三个角色完全独立上下文，避免确认偏差。Solo Edition 简化为 Designer+Runner 合并 + Gatekeeper 独立。

### A.2 异质模型（gatekeeper_model）

企业版允许配置 `gatekeeper_model: claude-sonnet-4-6`，让 Gatekeeper 使用不同厂商或档位的模型，降低共享盲区。Solo Edition 删除此配置，统一使用同一模型。

### A.3 Commit 作者白名单 + approved_by 校验

企业版 Waiver 流程要求：

* `waivers.yml` 中每条 waiver 必须有 `approved_by: email` 字段
* email 必须在 `.qa-agent.yml` 的 `waivers.allowed_approvers` 白名单内
* 或与 `git log` 中的 commit 作者匹配

Solo Edition 删除白名单和 `approved_by` 字段，改为标记 + 过期时间。

### A.4 KPI 数据回流通道

企业版要求建立 `qa/feedback/` 目录：

* `escaped_bugs/*.yml`：验收/生产中发现的缺陷
* `false_positives/*.yml`：QA 报为 fail 实为测试代码问题

用于计算缺陷逃逸率和误报率。Solo Edition 删除此强制要求，个人项目通常没有运维反馈通道。

### A.5 段落语义指纹（SimHash / MinHash）

企业版用 SimHash 对需求段落生成语义指纹，避免排版微调引发大批用例标 stale。Solo Edition 改为 LLM 直接比对（成本可接受）。

### A.6 人/Agent 触发区分 + auto_confirm

企业版区分：

* 人触发（对话中 `/qa ...`）：必须 yes 才执行
* Agent 触发（Dev Agent 交接文件）：按 `auto_confirm.modes` 白名单决定是否自动执行

Solo Edition 删除此配置，统一为"打印摘要 → 等 yes"。

---

**文档结束**
