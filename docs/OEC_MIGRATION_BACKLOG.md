# TestAgent 后续可实施能力清单（Backlog）

> 本文档记录从 oec-ai-infra 对比分析中识别出的、**后续可按需实施**的能力点。
> 已完成的（需求解析/路径约束/报告增强/覆盖率分析）不在此列。
> 每项标注价值、迁移方式、依赖，便于以后按优先级捡起。

> **进度更新**：W1 前端静态分析（commit 含 `qa_agent/webui/analyzer/`）、
> A1 接口扫描（`qa_agent/core/api_scanner.py`）**已完成**，下方对应小节标 ✅。

---

## 一、API 测试输入流水线（最高杠杆，三件套）

> **背景**：TestAgent 的 `enhanced_execute_with_auth.py` 已在消费 `api_definition.json` 算覆盖率，
> 但**没有任何工具生成这个文件**——接口发现/定义/场景设计这条"输入流水线"是空白，
> 全压在 subagent 临场推理。补齐后 API 测试从"猜接口"升级为"基于真实接口清单+调用链+SQL"。

### A1. 接口自动发现（Spring MVC 扫描）★P0 高价值 ✅ 已完成
- **实现**：`qa_agent/core/api_scanner.py`（源码模式正则解析）+ `scan-api` CLI +
  接入 qa-test-engineer.md 后端章节。输出对齐 `{'apis':[...]}` 消费端结构。
- **oec 怎么做**：`api-scanner` 从 JAR/class/源码三种输入提取 `@RestController`/`@GetMapping` 注解，
  输出接口路径/方法/参数/请求体/响应体的标准 JSON，自动从 application.yml/pom.xml 提取服务名。
  源：`oec-infra/skills/test/skills/api-scanner/`（带 jar）
- **TestAgent 现状**：无。后端用例靠 subagent 读源码"猜"接口，无接口清单产物。
- **迁移方式**：借鉴重写（Java JAR 与 TestAgent 多语言定位冲突，用 Python 解析注解，
  或对 Java 项目直接 shell 调用其 JAR）。
- **承载点**：`qa_agent/adapters/backend/adapter.py`

### A2. 接口定义生成 + 调用链/SQL 追踪 ★P0 高价值 ✅ 已完成
- **实现**：qa-test-engineer.md 后端章节新增"接口定义增强"步骤（纯 prompt，
  用 CodeGraph callees 追调用链 + 读 Mapper XML/注解提 SQL + 参数映射 + testPoints）。
- **oec 怎么做**：`api-definition-generator` + `api-source-analyzer` 追踪 Controller→Service→Dao 调用链，
  提取 SQL + 分析"WHERE 字段哪些需接口参数提供"，生成含 testPoints/businessRules/databaseQueries/
  serverGeneratedFields 的 `api_definition.jsonl` + `db_schema.md`。
- **TestAgent 现状**：有 `codegraph.py` 做符号级调用链，但不产出接口定义，无 SQL/参数映射。
- **迁移方式**：借鉴提示词为主 + 复用标准 JSON 格式规范，叠加在现有 codegraph 上。
- **依赖**：A1 产物更佳

### A3. 场景设计 6 维度 + scenario.md 产物 ★P1 高价值 ✅ 已完成
- **实现**：qa-test-engineer.md 后端章节新增"场景设计 6 维度 + scenario.md"步骤
  （6 维度表 + 测试点清单 + 覆盖自检 + 未覆盖列表，产出 qa/run/scenario.md）。
- **oec 怎么做**：`api-scenario-designer` 按"核心流程/CRUD闭环/业务规则跨接口/数据一致性/
  跨模块联动/关键业务异常"6 维度提取测试点清单，设计场景 + 回填覆盖统计，输出标准 scenario.md。
- **TestAgent 现状**：部分。`qa-test-engineer.md` 有后端维度矩阵但是散文式提示词，
  无结构化测试点清单、无覆盖回填、无 scenario.md 产物。
- **迁移方式**：借鉴重写进 `qa-test-engineer.md` 的 API 设计章节，落地 `qa/backend/scenario.md`。
- **依赖**：A2

### A4. 双轨覆盖分析（需求侧×代码侧交叉找漏场景）★P2 中价值
- **oec 怎么做**：`api-scenario-enhancer` 拿 scenario.md 的"需求侧测试点"和 jsonl 的"代码侧 testPoints"
  做矩阵交叉，识别"双轨都未覆盖"的真漏场景。coverage-analyzer 的双轨分级（🔴需求未覆盖/
  🟠代码未触发/🟡仅代码侧）同源。
- **TestAgent 现状**：部分。`coverage_analyzer.py` 有 JaCoCo 单轨 Gap 分类，但无双轨
  （缺 A2 的 testPoints 和 A3 的需求测试点清单作输入）。
- **迁移方式**：借鉴提示词。
- **依赖**：**强依赖 A2+A3 先落地**，否则无数据可交叉。

### A5. 单接口/场景脚本生成规范 + DB 元数据校验 ★P1 中价值
- **oec 怎么做**：`api-endpoint-test-generator`/`api-scenario-test-generator` 有"一接口一文件"、
  `fixture scope="class"` 防坑规范、`db_metadata_validation.md`（连库校验表名/字段、SQL 加反引号）。
- **TestAgent 现状**：部分。`backend/adapter.py` 只生成 `assert True` 占位骨架，真内容靠 subagent；
  有 DB 查询捕获但无 DB 元数据预校验。已有 `script_auto_fixer` 兜底。
- **迁移方式**：仅借鉴提示词（生成规范并入 qa-test-engineer.md，DB 校验可选做小工具）。

---

## 二、WebUI 测试能力

### W1. 前端静态源码分析（Vue 路由→组件→字段/按钮/API 知识图）★P0 高价值 ✅ 已完成
- **实现**：迁移整个包到 `qa_agent/webui/analyzer/`（analyze + parsers/ + extractors/）+
  接入 qa-test-engineer.md Web 前端章节。`python -m qa_agent.webui.analyzer.analyze` 可直接调。
- **oec 怎么做**：`web-uitest-frontend-analyzer`（带 `scripts/analyze.py`）读 Vue 源码，
  按 test-url 前缀预筛路由，输出 `frontend_knowledge.json`：路由→组件、form_fields[].label/type、
  按钮、调用的 API、状态机条件、element_index。支持 monorepo/微前端。目的"避免 LLM 猜业务行为"。
  源：`oec-infra/skills/test/skills/web-uitest-frontend-analyzer/scripts/analyze.py`
- **TestAgent 现状**：无静态分析。`web/e2e_enhancer.py` 只有**运行时** Playwright 探测
  （必须先成功登录才能拿元素，且只抓当前页 DOM，拿不到路由表/组件字段语义/API 调用关系）。
- **补全价值**：解决两痛点：(1) 登录失败/复杂前置时运行时探测拿不到元素，静态分析无此依赖；
  (2) 给断言生成提供"字段中文名/业务规则"语义。与运行时探测形成"静态知识+动态元素"互补。
- **迁移方式**：**复用代码包**（核实：analyze.py 非单文件，依赖同级 `parsers/`
  (vue_router_parser/vue2_component_parser) + `extractors/`(component_knowledge/
  ui_surface_extractor) 共 5 个模块；经核实无平台耦合——grep 命中的 platform/token
  全是 `sys.platform=="win32"`/文档注释/示例文本误报）。移植整个 scripts/ 包为
  `qa_agent/webui/analyzer/`，再把 frontend_knowledge.json 喂给 e2e_enhancer。
- **配套**：`uitest-source-fetcher`（git clone 前端仓库）可一并轻量移植作前置。

### W2. 需求预审（执行前 6 维度门禁）★P2 中价值
- **oec 怎么做**：`web-uitest-requirement-reviewer` R 模式 6 维度（目标页面/关键操作/完成标志/
  数据字段/异常场景/环境信息），分 ✅充分/⚠️轻微缺失自动扩写/❌严重缺失暂停补充。
- **TestAgent 现状**：无。Gatekeeper 是**执行后**判定，没有**执行前**的需求质量门禁。
- **迁移方式**：仅借鉴提示词（6 维度清单移入 agent/command，去掉 Midscene 特定术语检测）。

### W3. 需求生成模板（5 模式专家模板）★P3 低价值
- **oec 怎么做**：`web-uitest-requirement-generator` R/S/C/M/U 五模式模板。
- **TestAgent 现状**：无，但 qa-test-engineer.md 已有自己的用例设计流程。
- **迁移方式**：仅借鉴提示词，且模板强绑 Midscene 范式，与 Playwright 不完全契合，
  择优借鉴"要素提取表/预断言表"结构即可。

---

## 三、测试设计与评审（来自第一轮对比报告）

### D1. 测试用例评审 10 维度 ★P2 中价值
- **oec 怎么做**：`testcase-review` 从 10 维度（完整性/可追溯性/数据有效性/边界覆盖/
  前置后置/步骤清晰/预期明确/异常覆盖/独立性/可维护性）识别用例质量问题，
  输出问题清单 + 修订稿 + metadata.json。
- **TestAgent 现状**：Gatekeeper 有 9 条硬规则，但维度不如 oec 系统化。
- **迁移方式**：借鉴 10 维度清单增强 Gatekeeper 检查项（不照搬报告生成，保持轻量）。

### D2. 智能测试计划生成器 ★P3 低价值（需求驱动）
- **oec 怎么做**：`smart-test-plan-generator` 需求 → 测试策略+质量目标+里程碑。
- **TestAgent 现状**：无。但 TestAgent 是"功能级快速测试"，不面向完整测试方案编写。
- **迁移方式**：暂缓，除非要做企业级测试管理。

---

## 四、PCUI 桌面测试链路 ★P3（需求驱动）

- **oec 怎么做**：6 个 skill（session-management/env-setup/case-parser/test-runner/
  report-generator/test-replayer）做 Windows 桌面应用自动化（@midscene/computer + Vitest）。
- **TestAgent 现状**：无 PCUI 场景。
- **迁移方式**：**需求驱动** —— 有实际 Windows 桌面应用测试项目再做。
  注意 oec 的 PCUI 执行依赖 @midscene/computer（AI 视觉），与 TestAgent 本地确定性优先理念
  需评估；可考虑改用 WinAppDriver/pywinauto 等确定性方案。

---

## 五、明确不迁移（架构理念冲突）

- **UTP 平台集成系列**（utp-apis/utp-coverage-batch/utp-test-plan/utp-test-report/utp-ai-report）：
  强依赖讯飞内部测试平台，TestAgent 本地优先 + Claude Code 扩展，理念冲突。
- **所有 Midscene/platform-gateway OAuth 执行链路**（web/mobile 的 session-init/auth-get/
  task-submit/status-poll/import）：平台耦合，TestAgent 本地直跑 Playwright/Espresso。
- **api-impacted-case-finder**：依赖 UTP 平台查存量用例。
- **已移植无需重做**：api-test-executor（→ enhanced_execute_with_auth+conftest_plugin）、
  api-coverage-analyzer 单轨内核（→ coverage_analyzer.py）、api-code-diff-analyzer（→ impact_analysis.py）。

---

## 推荐实施顺序（按价值×成本）

| 批次 | 能力 | 价值 | 成本 | 理由 |
|---|---|---|---|---|
| 第一批 | W1 前端静态分析 | 高 | 低 | analyze.py 可整体复用，无平台耦合，补运行时探测短板 |
| 第一批 | A1 接口发现 + A2 接口定义 | 高 | 中 | API 输入流水线源头，打通"猜接口→真实清单"，A2 依赖 A1 |
| 第二批 | A3 场景设计 scenario.md | 高 | 中 | 依赖 A2；把 Gatekeeper 防漏场景固化成可检产物 |
| 第二批 | A5 脚本生成规范 | 中 | 低 | 纯提示词，降 subagent 生成 bug 率 |
| 第三批 | A4 双轨覆盖 | 中 | 中 | 强依赖 A2+A3，先决条件满足后做 |
| 第三批 | D1 评审 10 维度 / W2 需求预审 | 中 | 低 | 纯提示词增强，前置质量门禁 |
| 按需 | D2 测试计划 / PCUI 链路 | 低 | 高 | 需求驱动，有实际场景再做 |

---

*生成于 oec-ai-infra 测试体系对比分析。已完成项见 commit c584c59/ed2da98/d72683f/ef10c7b。*
