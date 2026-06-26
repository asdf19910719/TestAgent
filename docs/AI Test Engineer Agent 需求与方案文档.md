# AI Test Engineer Agent 需求与方案文档

> 版本：v2.1
> 修订日期：2026-06-16
> 文档定位：提供给 Claude 等编排 Agent，用于实施"AI 测试工程师"项目的契约级规范
> 适用范围：通用，覆盖 Web / 后端 / 移动 / 桌面 / 游戏 / 工具类项目
> **配套文件**：`docs/implementation_guide.md`（v2.1 新增）—— 本规范说"做什么 / 不做什么"，实现指南说"怎么做"。两者必须同时落实。

---

## 0. 修订摘要

### 0.1 v2.0 相对 v1.0

* **拆分单 Agent → 三角色**（QA-Designer / QA-Runner / QA-Gatekeeper），降低确认偏差与上下文过载。
* **新增 5 档运行模式 L0–L4**，按变更范围与场景裁剪测试范围，避免每次改动都跑全流程。
* **测试用例改为结构化资产**（YAML 长期存储 + Markdown 视图），增量演进而非重复生成。
* **影响面分析默认基于 CodeGraph**，仅在用户显式禁用时回退到 diff + 用例索引。
* **新增非功能性测试落地规范**（性能 / 安全 / 兼容）。
* **新增测试代码自身质量保证**（覆盖率门槛、mutation 抽样、对抗式 review、flaky 检测）。
* **新增失败循环防护**（重试上限、自修复轮数上限、强制升级人工）。
* **新增 Waiver / 风险接受机制**，必须人工签字。
* **新增需求变更与用例同步机制**。
* **新增 Agent 自身 KPI**。
* **新增平台适配器接口契约**。
* **本版本不涉及 CI、Issue Tracker、PR 评论、仪表盘**——所有产物以本地文件为权威来源。
* **预算控制**：不设 token 上限，仅设单次执行用例数上限并提供熔断确认。

### 0.2 v2.1 相对 v2.0（按反馈收敛"含糊点 → 协议级约束"）

* **三角色偏置缓解强化**：Gatekeeper 必须**独立从原始需求摘录条款**，禁止 trust Designer 的关联关系（3.3）。
* **需求绑定改为段落语义指纹**：`requirement_hash` 改为规范化文本 hash + LLM 相似度比对 fallback（5.9 / 9.2）。
* **mutation / flaky 成本收敛**：mutation 仅对**本次 diff 涉及代码**抽样、仅 L3 全量；flaky **只对失败用例隔离重跑**，通过用例由 `history.json` 滚动统计（5.6 / 11）。
* **L3 允许"维度切片"**：可显式跳过非功能/兼容某些维度，但必须在 `release_gate_report` 登记"未覆盖维度"，避免"全有或全无"导致的私下绕规则（7.1 / 18.2）。
* **CodeGraph 漏选兜底**：以 `feature_id` / `regression_tags` 为补集，覆盖动态语言、跨进程、配置驱动调用看不到的情形（8.5）。
* **触发场景区分**：人触发需用户确认；Agent / 批处理触发可走 `auto_confirm`；自动场景下 Agent 仍不得降档（5.5 / 18.4）。
* **反向梳理签字落地**：通过 commit 作者白名单 + `qa/signoff/*.yml` 外部签批文件实现机器可强制（6.4）。
* **安全用例 waiver 分级**：critical/high 不允许 waiver，medium/low 允许有限 waiver（必须附 PoC 不可达证据 + 更短过期）（5.8）。
* **KPI 数据回流接口**：明确 `qa/feedback/` 目录为外部反馈来源（生产逃逸、误报标注），无该目录时 KPI 显式标"数据不足"而非 0（2.1）。
* **token 表述修正**：从"不设上限"改为"成本不作为缩减执行集的理由"（context window 物理上限仍存在）（5.5 / 7.4）。
* **mode_limits 增加 `max_minutes` 时间预算**：与用例数上限并列，先到先触发熔断（11）。
* **Adapter 加 `capabilities` 能力声明矩阵**：Core 按能力位决策，不再假设所有 Adapter 行为统一（14）。
* **失败分类**：区分"测试失败"与"环境/setup 失败"，后者升级 BLOCKED 而不是 FAIL，且不阻断下层（19.2）。
* **测试数据加 secret 引用语法**：`${env:VAR}` / `!secret path.key`，禁止凭据硬编码进 YAML 或生成脚本（9.2 / 16.1）。
* **`data-testid` 强制改为软提示**：缺失时输出 `ImprovementHint` 给 Dev Agent，不再死禁（14.1）。
* **新增"渐进式接入"章节**：覆盖已有 `tests/` / 已有测试配置项目的轻量迁移路径（11.2 新增）。
* **路线图收敛**：v1.0 收缩为 Web + Backend 完整 + 其他三个 Adapter stub；移动/桌面/游戏完整版推到 v1.5 / v2.0（24.3 / 24.4）。
* **大量"必须……"含糊条款迁出**：协议级实现细节（session 划分、文件锁、CLI 输出格式、secret 解析、capabilities 矩阵、mutation 抽样算法、flaky 重跑算法、签批文件 schema、auto_confirm 配置）统一移入 `implementation_guide.md`。

---

## 1. 背景

当前 AI 编程工具已经能够较快完成项目开发，但经常出现以下问题：

* AI 完成功能后没有系统化测试。
* 没有测试工程师视角的完整测试用例。
* 没有按照单元测试、集成测试、系统测试、验收测试进行分层验证。
* 没有自动化执行测试用例。
* 没有测试报告。
* 测试失败后没有标准缺陷报告。
* 修复后没有回归测试。
* AI 经常"功能看起来能跑"就宣布完成，但缺少可靠交付证据。
* 单一开发 Agent 自己开发、自己验收，容易产生确认偏差。

因此需要创建一个独立的 **AI Test Engineer Agent**，专门负责开发完成后的测试设计、自动化测试、测试执行、缺陷反馈、修复验证和回归测试闭环。

## 2. Agent 总目标

创建一个通用的 AI 测试工程师 Agent，用于在软件开发完成后执行完整 QA 流程：

```text
需求 / 规格 / 设计文档 / 当前代码
↓
测试需求分析
↓
生成（或增量更新）完整测试用例
↓
按测试层级分类
↓
生成自动化测试脚本
↓
按运行模式裁剪执行范围
↓
执行测试
↓
输出测试报告
↓
根据失败结果生成缺陷报告
↓
修复（自行或交由 Dev Agent）
↓
基于影响面执行回归测试
↓
输出最终质量门结论
```

该 Agent 的根本目标不是"写更多测试代码"，而是建立一个**可验证、可重复、可回归、可交付**的测试闭环。

### 2.1 Agent 自身 KPI

Agent 实现后必须能够自评以下指标，作为长期演进依据：

| 指标 | 含义 | 阈值建议 | 数据来源 |
|---|---|---|---|
| 缺陷逃逸率 | 验收后被发现的缺陷数 / 总缺陷数 | < 10% | `qa/feedback/escaped/*.yml` |
| 误报率 | 报为 FAIL 实际为测试代码问题的占比 | < 15% | `qa/feedback/false_positive/*.yml` |
| P0 自动化覆盖率 | 已自动化 P0 用例 / 总 P0 用例 | ≥ 95% | 用例库聚合 |
| 用例有效性 | mutation 抽样中被用例捕获的变异占比 | ≥ 60% | mutation 工具产物 |
| Flaky 率 | 重复执行结果不一致的用例占比 | < 3% | `qa/run/history.json` |

**KPI 数据回流接口**：

* `qa/feedback/escaped/<id>.yml`：人工或运维标注的"逃逸到生产/验收的缺陷"。
* `qa/feedback/false_positive/<id>.yml`：人工标注的"测试代码错导致的 FAIL"。
* 这两个目录由人或外部系统写入，**Agent 只读**；缺失时 KPI 在报告中显式标注 `数据不足` 而不是按 0 计算。
* 详细 schema 见实现指南。

KPI 不达标时，Agent 应主动在最终报告中标注，但不得自行降低阈值。

---

## 3. Agent 角色定位与拆分

为避免单一 Agent 既当运动员又当裁判、上下文严重过载，本方案将原"6 合 1"角色拆分为三个协作子角色。它们可以由同一个底层模型驱动，但**必须在不同的对话上下文/不同的提示词中独立运行**，并通过文件交接结果。

```text
┌────────────────────────────────────────────────────────┐
│                    QA-Designer                          │
│ 测试架构师 + 高级测试工程师                             │
│ 职责：风险分析、测试计划、用例设计、追踪矩阵、自动化映射│
│ 产物：qa/test_plan.md、qa/cases/*.yml、矩阵            │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│                    QA-Runner                            │
│ 自动化测试工程师                                        │
│ 职责：按用例生成脚本、执行、收集失败、生成缺陷报告      │
│ 产物：tests/**/*.{py,ts,…}、qa/run/*.json、bug 报告     │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│                    QA-Gatekeeper                        │
│ QA Gate / 回归 / 发布质量门负责人                       │
│ 职责：选择回归范围、判定通过 / 失败 / 阻塞、签发结论    │
│ 产物：qa/regression_report.md、qa/release_gate_report.md│
└────────────────────────────────────────────────────────┘
```

### 3.1 角色不可越界

* **QA-Designer 不得直接执行测试或修复代码**。
* **QA-Runner 不得修改用例本身的断言或预期**——发现用例错误必须回写给 Designer 处理。
* **QA-Gatekeeper 不得生成或修改用例与脚本**，只能基于产物作出决策。

### 3.2 修复角色

修复默认由外部 Dev Agent 完成。如果项目允许 QA 自修复（个人项目场景），必须由**第四个独立上下文** QA-Fixer 执行，且修复完成后必须重新触发 Runner + Gatekeeper，不允许 Fixer 自己宣布通过。

### 3.3 与基模型偏置的缓解（硬约束）

承认现实：三个子角色若使用同一基模型，仅靠"换提示词"无法消除共享盲区（同样的常识假设、同样的需求误读）。本节规定为强制约束：

* **Gatekeeper 独立溯源**：Gatekeeper 必须**直接读取原始需求/验收文档**并自行摘录条款，不得直接 `trust` Designer 产出的需求关联关系；追踪矩阵的需求列必须由 Gatekeeper 重新核对一遍。
* **不同视角提示词**：Designer 偏覆盖（"还有什么没测到"），Gatekeeper 偏怀疑（"哪里可能错"）。具体提示词框架见实现指南。
* **未验证项必须显式列出**：Gatekeeper 报告中的"未能验证的事项"不允许为空——若无法找出任何未验证项，必须显式声明 `审查不足`。
* **关键路径人工抽检**：P0 用例、安全用例、影响支付/权限/数据保存的用例，Gatekeeper 必须在报告中标注 `建议人工复核`，不能依赖 Agent 自审作为最终凭据。
* **可选异质模型**：在 `.qa-agent.yml` 中允许配置 `gatekeeper_model` 使用与 Designer 不同的模型（如不同厂商或不同尺寸），作为偏置缓解的进一步手段——非强制，但推荐 L3 启用。

---

## 4. 适用范围

该 Agent 应设计为通用测试工程师核心能力，可用于不同项目类型：

* 前端 Web 项目
* 后端 API 项目
* 前后端全栈项目
* 移动端 Android / iOS 项目
* 桌面端项目
* 游戏项目
* 工具类项目
* 小型个人项目
* AI 自动生成项目
* 传统人工开发项目

但不同项目的测试执行方式不同，因此采用：

```text
通用 QA Core
+ 不同平台 Test Adapter
```

而不是每种项目完全重写一套 Agent。Adapter 必须实现统一接口（见第 14 章）。

---

## 5. 核心设计原则

### 5.1 测试用例不是测试阶段

测试用例是测试设计产物，不属于单独某一个测试阶段。每个测试用例必须标明它属于哪种测试层级：

* Unit Test / 单元测试
* Integration Test / 集成测试
* System Test / 系统测试
* Acceptance Test / 验收测试
* Smoke Test / 冒烟测试
* Performance Test / 性能测试
* Compatibility Test / 兼容性测试
* Security Test / 安全测试
* Regression Test：**测试目的，不是测试层级**，可以由任意层级的用例承担

### 5.2 AI 自动化测试必须沉淀为脚本

正式测试不应依赖 AI 临时手动操作 UI 后口头判断。AI 直接操控浏览器/手机/桌面等的能力**只用于探索性测试与脚本草稿生成**，最终交付物必须是可重复执行的测试脚本。

### 5.3 需求决定测什么，设计决定怎么测

测试用例不能只根据需求生成，也不能只根据代码生成。应综合分析需求、验收标准、BDD、设计与架构、接口、数据结构、当前代码、最近 diff、历史 bug、日志、业务/技术风险。

```text
需求决定测试目标
设计决定测试覆盖深度
代码实现决定测试落点
历史 bug 决定回归重点
```

### 5.4 测试必须分层

| 测试层级 | 目标 |
|---|---|
| 单元测试 | 验证单个函数、类、模块、状态机、纯逻辑 |
| 集成测试 | 验证多个模块之间是否正确协作 |
| 系统测试 | 验证整个系统或应用是否能完整运行 |
| 验收测试 | 验证功能是否满足需求和验收标准 |
| 冒烟测试 | 验证核心流程是否可启动、可进入、无阻塞错误 |

回归测试不在此表中，参见 5.1。

### 5.5 反伪造红线（强制）

禁止以下行为，任何一项触发即视为 Agent 违约：

* 删除失败测试来伪造通过。
* 降低断言标准来伪造通过。
* 跳过失败测试但仍宣布完成。
* 没有运行测试就声称测试通过。
* 只运行程序不做断言。
* 只手动体验一次就认为完成。
* 未记录失败原因就直接修改代码。
* 修复后不做回归测试。
* **L0 / L1 / L4 模式的结果作为发版依据**（见第 7 章）。
* **Agent 自行降档运行模式**（必须由用户显式指令）。
* **Agent 自行缩减用例选择范围**（用户可扩充，Agent 不可单方面缩减）。
* **以"省成本"为由缩减执行集**（成本不构成合法理由；上下文窗口物理上限触发时按"熔断暂停 + 拆分"处理，见 7.4）。

注：上述红线在**人触发**与**Agent 触发**场景下都适用，但执行前确认策略不同（见 18.4）。

### 5.6 测试代码自身的质量保障

测试代码不是免检产物，必须满足：

* 每个测试必须至少一个**有效断言**（不是 `assert True` 或仅打印）。
* 覆盖率门槛由项目级配置（见 `.qa-agent.yml`），默认 P0 相关代码行覆盖 ≥ 80%。
* **Mutation testing（增量执行）**：默认**仅 L3** 启用，且**只对本次 diff 涉及的源文件**做变异（不全量），用例有效性低于阈值时回写 Designer 补强。L2 不强制 mutation；项目可在 `.qa-agent.yml` 显式开启 L2 抽样。
* **对抗式 review**（仅 L2/L3）：QA-Designer 完成用例后，由独立上下文执行——尝试构造"实现错误但用例仍 PASS"的反例。
* **Flaky 检测（仅对失败用例）**：单条用例**失败**才触发隔离重跑（默认 5 次），全 PASS 才视为偶发并标 flaky 候选。**通过用例不重复跑**，flaky 概率由 `qa/run/history.json` 滚动统计。flaky 用例不计入 PASS。

实现细节（重跑次数、隔离上下文、统计窗口）见 `implementation_guide.md` §3。

### 5.7 失败循环防护

防止 AI 陷入"失败 → 改 → 再失败"无限循环：

* 单条用例自动修复尝试上限：**3 次**。
* 单次 QA 流程内的整体修复轮次上限：**5 轮**。
* 超限后必须停止，输出 `BLOCKED` 并升级人工。
* 同一断言连续失败两次，禁止继续修改测试代码本身（说明问题在被测代码或需求）。

### 5.8 Waiver / 风险接受机制

强红线的对立面必须是合法豁免通道，否则团队会绕规则。规则如下：

* 任何"已知不修复但允许放行"的失败用例，必须在 `qa/waivers.yml` 中显式登记。
* 每条 waiver 必须包含：用例编号、原因、责任人、签批时间、过期时间（≤ 当前迭代结束）。
* **过期 waiver 自动失效**，再次失败重新计入阻塞。
* Waiver 必须由人工签字的字段（`approved_by`）才能生效，**`approved_by` 必须匹配项目允许的 commit 作者白名单**（默认取 `git config user.email` 或 `.qa-agent.yml` 中 `waivers.allowed_approvers`）；不匹配视同未签字。
* **个人项目兜底**：单人项目可关闭白名单校验，但仍需在 `qa/waivers.yml` 中记录签字（君子协议级，由 25 章自检清单暴露）。
* **安全测试 waiver 按严重度分级**：
  * `critical` / `high`：**禁止 waiver**，必须修复或显式回退功能。
  * `medium` / `low`：允许有限 waiver，但过期时间 ≤ 7 天，且必须附 PoC 不可达性证明（在 `evidence:` 字段引用证据文件）。
  * 严重度由扫描器或人工评定，Agent 不得自降严重度。

### 5.9 需求变更与用例同步

* 每条用例必须关联**需求 ID + 需求段落语义指纹**（不是裸 hash）。
* 段落语义指纹生成步骤：去除空白/标点/Markdown 装饰 → 规范化 token → 计算指纹（默认 SimHash / MinHash 之类对小改动稳定的算法）。
* 需求文档变更时，QA-Designer 必须扫描受影响指纹：
  * **指纹完全一致** → 用例继续 active。
  * **指纹相似度 ≥ 0.85**（默认阈值，可在 `.qa-agent.yml` 调整）→ 视为微调，标 `state: review`，由 Designer 快速复审。
  * **相似度 < 0.85** → 标 `state: stale`。
* 任何 `stale` 用例不计入"已通过"，必须先复审或重设计后才能再执行。
* 跨段落需求由用例的 `requirement_ids[]` 数组承载，每个 ID 各自维护指纹；**任一指纹失配即触发同步**。
* 具体语义指纹算法、阈值调参与回归数据落在《实施指南》第 2 节。

---

## 6. 与 BMAD / Spec Kit 的关系

该 Agent 不替代 BMAD 或 Spec Kit。

```text
BMAD / Spec Kit
负责：需求、规格、架构、任务、验收标准

AI Test Engineer Agent
负责：测试计划、测试用例、自动化测试、测试报告、缺陷修复、回归测试

Platform Test Adapter
负责：不同项目类型的具体测试执行方式
```

### 6.1 BMAD 适合做什么

需求分析、PRD、架构设计、Epic / Story 拆分、QA 角色流程、PO 验收流程、测试策略引导。但 BMAD 默认生成的 Acceptance Criteria 通常不是完整测试工程师级测试用例。

### 6.2 Spec Kit 适合做什么

规格驱动开发：Constitution / Spec / Plan / Tasks / Implement / Validate。但 Spec Kit 默认也不是完整测试执行系统。

### 6.3 本 Agent 应该补足什么

```text
开发完成后的 QA Gate
```

包括完整测试用例、自动化测试脚本、测试执行、失败分析、缺陷报告、修复验证、回归测试、最终测试报告。

### 6.4 反向梳理（无需求文档时）

如果缺少需求或验收标准，Agent **不得直接生成测试**。流程：

```text
反向梳理当前功能 → current_features.md
↓
推断验收标准 → acceptance_criteria.draft.md
↓
【签字校验】
↓
转为正式 acceptance_criteria.md
↓
开始测试用例设计
```

**签字校验规则**（机器可强制，区分项目规模）：

* **多人项目（默认）**：必须由项目允许的 commit 作者签字（`approved_by` 字段，匹配 `git config user.email` 或 `.qa-agent.yml` 中 `reverse_engineering.allowed_signers` 白名单）；可选 GPG 签名。
* **个人项目**：在 `.qa-agent.yml` 设置 `reverse_engineering.solo: true` 后，签字降级为君子协议级——但 25 章自检清单会显式列出"未经独立审阅的反向梳理产物"，给用户提醒。
* **第二独立 Agent 审阅替代方案**：允许配置另一个上下文（最好是异质模型）作为审阅者，审阅记录写入 `acceptance_criteria.review.md`。

未签字的反向梳理产物**不得**作为测试基线，否则等同 Agent 自审自验。

---

## 7. 运行模式 L0–L4（核心成本控制）

不允许每次改动都跑全流程。Agent 提供 5 档运行模式，由用户**显式指令**触发，Agent 不得自行降档。

### 7.1 模式定义

| 模式 | 触发场景 | 设计阶段动作 | 执行阶段动作 | 产出 | 是否可作发版依据 |
|---|---|---|---|---|---|
| **L0 Spot** | 单点小改 / 快速 sanity | 不做设计，命中现有受影响用例 | 仅跑受影响单测 + 关联冒烟 | 简短结果（终端打印 + `qa/run/last.json`） | ❌ |
| **L1 Feature** | 一个功能开发完 | 增量补该功能用例 | 跑该功能全部分层用例 + 邻接回归 | 功能级测试报告 | ❌ |
| **L2 Module** | 一个模块/迭代完成 | 复核该模块所有用例完整性 | 跑该模块全部用例 + 跨模块集成 + 抽样 mutation | 模块级测试报告 + 缺陷清单 | ❌ |
| **L3 Release** | 准备发版 / 验收 | 校验需求追踪矩阵 100% 覆盖 | 全量分层 + 非功能（性能/安全/兼容） + flaky 检测 | 完整测试结论 + 质量门决策 | ✅ **唯一发版依据** |
| **L4 Bugfix** | 修复某个缺陷后 | 不做设计，定位失败用例 | 跑该缺陷复现用例 + 影响面回归 | 缺陷验证报告 | ❌ |

### 7.2 触发方式（仅基于本地命令与对话）

* 用户在对话中显式指令：`/qa L0`、`/qa feature 用户登录`、`/qa module 订单`、`/qa release`、`/qa bugfix BUG-007`。
* 项目根的 `.qa-agent.yml` 定义每档具体行为（覆盖默认值）。
* Agent 接到指令后**先回报**："本次以 X 模式执行，预计设计 N 条新用例 + 执行 M 条用例（其中 P0 a 条 / P1 b 条）"，**等用户确认后**再执行。

### 7.3 强制规则

* **L3 不允许整体省略**：发版/验收前必须完整执行一次 L3，未通过即视为未发版。
* **L3 维度切片（合法收窄）**：L3 包含若干**正交维度**——功能层（unit / integration / system / acceptance）、性能、安全、兼容（浏览器矩阵 / OS 矩阵 / 设备矩阵）、mutation、flaky 检测。允许在 `/qa release --skip <dim>[,<dim>...]` 中显式跳过部分**非功能或矩阵**维度（如 `--skip compatibility:firefox,performance`），但：
  * **功能层 + 安全 + P0 全量执行不可跳过**。
  * 跳过的维度必须在 `release_gate_report.md` 的 `uncovered_dimensions:` 字段登记，并附理由与责任人。
  * 切片后的 L3 仍是 L3，结论生效；但带 `uncovered_dimensions` 的 PASS 自动降级为 `CONDITIONAL PASS`。
  * Agent 不得自行决定跳过维度；切片必须由用户显式指令。
* **Agent 不得自行降档**：用户要求 L3，Agent 不能因"看上去用例不多"自动改成 L1。降档与切片是不同概念——切片是 L3 内部的合法裁剪，降档是把 L3 改成 L2/L1（禁止）。
* **升级路径单向**：
  * L0 在同一变更上累计失败 ≥ 2 次 → 强制升 L1。
  * L1 在同一功能上累计失败 ≥ 2 次 → 强制升 L2。
  * 升级是 Agent 的义务，不需要用户额外指令。
* **L0 / L1 / L4 的"PASS"不构成发版凭据**（红线，参见 5.5）。

### 7.4 执行预算

* **不设 token 上限**。**成本不构成缩减执行集的理由**——Agent 不得以"省 token"为由缩减范围。上下文窗口物理上限触发时按"熔断暂停 + 拆分多次执行"处理，不允许通过缩减用例集规避。
* **单次执行用例数上限**：默认 L0=10、L1=80、L2=500、L3=不限、L4=20，可在 `.qa-agent.yml` 覆盖。
* **可选时间预算**：`.qa-agent.yml` 允许配置 `mode_limits.<L>.max_minutes`（仅作熔断阈值，不作裁剪依据）。超时不允许 Agent 自行缩减用例集；触发时向用户报告"当前模式超时，建议拆分 / 增加并行 / 切换模式"。
* 用例数 / 时间任一超限触发**熔断暂停**："当前选择超过模式上限，是否继续 / 拆分 / 切换模式？" 由用户决定，Agent 不得自动截断。
* **mode_limits 自适应建议**：项目可在 `.qa-agent.yml` 设 `mode_limits.<L>.percentage`（如 `L1: percentage: 0.15` 表示当前用例库的 15%）；条数与百分比同时设置时取较大值。

### 7.5 模式与角色协作

```text
L0 / L4：仅 QA-Runner + QA-Gatekeeper（轻量结论）
L1：QA-Designer（增量）+ Runner + Gatekeeper
L2：三角色全开 + 对抗式 review + mutation 抽样
L3：三角色全开 + 对抗式 review + mutation + 非功能 + flaky + waiver 校验
```

---

## 8. 影响面分析（执行裁剪算法）

执行阶段"跑哪些用例"由影响面分析决定。本规范**默认依赖 CodeGraph** 作为代码图来源，仅在用户显式禁用时才回退到本地 diff + 用例索引。

### 8.1 默认实现（CodeGraph 模式）

1. 取本次变更的 diff（git diff，或用户显式提供的代码区间）。
2. 调用 CodeGraph 工具：
   * `mcp__codegraph__codegraph_explore`：拿到变更涉及的符号列表与受影响 process。
   * 对每个变更符号调用 `mcp__codegraph__codegraph_node`，方向 `upstream`，深度按模式：**L0=2 / L1=3 / L2=3 / L3=不限 / L4=3**（动态语言/反射/依赖注入项目下，浅层深度极易漏选，故默认值已上调）。
3. 把受影响符号集合反查 `qa/cases/*.yml` 中 `targets:` 字段，命中即纳入执行集。
4. **补集兜底（强制）**：CodeGraph 难以追踪反射、装饰器、字符串路由、依赖注入、跨进程/跨服务调用。Agent 必须按以下规则补充执行集：
   * 命中用例的 `feature_id` 集合 → 纳入同 `feature_id` 的所有用例（L2/L3 全开；L1 仅同 feature_id 内 P0/P1）。
   * 变更文件路径前缀匹配的 `regression_tags`（项目可在 `.qa-agent.yml` 配置 `path_to_tags` 映射）→ 纳入相应 tag 下所有用例。
   * 历史"易随此变更失败"的用例（`qa/run/history.json` 中与当前 diff 文件 cohort 关联失败 ≥ 2 次）→ 纳入。
5. 命中用例的兄弟用例（同 `feature_id`）在 L2/L3 下也纳入（与 4 重叠时去重）。
6. 历史 flaky / 易失败用例额外纳入（来自 `qa/run/history.json`）。
7. 输出执行集 + 选择理由（写入 `qa/run/selection.md`），每条用例标注命中来源（`codegraph_upstream` / `feature_cohort` / `tag_match` / `history_correlation` / `flaky_followup` / `user_added`）。

### 8.2 回退实现（无 CodeGraph）

仅在用户在 `.qa-agent.yml` 设置 `impact_analysis: local` 或显式指令 `/qa --no-codegraph` 时启用：

1. 基于 git diff 拿到变更文件路径。
2. 反查用例 `targets.files[]` 命中。
3. 在 L2/L3 下，额外加入文件所在目录下其他用例（粗粒度近似邻接）。
4. 在报告中显著标注"本次未使用代码图，影响面分析为粗粒度近似，可能漏选用例"。

### 8.3 用户控制

* **用户必须能扩充**执行集（追加用例 ID 或 tag）。
* **Agent 不得单方面缩减**用户提供的执行集。
* 选择理由必须可读：`qa/run/selection.md` 列出每条入选用例的命中链路（变更符号 → 被测代码 → 用例）。

### 8.4 CodeGraph 不可用时的处理

* CodeGraph 工具调用失败 → Agent 必须明确告知用户"代码图不可用"，**不得静默回退**。
* 用户可选择：等待修复 / 显式切到 local 模式 / 取消本次运行。

---

## 9. 测试资产管理（长期沉淀）

测试用例 / 缺陷 / 映射表是**长期资产**，不是每次重生成的中间产物。

### 9.1 存储格式：结构化为主，Markdown 为视图

* 用例：`qa/cases/<feature_id>/<case_id>.yml`，每条一个文件，便于 diff、合并、引用。
* 映射表 / 矩阵：从用例文件聚合生成 `qa/test_traceability_matrix.md`、`qa/automation_mapping.md` 作为只读视图，**不允许直接编辑视图文件**。
* 缺陷：`qa/bugs/<bug_id>.yml`，列表视图聚合到 `qa/bug_report.md`。
* 历史：`qa/run/history.json` 记录每次执行结果（成败、耗时、flaky 标记）。

### 9.2 用例 YAML Schema

```yaml
id: TC-LOGIN-001
title: 用户使用正确账号密码登录成功
state: active            # active | review | stale | flaky | retired
                         # review = 需求微调待复审；stale = 需求大改需重设计
feature_id: F-LOGIN
requirement_ids: [REQ-101]
requirement_fingerprints:    # 见 5.9，每个需求段落一个语义指纹
  REQ-101: "simhash:a1b2c3d4..."
acceptance_criteria_ids: [AC-101-1]
level: system            # unit | integration | system | acceptance | smoke | performance | security | compatibility
purpose: functional      # functional | exception | boundary | regression | exploratory
priority: P0             # P0 | P1 | P2 | P3

preconditions:
  - 用户账号已存在

test_data:
  username: alice
  # 机密字段必须用引用语法，禁止明文：
  password: "${secret:login.password}"     # 来自机密文件 / 密钥库
  token:    "${env:LOGIN_TOKEN}"           # 来自环境变量
  # Adapter.generate 必须识别 ${secret:...} / ${env:...} 并在生成脚本时
  # 替换为对应运行时取值代码（见实施指南 §6）。

steps:
  - 打开登录页
  - 输入账号密码
  - 点击登录
expected:
  - 跳转首页
  - 显示用户昵称
assertions:
  - selector: "[data-testid=username-display]"   # 见 14.1：禁止结构脆弱选择器
    equals: "alice"

automation:
  status: implemented    # implemented | scaffolded | manual | not_applicable
  framework: playwright
  file: tests/system/login.spec.ts
  test_id: login_with_valid_credentials

# targets 由 Adapter/Indexer 自动维护，Designer 不手填；
# 重命名/移动文件时由工具回写。Designer 只填 feature_id 与需求关联。
targets:
  files: [src/pages/login.tsx, src/api/auth.ts]
  symbols: [LoginPage, authenticate]
  generated_by: adapter-web@0.5.0
  generated_at: 2026-06-16T10:00:00+08:00

regression_tags: [auth, smoke]
notes: ""
```

**字段维护责任划分**：

| 字段 | 责任方 | 说明 |
|---|---|---|
| `requirement_ids` / `requirement_fingerprints` | QA-Designer | 关联需求与指纹 |
| `targets.files` / `targets.symbols` | Adapter / Indexer 自动 | 重构时由工具回写；Designer 不手维护 |
| `automation.*` | QA-Runner（首次生成）/ Adapter | 框架、文件路径、test_id |
| `state` | Designer（设计变更）/ Runner（flaky 检测）/ 用户（retired） | 不同事件触发不同写入方 |
| `assertions` | Designer | Runner 不得弱化 |
| `test_data` | Designer | 机密字段必须用引用语法 |

### 9.3 增量演进规则

* 首次接入项目跑一次 L2/L3 建立用例库。
* 之后只对**新需求 / 改动需求**做增量设计，已有用例**直接复用**。
* 用例的 `state` 必须显式管理：`stale` / `review` / `flaky` 用例不计入 PASS。
* 用例下线必须改 `state: retired` + 注明原因，**不得直接删除文件**（保留审计轨迹）。

### 9.4 KPI 反馈数据回流

第 2.1 章定义的"缺陷逃逸率"、"误报率"必须有真实数据来源，否则永远是 0/0：

* 反馈目录：`qa/feedback/`
  * `escaped_bugs/<bug_id>.yml`：验收/上线后被发现的缺陷，包含原始 release 标识、漏检的用例链路（如有）。
  * `false_positives/<run_id>/<case_id>.yml`：被人工标注为"测试代码 bug 而非实现 bug"的失败记录。
* 写入方：人工或外部 issue/反馈系统的同步脚本（**不在本规范范围**，但 Agent 必须读得懂这个目录）。
* 计算方：QA-Gatekeeper 在 L3 报告中计算 KPI 时，从 `qa/feedback/` 与 `qa/run/history.json` 联合统计；缺数据时显示 `n/a`，而不是 `0`。

### 9.5 缓存

测试计划、风险分析、追踪矩阵的产物在产物头加 `inputs_hash`：输入未变 → 跳过重新生成，直接复用上次产物。

---

## 10. 推荐项目目录结构

```text
project/
  docs/
    requirements.md
    architecture.md
    design.md
    acceptance_criteria.md
    task_breakdown.md

  specs/
    feature-001/
      spec.md
      acceptance.feature
      tasks.md

  qa/
    test_plan.md                    # 视图，可重新生成
    test_traceability_matrix.md     # 视图，由 cases 聚合生成
    automation_mapping.md           # 视图，由 cases 聚合生成
    manual_test_cases.md            # 视图，由 cases 聚合生成
    final_test_report.md            # 视图，由 run/ 聚合生成
    bug_report.md                   # 视图，由 bugs/ 聚合生成
    regression_report.md            # 视图
    release_gate_report.md          # 视图（仅 L3 生成）
    waivers.yml                     # 风险接受清单（人工签字）
    cases/                          # 权威源
      F-LOGIN/
        TC-LOGIN-001.yml
        TC-LOGIN-002.yml
      F-ORDER/
        ...
    bugs/                           # 权威源
      BUG-007.yml
    run/                            # 执行历史
      last.json
      history.json
      selection.md                  # 本次影响面选择理由
    feedback/                       # KPI 数据回流（人工或外部系统标注）
      escaped_bugs.yml              # 验收/生产中发现、QA 漏掉的缺陷
      false_positives.yml           # QA 报为 fail 实为测试代码问题
      manual_signoffs/              # 人工签字证据（含 manual 用例与 waiver）

  tests/
    unit/
    integration/
    system/
    acceptance/
    smoke/
    performance/
    security/

  scripts/
    run_tests.sh
    run_unit_tests.sh
    run_integration_tests.sh
    run_system_tests.sh
    run_acceptance_tests.sh

  .qa-agent.yml                     # 项目级配置（见 11 章）
  AGENTS.md
```

如果项目已有自己的目录结构，Agent 应在不破坏原结构的前提下适配（参见下一节渐进式接入）。

---

## 10A. 渐进式接入（已有项目）

新建项目可以直接按 §10 创建目录；但实际场景里项目通常**已有 `tests/`、已有 pytest/jest 配置、已有部分 CI 脚本**。Agent 不允许"清空重写"，必须按以下顺序接入：

### 步骤 1：盘点现状（只读）

* 调用 Adapter `detect()` 识别现有测试框架与目录布局。
* 输出 `qa/current_test_status.md`：列出已有测试目录、配置文件、可执行命令、推断的层级映射。
* **不修改任何源文件**。

### 步骤 2：协商映射（请用户确认）

向用户给出"现有目录 → §5.4 测试层级"的映射建议，例如：

```text
src/__tests__/         → unit
tests/integration/     → integration
e2e/                   → system
features/              → acceptance
```

允许多对一、一对多。用户确认后写入 `.qa-agent.yml` 的 `paths.layers:` 节。

### 步骤 3：建立用例库（不动现有测试）

* 在 `qa/cases/` 下逐个生成对应 YAML，`automation.file` 指向**现有测试文件**（不重写）。
* 现有测试无法对齐到任何用例的 → 标 `automation.status: orphan`，列入 `qa/orphan_tests.md`，**不删**，由人工决定后续处理。

### 步骤 4：增量改造而非迁移

* **不**强制把 `src/__tests__/` 移到 `tests/unit/`。Adapter 必须能按 `paths.layers:` 解析现有路径。
* §10 推荐目录是**新项目模板**，已有项目以 `paths.layers:` 为准。

### 步骤 5：补齐缺口

* 列出当前缺失层级（例如已有 unit/integration，缺 system/E2E）。
* 由用户决定补哪几层 → 进入正常 L1/L2 流程逐步补齐。

### 强制约束

* **禁止**为对齐推荐目录而批量移动现有测试文件。
* **禁止**修改现有测试的断言（除非该测试已经被识别为 orphan 且用户签字同意）。
* `qa/` 目录的引入不得破坏原有 CI 之外的任何路径（本规范不涉及 CI 修改）。

---

## 11. 项目级配置 `.qa-agent.yml`

每个项目根放一份 `.qa-agent.yml`，覆盖默认行为：

```yaml
project_type: web                   # web | backend | fullstack | mobile | desktop | game | tool
language: typescript
frameworks:
  unit: vitest
  integration: vitest
  e2e: playwright
  performance: k6                   # 可选
  security: zap                     # 可选

# 三角色模型配置（5.5 节"可选异质模型"）
roles:
  designer_model: claude-opus-4-7    # 默认继承
  runner_model: claude-opus-4-7
  gatekeeper_model: claude-sonnet-4-6  # 推荐 L3 异质，弱化共享盲区

impact_analysis: codegraph           # codegraph（默认） | local
codegraph:
  fallback_supplement_tags: true    # 8.1 步骤 6：按 feature_id/regression_tags 兜底
  upstream_depth:
    L0: 1
    L1: 2
    L2: 3
    L3: -1
    L4: 2

mode_limits:                        # 单次执行用例数上限（不限 token，仅限用例数）
  L0: 10
  L1: 80
  L2: 500
  L3: -1                            # 不限
  L4: 20

# 可选：单次执行最大墙钟时间（按时间预算补充用例数预算，超时熔断）
mode_time_budget_minutes:
  L0: 5
  L1: 30
  L2: 120
  L3: -1
  L4: 15

coverage_thresholds:
  p0_line: 0.80
  p0_branch: 0.70

mutation:
  enabled: true
  scope: diff                       # diff（默认，仅本次变更涉及代码） | sample（指定模块抽样）
  sample_modules: [src/auth, src/payment]   # 仅当 scope=sample 时生效
  enabled_modes: [L3]               # 默认仅 L3 跑；可加 L2 显式开启
  threshold: 0.60

flaky:
  retry_failed_only: true           # 仅对失败用例重跑，通过用例不重跑
  retry_runs: 5                     # 失败重跑次数；全 PASS 才视为偶发并标 flaky
  rolling_window_runs: 50           # history.json 滚动统计窗口
  block_as_pass: true               # flaky 用例不计入 PASS

waivers:
  require_human_approval: true
  allowed_approvers: []             # 邮箱白名单；空数组退化为君子协议（个人项目）
  forbid_security_waiver_severity: [critical, high]  # high/critical 禁止 waiver
  max_expiry_days_low_severity: 7   # medium/low 严重度安全 waiver 最长 7 天

repair_loop:
  per_case_attempts: 3
  total_rounds: 5

# 非功能测试触发档位
nonfunctional:
  performance: [L3]
  security: [L3]
  compatibility: [L3]

# L3 维度切片（避免"全有或全无"导致团队私下降档）
release_dimensions:
  required: [functional, regression, smoke, p0_coverage]
  optional:                         # 可显式跳过的维度，必须在 release_gate_report 登记
    - performance
    - security_scan
    - compatibility_matrix
    - mutation
  skip_requires_waiver: true        # 跳过 optional 维度时必须有对应 waiver

# 生产保护
production_guard:
  patterns:
    - "*.prod.example.com"
    - "*-production.*"
    - "PROD_DB_HOST"

# 触发场景识别（区分人触发 vs Agent 触发，决定是否需要交互确认）
trigger:
  human_modes_require_confirm: true        # 用户对话触发：必须 yes 才执行
  agent_modes_auto_confirm: [L0, L4]       # Dev Agent 触发：仅 L0/L4 可自动确认
  agent_modes_require_human_for: [L2, L3]  # L2/L3 即使 Agent 触发也需人审

# secret 注入
secrets:
  resolver: env                     # env | dotenv | vault
  env_prefix: QA_

# 用例 targets 自动维护
targets_indexer:
  enabled: true
  update_on_rename: true            # 借助 LSP / CodeGraph 自动跟踪 rename/move
```

如果 `.qa-agent.yml` 不存在，Agent 在初始化阶段必须**先生成草稿并请用户确认**，不得使用未确认的默认值直接跑 L3。

---

## 12. Agent 输入

### 12.1 必选输入

* 当前项目源码
* 当前开发完成的功能说明
* 需求文档或用户故事
* 验收标准
* 项目运行方式
* 项目测试命令
* `.qa-agent.yml`（缺失时按 11 章流程补齐）

### 12.2 推荐输入

架构文档、设计文档、接口文档、数据库设计、UI 流程、BDD/Gherkin 场景、历史 bug、最近代码 diff、运行日志、崩溃日志、已有测试代码。

### 12.3 输入缺失处理

参见 6.4。**反向梳理产物未经签字不得作为测试基线**。

---

## 13. Agent 输出

所有"报告"类文件均为**视图文件**，由结构化数据聚合生成，可被覆盖重写；权威数据在 `qa/cases/`、`qa/bugs/`、`qa/run/` 中。

### 13.1 测试计划 `qa/test_plan.md`

* 测试目标
* 测试范围 / 不测试范围
* 风险分析
* 测试层级
* 测试优先级
* 测试环境与数据策略（含 mock / Testcontainers / 凭据注入说明）
* 自动化策略
* 手动测试策略
* 回归策略
* 非功能测试策略（性能 / 安全 / 兼容）
* 发布质量门标准

### 13.2 需求追踪矩阵 `qa/test_traceability_matrix.md`

| 需求编号 | 功能点 | 验收标准 | 测试用例 | 测试层级 | 自动化状态 | 当前状态 |
|---|---|---|---|---|---|---|

由 `qa/cases/**/*.yml` 聚合生成。

### 13.3 测试用例

权威源：`qa/cases/<feature_id>/<case_id>.yml`（schema 见 9.2）。
聚合视图：`qa/test_cases.md`、`qa/manual_test_cases.md`。

### 13.4 自动化映射 `qa/automation_mapping.md`

| 用例编号 | 测试层级 | 框架 | 文件 | test_id | 已实现 | 已执行 | 最近结果 | flaky |
|---|---|---|---|---|---|---|---|---|

### 13.5 测试报告 `qa/final_test_report.md`

* 运行模式（L0–L4）
* 总数 / 自动化 / 手动 / 通过 / 失败 / 跳过 / Flaky
* 未覆盖需求清单
* 高风险问题、阻塞问题
* 回归结果
* **未能验证的事项**（Gatekeeper 必填）
* **建议人工复核的项**（Gatekeeper 必填）
* 是否建议通过验收 / 发布（仅 L3 生效）

### 13.6 缺陷报告（权威：`qa/bugs/<bug_id>.yml`，视图：`qa/bug_report.md`）

```yaml
id: BUG-007
title: 登录后昵称未渲染
state: open                # open | fixed | verified | wont_fix | duplicate
severity: high             # blocker | high | medium | low
priority: P1
related_cases: [TC-LOGIN-001]
related_requirements: [REQ-101]
repro_steps: [...]
expected: ...
actual: ...
logs: ...
suspected_cause: ...
impact_scope: ...
suggested_fix: ...
needs_regression: true
regression_scope_hint: [F-LOGIN, smoke]
created_at: 2026-06-16T10:00:00+08:00
```

### 13.7 回归测试报告 `qa/regression_report.md`

* 修复列表
* 回归用例集（含选择理由 → 引用 `qa/run/selection.md`）
* 回归通过 / 失败
* 是否引入新问题
* 最终结论

### 13.8 发布质量门报告 `qa/release_gate_report.md`（仅 L3）

结论必须是以下之一：

```text
PASS              允许进入验收或发布
CONDITIONAL PASS  允许继续，但存在非阻塞问题（必须列出 waiver 引用）
FAIL              不允许发布，存在阻塞问题
BLOCKED           测试无法完成，需要补充环境、需求或配置
```

---

## 14. 平台适配器接口契约

所有 Adapter 必须实现下列方法。Agent 调用时**只通过该接口**，不允许在 Core 内硬编码任何平台细节。Core 不假设接口"行为统一"，而是按下文 14.0 的 **capabilities 能力声明**决策。

```text
interface TestAdapter:
  detect() -> ProjectFingerprint
      # 返回项目类型、语言、已识别框架、运行命令、构建命令、capabilities 位

  scaffold(plan) -> void
      # 按 plan 在项目中创建/补齐测试目录、配置、依赖说明（不擅自安装）

  generate(case_yaml) -> AutomationFile
      # 基于用例 YAML 生成可执行测试脚本，返回脚本路径与 test_id

  index_targets() -> TargetIndex
      # 自动维护用例 targets.{files,symbols} 与代码的映射；
      # 在 rename / move / 抽函数后由 Adapter 内部刷新，Designer 不手填

  run(selection, mode) -> RunResult
      # 执行 selection 指定的用例集合，返回结构化结果（用例ID、状态、耗时、错误、产物路径）

  parse_report(raw_output) -> NormalizedResult
      # 把框架原生输出归一为标准结果对象

  collect_artifacts(run_id) -> ArtifactBundle
      # 收集失败截图、日志、视频、覆盖率、mutation 报告等

  classify_failure(case_result) -> FailureKind
      # 区分 test_failure / setup_failure / env_failure / flaky；用于 19 章决定是否阻断下层
```

**强约束**：

* `RunResult` 必须给每条用例返回机器可读状态（pass / fail / skip / error / flaky / blocked）。
* `generate` 产物必须遵循 9.2 用例 YAML 中的 `assertions:`，断言不能在生成阶段被静默削弱。
* `index_targets` 必须能自动刷新 `targets.{files,symbols}`；Designer 在用例 YAML 中只需要写 `feature_id` 与 `requirement_ids[]`，`targets` 由 Adapter 自动产出 / 维护。
* 当 Adapter 不支持某能力，必须在 `capabilities` 中显式置 `false`，不得伪装支持。

### 14.0 Capabilities 能力声明矩阵

每个 Adapter 的 `detect()` 必须返回一份能力位声明，Core 据此决策："如果某能力为 false，对应阶段自动降级为 manual / not_applicable / 提示用户补环境，而不是假装能跑"。最小集合：

| 能力位 | 含义 | Core 行为（false 时） |
|---|---|---|
| `headless` | 是否支持无头执行 | E2E/UI 类用例自动转 manual 或在 L3 提示需要图形环境 |
| `parallel` | 是否支持并行执行 | 串行回退，不再尝试多 worker |
| `coverage` | 是否能产出覆盖率 | 跳过覆盖率门槛校验，并在报告中标注"未覆盖" |
| `mutation` | 是否支持 mutation testing | 自动跳过 mutation 抽样 |
| `screenshot` | 失败截图能力 | `collect_artifacts` 不强制要求截图 |
| `video` | 失败录屏能力 | 不强制要求录屏 |
| `network_record` | 网络录制 / 重放 | 网络相关用例降级 mock-only |
| `device_pool` | 真机/模拟器池 | Mobile 用例转 manual 或提示需要设备 |
| `process_isolation` | 用例间进程隔离 | flaky 隔离重跑降级为同进程隔离 |
| `secret_provider` | 机密注入支持 | 用 `${env:...}` 兜底，不再尝试 vault 引用 |

Adapter 可声明额外能力位（自定义），Core 必须把未识别能力位记录在 `qa/run/last.json` 但不据此决策。

### 14.1 Web Adapter

* 推荐工具：Playwright、Cypress、Vitest、Jest、Testing Library
* 关注点：渲染、表单、路由、API mock、状态管理、E2E 流程、可访问性
* **强制**：E2E 选择器优先 `data-testid` / `aria-role`。
* **不可机器强制**：项目代码可能本身没 `data-testid`。Adapter 必须在 `detect()` 阶段统计 `data-testid` 覆盖率，缺失时输出 `ImprovementHint`（写入 `qa/current_test_status.md`）建议 Dev Agent 补，**但不阻断生成**；缺失场景下 Adapter 可使用 role/text 选择器，禁止使用纯 nth-child 链，并在 RunResult 中标注 `selector_quality: weak`。

### 14.2 Backend Adapter

* 推荐工具：pytest、JUnit、NUnit、go test、REST Assured、Pact（按需）
* 关注点：API、数据库读写、事务、鉴权、权限、缓存、队列、异常、幂等、并发
* **强制**：集成测试优先使用 Testcontainers / docker-compose 启真依赖，不允许默认 mock 数据库（除非项目在 `.qa-agent.yml` 中显式配置 `integration_db: mock` 并附理由）。

### 14.3 Mobile Adapter

* 推荐工具：JUnit、Espresso、XCUITest、Maestro、Appium
* 关注点：跳转、模拟器、权限、网络切换、横竖屏、后台恢复、输入法、版本兼容、崩溃日志
* **能力依赖**：`device_pool` 为 false 时，所有需要真机/模拟器的用例自动转 manual，并提示用户连接设备。

### 14.4 Desktop Adapter

* 推荐工具：Playwright（Electron）、平台原生 UI 自动化工具、单元测试框架
* 关注点：启动、窗口、文件读写、系统权限、快捷键、跨平台
* **能力依赖**：跨 OS 兼容由能力位 `cross_os` 声明；缺失时只在当前 OS 跑，不强制矩阵。

### 14.5 Game Adapter

* 推荐工具：引擎自带框架（Unity Test Framework、GdUnit4 / GUT、Unreal Automation）、自定义场景脚本
* 关注点：场景加载、状态机、存档读档、UI 状态、任务流程、属性、输入模拟、资源引用、性能、卡死、主流程冒烟
* **能力现实**：游戏 GUI 测试常需图形栈（Xvfb / 显示器），`headless` 多为 false。这种情况下 Game Adapter 可只跑 `unit + smoke`，UI 体验类用例转 manual 并在 release_gate_report 中显式列出。
* **特殊**：人工体验验收用例不强制自动化，但必须登记在 `manual_test_cases` 视图，不得遗漏。

### 14.6 不可自动化用例

每个 Adapter 必须能识别并标记 `automation.status: not_applicable`：
* 必须给出原因（如真实支付链路、视觉细节、第三方限流、平台 capabilities 缺失）。
* 必须以 manual 用例形式登记，并在 L3 报告中列出"待人工执行"清单。
* L3 通过的前提是这些 manual 用例由人工签字确认。

### 14.7 渐进式接入（已有项目）

文档目录结构假设新项目，但实际项目大多有自己的 `tests/` 与配置。Adapter 必须支持渐进式接入：

1. **detect 阶段不破坏现状**：识别已有 `tests/`、`pytest.ini`、`jest.config.js` 等，不强制重排目录。
2. **影子目录**：`qa/cases/` 单独存放用例 YAML，与项目原有测试代码并存；`automation.file` 字段可指向原 `tests/` 路径，无需迁移。
3. **新增用例先放新目录**，旧测试用 `index_targets` 反向登记进用例库（自动建档案）。
4. **能力位降级**：旧项目缺 `data-testid`、缺 Testcontainers、缺覆盖率配置时，按 14.0 表格降级，**只输出 ImprovementHint，不阻断**。
5. **MVP 接入"轻模式"**：仅 L0/L4 + local 影响面 + 不要求覆盖率门槛，团队可先用一周观察，再决定是否升 L2/L3。
6. 完整迁移路径写在 `qa/current_test_status.md` 顶部，作为渐进改进任务清单。

---

## 15. 测试层级定义

### 15.1 单元测试

目标：验证单个函数、类、组件、状态机、纯逻辑是否正确。
适合：计算逻辑、状态流转、数据转换、校验规则、工具函数、独立业务规则。
特点：快、稳定、易定位，应频繁执行。

### 15.2 集成测试

目标：验证多个模块、组件、服务之间是否正确协作。
适合：前端组件与状态管理、后端服务与数据库、API 与业务服务、消息队列、缓存、第三方集成。
特点：能发现接口与联动问题；优先用 Testcontainers / docker-compose 启真依赖。

### 15.3 系统测试

目标：验证整个系统从用户入口到核心流程是否完整可运行。
适合：应用启动、登录到核心业务、主流程、端到端链路、部署环境验证。
特点：接近真实使用，但失败定位成本较高。

### 15.4 验收测试

目标：验证功能是否满足需求、用户故事和验收标准。
适合：用户故事验收、产品需求验收、BDD 场景、发布前质量门、业务流程确认。
特点：以需求为中心，可自动化也可部分手动。

### 15.5 回归测试

目标：验证新增/修复后没有破坏已有功能。
回归是**测试目的**，不是层级；范围由影响面分析（第 8 章）决定。

### 15.6 非功能性测试（v2 新增落地）

#### 性能测试

* 触发档位：默认 L3（可在 `.qa-agent.yml` 调整）。
* 工具建议：k6 / JMeter / Locust（后端）、Playwright trace + Lighthouse（Web）、引擎 profiler（游戏）。
* 必须设定阈值：QPS、p95 / p99 延迟、错误率、资源占用。阈值在 `qa/test_plan.md` 中显式记录，未设阈值的性能用例不允许判定 PASS。

#### 安全测试

* 触发档位：默认 L3。
* 工具建议：OWASP ZAP（Web）、依赖漏洞扫描（npm audit / pip-audit / OWASP Dependency-Check）、自定义鉴权绕过用例。
* **环境隔离强制**：安全测试**只允许在隔离环境**运行；目标 host 命中生产标识时必须中止并报错。
* **安全用例不允许 waiver**（5.8）。

#### 兼容性测试

* 触发档位：默认 L3。
* Web：浏览器矩阵（Chromium / Firefox / WebKit）。
* 移动端：系统版本矩阵 + 屏幕尺寸矩阵。
* 桌面端：操作系统矩阵。
* 矩阵在 `.qa-agent.yml` 显式列出，未列出的不视为已覆盖。

---

## 16. 测试环境与数据策略

### 16.1 环境

* 单元测试：进程内，不依赖外部服务。
* 集成测试：默认使用 Testcontainers / docker-compose 启动真实依赖；如必须 mock，须在 `qa/test_plan.md` 显式记录与理由。
* 系统/E2E 测试：本机或沙箱，禁止指向生产。
* 凭据：通过本地 `.env` 或机密文件注入；Agent 不得把凭据写入用例 YAML 或日志。

### 16.2 测试数据

* 默认每条用例自带或引用独立测试数据，避免共享可变状态。
* 数据库测试每个用例使用独立 schema / 事务回滚。
* 不允许用例之间通过执行顺序传递状态。

### 16.3 生产保护红线

* Agent 在执行前必须检查目标 endpoint / DSN：包含生产标识（如 `prod`、生产域名、生产数据库主机）时**直接中止**。
* 用户可在 `.qa-agent.yml` 配置 `production_guard.patterns` 列表，Agent 必须遵守。

---

## 17. BDD 支持

Agent 应支持 BDD，但不强制所有项目使用 BDD。

* 项目已有 BDD/Gherkin → Agent 读取并生成对应用例 YAML。
* 项目无 BDD 但有验收标准 → Agent 可将验收标准转换为 Gherkin 草稿，再转为用例 YAML。
* BDD 文档不是终点，必须继续生成用例与自动化映射。

```gherkin
Feature: 用户登录
  Scenario: 用户使用正确账号密码登录成功
    Given 用户位于登录页面
    And 用户账号存在
    When 用户输入正确账号和密码
    And 点击登录按钮
    Then 系统应进入首页
    And 页面应显示用户昵称
```

---

## 18. Agent 工作流（按模式分支）

### 18.1 初始化阶段（首次接入项目时一次性）

1. 扫描项目结构。
2. 调用 Adapter `detect()` 识别项目类型、语言、框架、运行命令、构建命令。
3. 检查 `.qa-agent.yml`，缺失则生成草稿请用户确认。
4. 检查 CodeGraph 可用性；不可用且用户未显式选择 local 模式 → 中止并请示。
5. 输出 `qa/current_test_status.md`：当前测试能力评估、缺口清单。

### 18.2 L3 完整流程（设计 → 执行 → 决策）

```text
[QA-Designer]
  读取需求 / 设计 / 验收标准 / BDD
    ↓ 缺失？→ 6.4 反向梳理（必须签字）
  生成或更新用例 YAML（增量演进）
  生成 test_plan.md / 矩阵 / 自动化映射
  对抗式 review：尝试构造"实现错但用例 PASS"反例 → 补强
    ↓
[QA-Runner]
  调用 Adapter.generate() 补齐自动化脚本
  调用 8.1 影响面分析 → selection.md（L3 全量）
  调用 Adapter.run(selection, mode=L3)
  收集失败 → 写入 qa/bugs/
  flaky 检测（重跑 N 次）
  抽样 mutation testing
    ↓
[失败 → 修复轮（受 5.7 上限保护）]
  外部 Dev Agent 或 QA-Fixer 修复
  Runner 重跑相关用例
    ↓
[QA-Gatekeeper]
  调用 8.1 选回归集（基于本轮所有 fixed bug）
  Runner 跑回归 → regression_report.md
  校验：
    - 所有 P0 通过？
    - 覆盖率 / mutation 阈值达标？
    - 无 active flaky 阻塞？
    - 待人工签字 manual 用例已签字？
    - 安全测试无失败且无 waiver？
    - waivers.yml 是否有过期项？
  输出 release_gate_report.md：PASS / CONDITIONAL PASS / FAIL / BLOCKED
  必填："未能验证的事项"、"建议人工复核的项"
```

### 18.3 L0 / L1 / L2 / L4 简化分支

* **L0**：Runner 单跑受影响单测+冒烟，直接给终端结论；不出报告文件。
* **L1**：Designer 增量补该功能用例；Runner 跑该功能全部 + 邻接回归；轻量 final_test_report 标注"非发版依据"。
* **L2**：完整三角色，但跳过非功能测试与 mutation 全量（保留抽样）；不输出 release_gate_report。
* **L4**：Runner 定位失败用例 + 影响面回归；Gatekeeper 仅判定该 bug 是否 verified。

### 18.4 模式切换的强制提示（区分人触发 / Agent 触发）

每次 Agent 接到执行指令时，必须在执行前打印：

```text
将以 [L?] 模式执行
设计阶段：[新增/复核 N 条用例 | 跳过]
执行阶段：[选中 M 条用例（P0=a, P1=b, P2=c）]
影响面来源：[CodeGraph | local]
非功能测试：[启用 / 跳过]
单次上限：[X 条] —— 当前选择 [是否触发熔断]
触发来源：[human | agent | scheduled]
是否继续？(yes / 修改 / 取消)
```

**确认策略按触发来源区分**：

* **human 触发**（用户在对话中下达 `/qa ...`）：必须等待用户显式 `yes`。回复"修改"→ Agent 接受**扩充**（不接受缩减）。
* **agent 触发**（Dev Agent 或编排 Agent 在交接文件中要求执行）：从 `.qa-agent.yml` 读取 `auto_confirm` 配置：
  * `auto_confirm.modes` 列表中的模式（默认 `[L0, L4]`）→ 直接执行，但仍打印上述提示并写入 `qa/run/last.json` 以供审计。
  * 不在白名单的模式（默认 `L1/L2/L3`）→ Agent 不得自动执行，必须停下并发出**人工请示**：在 `qa/run/pending_confirm.md` 写入待确认事项，并退出本次流程，等下一次人触发。
* **scheduled / 批处理触发**（如夜间任务）：等同 agent 触发，但额外写入 `triggered_by: schedule` 字段供审计；超过 `auto_confirm.modes` 的模式同样必须停下请示。

**不变量**：

* `auto_confirm` 永远不允许包含 `L3`——L3 必须人工确认。
* 任何"自动确认"的执行，其 `qa/run/last.json` 必须包含 `confirmation: auto` 字段，便于事后审计。

---

## 19. 测试执行顺序（同模式内）与失败分类

Adapter 在执行选中集合时，遵循分层惰性：

```text
1. 静态检查 / Lint（若已配置）
2. 单元测试
3. 集成测试
4. 冒烟测试
5. 系统测试
6. 验收测试
7. 非功能测试(仅 L3)
8. 回归测试(针对修复轮)
```

### 19.1 失败分类与阻断策略

不能把"层级全部失败"一律当作代码问题阻断下层。Runner 必须把失败分为两类：

| 类别 | 触发特征 | 阻断行为 |
|---|---|---|
| **环境失败 / setup 失败** | 依赖未装、端口占用、容器启动失败、数据库连不上、Adapter `detect()` 返回缺失项、`setup` 钩子异常 | **不阻断后续层**；当前层标 `BLOCKED`；Runner 继续尝试下层（如下层不依赖此环境）；Gatekeeper 综合后给 `BLOCKED` 结论 |
| **测试失败** | 测试代码本身抛异常或断言失败 | 仅阻断下层条件：**该层 ≥ 80% 用例 fail** 时停止下层（默认阈值，可在 `.qa-agent.yml` 配 `layer_fail_threshold`） |

判定规则：

* 若失败率 ≥ 阈值且**全部为环境失败** → 标 `BLOCKED`，**不停下层**（除非下层也声明依赖同一环境）。
* 若失败率 ≥ 阈值且**全部为测试失败** → 停止下层。
* 若混合 → 仍停下层（保守），但报告中区分两类原因。
* 单条用例失败不阻塞同层其他用例（不变）。

### 19.2 失败分类的判定来源

Adapter `parse_report()` 必须把每条 fail 用例的 `failure_kind` 归一为 `env | test | unknown` 三档：

* `env`：异常栈含 `Connection refused / ECONNREFUSED / not found / port in use / docker / container failed to start` 等环境特征。
* `test`：断言失败或被测代码抛业务异常。
* `unknown`：无法判定 → 视同 `test`（保守阻断）。

Adapter 必须在自身 capabilities 中声明是否实现了 `failure_classification`；未实现的 Adapter 默认全部记为 `test`，并在报告中注明"失败分类未实现"。

---

## 20. 优先级规则

### P0（必须自动化，除非 Adapter 标记 not_applicable）

应用启动、登录/核心入口、核心业务主流程、数据保存、支付/订单/权限等高风险功能、关键状态流转、阻塞性 bug 回归。

### P1（应尽量自动化）

常用功能、重要异常路径、重要边界条件、常见用户操作、主要模块集成。

### P2（可自动化也可手动）

低频功能、视觉细节、辅助功能、非阻塞体验问题。

### P3（通常手动或低优先级）

文案、极低频边界、临时功能、探索性测试项。

### "不可自动化"判定

* 必须由 Adapter 主动标记 `automation.status: not_applicable` + 注明原因。
* QA-Designer **不允许**对 P0 用例直接标 not_applicable，必须由用户签字批准。
* not_applicable 用例统一进入 manual 视图，L3 通过前必须人工签字。

---

## 21. 与开发 Agent 的交互协议

QA Agent 与 Dev Agent 通过文件交接，不依赖聊天上下文。

```text
Dev Agent 完成功能
  ↓
通知 QA-Designer：feature_id + 关联需求文件 + diff 范围
  ↓
QA 流程按指定 L 档运行
  ↓
QA-Runner 输出 qa/bugs/*.yml
  ↓
Dev Agent 读取 bugs/ 并修复
  ↓
触发 L4：QA-Runner 验证修复 + Gatekeeper 决定 bug 是否 verified
  ↓
模块/迭代结束 → 触发 L2
  ↓
发版前 → 触发 L3 → release_gate_report.md
```

**强制约束**：

* Dev Agent 修复时不得直接修改 `qa/cases/`（除非用例本身错误，需走 Designer 流程）。
* Dev Agent 不得在 `bugs/<id>.yml` 中把状态从 `open` 改到 `verified`，verified 只能由 QA-Gatekeeper 写入。

---

## 22. AGENTS.md 推荐规则（项目级红线汇总）

```markdown
# QA Gate Rules（v2.1）

## 触发

任何模块/功能开发完成后必须以适当模式进入 QA 流程。

- 单点小改：/qa L0
- 一个功能完成：/qa feature <name>（L1）
- 一个模块/迭代完成：/qa module <name>（L2）
- 修复缺陷后：/qa bugfix <bug_id>（L4）
- 发版/验收前：/qa release（L3，唯一发版凭据）
- 跨 Agent 调用（Dev Agent → QA Agent）需在 `.qa-agent.yml` 启用 `auto_confirm` 才不阻塞。

## 禁止

1. 未运行测试就标记完成。
2. 删除失败测试来伪造通过。
3. 降低断言标准来伪造通过。
4. 跳过 P0 测试。
5. 只运行程序不做断言。
6. 只靠人工观察或 AI 口头判断宣布通过。
7. 修复 bug 后不执行回归测试。
8. 用 L0 / L1 / L4 的"PASS"作为发版凭据。
9. Agent 自行降档。
10. Agent 自行缩减用户提供的执行集。
11. 直接编辑视图文件（test_cases.md 等聚合文件）。
12. 直接删除用例文件（必须改 state: retired）。
13. 把状态 open → verified（必须由 Gatekeeper 写入）。
14. 安全测试用例（critical/high）waiver。
15. 在生产环境运行测试。
16. CodeGraph 调用失败时静默回退到 local（必须报告并请示）。
17. Gatekeeper 直接 trust Designer 的需求关联（必须独立溯源）。
18. 把环境失败（ENV_FAIL）当作普通 FAIL 让 Gatekeeper 直接判 PASS/FAIL。
19. 测试用例 YAML 中硬编码凭据（必须使用 `${env:NAME}` / `!secret name` 引用）。

## 质量门（仅 L3 适用）

- 全部 P0 用例通过；否则 FAIL。
- 核心冒烟测试通过；否则 FAIL。
- 项目可启动；否则 BLOCKED。
- final_test_report、regression_report、release_gate_report 三件齐备；否则 BLOCKED。
- 待人工签字的 manual 用例已签字；否则 BLOCKED。
- waivers.yml 中无过期项、`approved_by` 在白名单内；否则 BLOCKED。
- 覆盖率 / mutation 达标；否则 CONDITIONAL PASS 或 FAIL（按 .qa-agent.yml）。
- 安全测试 critical/high 全部修复或降级；否则 FAIL。
- 所有 stale 用例已复审；否则 BLOCKED。
- L3 维度切片若声明跳过维度，必须在 release_gate_report 显式登记，并由 `approved_by` 签字；未登记或未签字一律 BLOCKED。
```

---

## 23. Agent 创建提示词

```text
你现在要创建一个名为 AI Test Engineer 的 Agent。

它由三个独立角色组成（同基模型 + 不同上下文 + 不同提示词）：
- QA-Designer：测试架构师 + 高级测试工程师，负责风险分析、测试计划、用例设计、追踪矩阵、自动化映射。
- QA-Runner：自动化测试工程师，负责生成脚本、执行、收集失败、生成缺陷报告。
- QA-Gatekeeper：质量门负责人，负责回归选择、判定 PASS/FAIL/BLOCKED，签发结论。

它必须支持 5 档运行模式：
- L0 Spot / L1 Feature / L2 Module / L3 Release / L4 Bugfix
模式由用户显式指令触发，Agent 不得自行降档；L3 是唯一发版依据。

它必须支持的产物（结构化为权威源 + Markdown 视图）：
- qa/cases/<feature>/<case>.yml（schema 见文档第 9.2）
- qa/bugs/<bug>.yml
- qa/run/{last.json, history.json, selection.md}
- qa/waivers.yml（需人工签字）
- qa/test_plan.md / 矩阵 / 自动化映射 / final_test_report / regression_report / release_gate_report

它必须遵守的红线（见文档第 5.5、22 章）：
- 不得伪造、不得降档、不得缩减执行集、不得删除失败测试、不得绕过断言、不得在生产环境运行、安全用例不得 waiver、只有 Gatekeeper 能 verified。

影响面分析默认依赖 CodeGraph（mcp__codegraph__codegraph_explore / impact），仅在用户显式 .qa-agent.yml 设置 impact_analysis: local 时才回退；调用失败时不得静默回退，必须报告并请示。

预算：
- 不设 token 上限。
- 单次执行用例数上限按模式（默认 L0=10、L1=80、L2=500、L3=不限、L4=20），超限熔断暂停请示用户。

它采用通用核心 + 平台适配器结构（见 14 章接口契约）：
- qa-core：流程、模式、影响面、预算、对抗式 review、决策
- qa-web / qa-backend / qa-mobile / qa-desktop / qa-game：实现 detect / scaffold / generate / run / parse_report / collect_artifacts

请根据当前项目 .qa-agent.yml 自动选择测试框架并创建所需目录、模板、脚本和执行流程。如 .qa-agent.yml 不存在，先生成草稿请用户确认，再继续。
```

---

## 24. 路线图：MVP → v0.5 → v1.0 → v1.5

### 24.1 MVP（v0.1）—— 单角色、L1/L4、本地影响面、Web 或 Backend 之一

目标：先把闭环跑通，**容忍一些约束**。

* 单 Agent 简化执行（Designer 与 Runner 合并），但 Gatekeeper 必须独立。
* 仅支持 L1 / L4 两档；不支持 L3，故**不能用作发版依据**。
* 影响面用 local 模式即可（无需 CodeGraph）。
* 用例 YAML schema 必须与 9.2 一致，但允许 schema 字段只填关键项；`targets` 允许人工填。
* 必须有：用例库、bug 库、final/bug 报告、最简回归、`.qa-agent.yml` 草稿、25 章自检清单。
* 强制红线（5.5、5.7）必须就位。
* 适配器：**Web 或 Backend 二选一**完整实现，其余 stub（仅 detect 返回 not_supported）。
* 渐进式接入：必须支持 §10A 的 1–4 步（识别已有 tests/、生成 mapping、写 readonly 视图）。

完成判据：

```text
对一个真实小项目（Web 或 Backend）：
  能在 L1 模式下生成/复用用例库 + 自动化脚本 + 通过/失败结论
  能在 L4 模式下验证一次修复 + 影响面回归
  红线触发可被检出
  自检清单 12 项全部输出
```

### 24.2 v0.5 —— 三角色 + L0/L2 + CodeGraph 默认 + targets 自动维护

* 三角色完整拆分（Designer / Runner / Gatekeeper），含 §3.3 硬约束（独立溯源）。
* 增加 L0、L2 模式。
* 影响面默认 CodeGraph，缺失时按 8.4 处理；增加 8.5 漏选兜底（feature_id / regression_tags 补集）。
* 增加对抗式 review（仅 L2/L3）。
* `targets` 自动同步：用例 YAML 的 `targets.files` / `targets.symbols` 由 Adapter/Indexer 在 commit 时自动重写（rename/move），Designer 只填 `feature_id`。
* 段落语义指纹（5.9）替换裸 hash，避免排版微调引发 stale 风暴。
* `auto_confirm` 配置生效，Dev Agent 自动触发 QA 流程不阻塞。
* `.qa-agent.yml` 全字段支持，含 `production_guard.patterns`、`waivers.allowed_approvers`。
* 至少 2 个 Adapter 实现完整接口（Web + Backend）。
* CLI 输出规范落地（实施指南 §6）：终端摘要、彩色、进度、结论行。

完成判据：

```text
- /qa L0/L1/L2/L4 全部跑通，且 CodeGraph 不可用时按 8.4 报告而非静默
- 三角色独立上下文，Gatekeeper 报告含「未能验证的事项」与「建议人工复核」
- targets 字段在一次 git mv 后自动更新
- KPI（缺陷逃逸率、误报率等）能从 qa/feedback/ 回流并写入 history.json
```

### 24.3 v1.0 —— L3 + 非功能 + Web/Backend 完整 + 其余 stub

**v1.0 不再追求 5 个 Adapter 全部完整实现**——Mobile / Desktop / Game 在 v1.0 仅以 capabilities 声明 + 基本 detect/scaffold + 文档级模板交付，真实 run/generate 留到 v1.5/v2.0。

* 新增 L3 模式与发布质量门报告。
* L3 维度切片（7.1A）落地：可显式跳过非功能/兼容矩阵某些维度，必须在 release_gate_report 登记并签字。
* 完整非功能测试支持：性能、安全、兼容（按 .qa-agent.yml 矩阵）。
* Flaky 检测（仅失败用例隔离重跑）、覆盖率门槛、mutation 阈值（仅 L3 + 仅 diff）正式生效。
* Waiver 流程上线（含过期校验、commit 作者白名单、安全严重度分级）。
* **Web Adapter 与 Backend Adapter 完整实现 14 章 6 个接口 + capabilities 声明**。
* **Mobile / Desktop / Game Adapter 仅交付 stub**：能 `detect()` 返回项目类型与 capabilities = []；其余方法返回 `not_implemented`，并在报告中标注"该平台 Adapter 未完整实现，请使用 v1.5+"。
* Agent 自身 KPI 计算与回写（基于 qa/feedback/）。
* `qa/feedback/` 回流通道全面启用，KPI 不再为 0/0。

### 24.4 v1.5 —— Mobile + Desktop 完整

* Mobile Adapter 完整实现（含模拟器/真机 pool、能力声明 headless=false 时的兜底）。
* Desktop Adapter 完整实现（跨 OS 矩阵）。
* Game Adapter 仍为 stub。

### 24.5 v2.0 —— Game + 全场景成熟

* Game Adapter 完整实现（headless GUI、引擎集成、人工体验闭环）。
* 全部 KPI 指标稳态达标。
* 增加 mutation 抽样（仅 L2/L3，且仅对 diff 涉及代码）。
* `.qa-agent.yml` 全字段支持。
* 用例 `targets` 由 indexer 自动产出（§9.2A），Designer 只填 feature_id。
* 适配器：**Web + Backend 两个完整实现**，Mobile/Desktop/Game stub。
* 5.9 段落语义指纹（SimHash）上线。
* `mode_limits` 同时支持用例数和时间预算两个维度（11 章）。
* 对话/Agent 双触发模式（18.4）+ `auto_confirm` 配置。

### 24.3 v1.0 —— L3 + 非功能 + 反馈通道 + 异质模型

* 新增 L3 模式与发布质量门报告。
* 完整非功能测试支持：性能、安全、兼容（按 .qa-agent.yml 矩阵）；支持 7.1 维度切片。
* Flaky 检测（仅对失败用例隔离重跑）、覆盖率门槛、mutation 阈值正式生效。
* Waiver 流程上线（含过期校验、白名单、安全分级）。
* `qa/feedback/` 反馈通道上线，KPI（2.1）数据可回流并参与下一轮排序。
* 可选异质 `gatekeeper_model` 配置（3.3）。
* 适配器：**Web + Backend 完整、Mobile 基本可用**（detect/scaffold/generate/run），Desktop/Game 仍 stub。
* `capabilities` 矩阵全字段（14 章）由 detect() 自动声明。

### 24.4 v1.5 —— Mobile/Desktop/Game 完整化

* Mobile Adapter 完整实现（含模拟器/真机管理、capabilities.real_device）。
* Desktop Adapter 完整实现（含跨 OS 矩阵）。
* Game Adapter 完整实现（含场景测试、人工体验签字流）。
* Adapter 能力矩阵中所有 capability 至少一个 Adapter 支持。
* 路线图后续视实际接入项目反馈再决定。

> 说明：v1.0 不再承诺 5 个 Adapter 全部完成。Mobile/Desktop/Game 的工程量各自数月级，强行打包到 v1.0 会让发版无限延期。这里把它们正式后置到 v1.5。

---

## 25. 反伪造检查清单（Agent 自检）

每次 QA 流程结束前，Agent **必须**逐项自检并写入报告：

```text
[ ] 所有 P0 用例已实际执行（不是被 skip）
[ ] 所有 fail 用例都生成了 qa/bugs/<id>.yml
[ ] 没有用例文件被删除（retired 不算删除）
[ ] 没有断言被弱化（与上次版本对比）
[ ] flaky 用例未被计入 PASS
[ ] 安全用例（critical/high）无 waiver；medium/low waiver 有 PoC 不可达性证据
[ ] waivers.yml 无过期项；approved_by 已通过白名单校验
[ ] manual 用例待签字清单已列出
[ ] 影响面来源（CodeGraph / local）已声明；CodeGraph 漏选兜底已应用
[ ] 运行模式已声明，且与触发指令一致；未自行降档
[ ] 修复轮次未超 5.7 上限
[ ] 未能验证的事项已列出（不允许空）
[ ] Gatekeeper 已独立从原始需求摘录，矩阵需求列已重核
[ ] 环境/setup 失败未被误判为 FAIL（参见 19）
[ ] L3 切片维度未省略；任何省略已在 release_gate_report 中登记
[ ] 用例 YAML 中无明文凭据（test_data 凭据均使用 ${env:} 或 !secret 引用）
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
QA-Designer 增量更新用例库（结构化资产）
↓
基于 CodeGraph 影响面裁剪执行范围
↓
QA-Runner 执行 + 收集失败 + flaky 检测 + mutation 抽样
↓
受 5.7 上限保护的修复轮
↓
QA-Gatekeeper 决策（含 waiver / 人工签字校验）
↓
仅 L3 输出发布质量门结论
↓
允许或拒绝验收 / 发布
```

最终交付物的衡量标准：

```text
需求可追踪（每条用例绑定需求 + 段落 hash）
测试可设计（结构化 YAML，可 diff 可演进）
执行可裁剪（基于 CodeGraph 影响面）
执行可自动（Adapter 接口产物可重复）
失败可复现（结构化 bug 报告 + 工件）
修复可验证（仅 Gatekeeper 能 verified）
回归可重复（基于变更选回归集）
红线不可绕（自检清单 + waiver 流程）
交付有证据（仅 L3 决策有效）
```

