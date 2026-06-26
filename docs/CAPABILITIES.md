# TestAgent 完整能力清单

> 系统盘点 TestAgent 的全部能力载体。与 oec-ai-infra 不同，TestAgent 把能力主要
> 沉淀为**可测试的 Python 代码**（25 核心模块 + 21 CLI 命令 + 6 Adapter），
> prompt 文件只承载需要 LLM 推理的部分。本清单基于实际代码提取，非记忆。

> **能力总量**：21 CLI 命令 + 25 core 模块 + 6 Adapter + webui 子系统（7 模块）
> + 3 Agent/分册。187 单测守护。

---

## 一、五档运行模式（用户入口，`/qa` 命令路由）

| 命令 | 模式 | 用途 | 可发版 |
|------|------|------|--------|
| `qa l0 [scope]` | L0 Spot | 快速 sanity，10-30 秒 | ❌ |
| `qa feature <name>` | L1 Feature | 一个功能开发完 | ❌ |
| `qa module <name>` | L2 Module | 模块/迭代完成 | ❌ |
| `qa release` | L3 Release | 发版前完整质量门 | ✅ 唯一发版凭据 |
| `qa bugfix <ref>` | L4 Bugfix | 修复缺陷后验证 | ❌ |

## 二、流程控制命令

| 命令 | 职责 |
|------|------|
| `qa init` | 引导式初始化：自动扫描项目、生成 `.qa-agent.yml` 配置草稿 |
| `qa status` | 查看当前测试覆盖状态（用例数/通过率/open bugs/覆盖率） |
| `qa retry` | 重跑上次的 selection（修复后再验证） |
| `qa resume` | 恢复中断的 L3 运行（检查点恢复） |
| `qa finalize` | 手动修复后更新状态（会话感知，杜绝无参数洗白） |

## 三、Subagent 内部命令（机械工作，确定性执行）

| 命令 | 职责 | 对应 oec skill |
|------|------|---------------|
| `qa prepare` | 影响面分析 + 生成 selection.md（不执行） | impact-scope-analyzer |
| `qa scaffold` | 调用 Adapter 生成测试脚本骨架 | （TestAgent 特有） |
| `qa execute` | 执行选中用例（真实调用 Adapter.run） | api-test-executor |
| `qa judge` | Gatekeeper 算法判定（L0/L4 用） | testcase-review 部分 |
| `qa resolve-bugfix` | 解析 bug 引用返回 bug_id | （特有） |
| `qa discover-docs` | 扫描目录按文件名分类文档 | （特有，含 spec-kit 支持） |
| `qa parse-req` | 解析需求文档（PDF/DOCX/TXT/MD + 图片） | requirement-parser ✅迁移 |
| `qa scan-api` | 扫描 Spring MVC 源码提取接口清单 | api-scanner ✅借鉴 |
| `qa coverage` | JaCoCo 覆盖率 + Gap 缺口分析 | api-coverage-analyzer ✅借鉴 |
| `qa report` | 从 last.json+history 生成结构化报告（HTML/JSON/MD+趋势） | build_test_report ✅借鉴 |
| `qa validate-kotlin` | 静态校验生成的 Kotlin 代码结构 | （特有，防编译阻塞） |

## 四、核心引擎模块（qa_agent/core/，25 个）

### 流程编排
- `engine.py` — 模式路由核心（L0-L4 分支调度）
- `engine_repair.py` — L3 修复循环编排
- `designer_runner.py` — Designer+Runner：用例设计→脚本生成→执行→收集失败
- `gatekeeper.py` — Gatekeeper 独立判定（PASS/CONDITIONAL/FAIL/BLOCKED）
- `state_manager.py` — 状态管理（last.json/baseline.json/history.jsonl/selection.md）

### 影响面与发现
- `impact_analysis.py` — 影响面分析（CodeGraph/local，含 scope 兜底）
- `codegraph.py` — CodeGraph 代码图封装（CLI 直调 + MCP 回退）
- `requirement_discovery.py` — 需求文档自动发现（docs/ai-docs/spec-kit/BMAD）
- `requirement_parser.py` — 需求文档解析（PDF/DOCX/TXT/MD + 图片）✅迁移
- `test_discovery.py` — 已有测试文件自动索引

### 质量分析
- `coverage_analyzer.py` — JaCoCo 覆盖率 + Gap 分类 ✅借鉴
- `api_scanner.py` — Spring MVC 接口扫描 ✅借鉴
- `mutation.py` — 变异测试
- `flaky.py` — Flaky 测试检测
- `nonfunctional.py` — 非功能测试调度（依赖审计/静态安全/性能/兼容）
- `e2e_evidence.py` — E2E 执行证据检查（防假 E2E）
- `report_parser.py` — 报告解析（vitest/playwright/pytest）
- `report_generator.py` — 结构化报告生成 ✅借鉴

### 缺陷与修复
- `bug_resolver.py` — Bug 引用解析
- `repair_loop.py` — 修复循环配置

### 基础设施
- `config.py` — 配置加载
- `paths.py` — 产物路径约束 ✅借鉴
- `types.py` — 核心数据结构（TestCase/Bug/RunResult 等）
- `yaml_serializer.py` — YAML 序列化
- `init_wizard.py` — 引导式初始化

## 五、Adapters（多端测试适配，qa_agent/adapters/）

| Adapter | 能力 |
|---------|------|
| `web/` | Playwright E2E + Vitest 单元；e2e_enhancer 运行时 DOM 探测 |
| `backend/` | pytest + requests；api_executor（401处理/HTML报告/脚本自愈） |
| `mobile/` | 三轨：Espresso/UiAutomator（instrumented）+ Maestro（UI flow）+ Robolectric（unit）；@AI-FILL 自动填充；Kotlin 静态校验 |
| `maestro/` | Maestro YAML flow 生成 + 执行 |
| `generic/` | 通用框架兜底 |

## 六、WebUI 子系统（qa_agent/webui/，7 模块）

- `analyzer/` — Vue 前端静态分析（路由→组件→字段/按钮/API 知识图）✅迁移 W1
- `explorer/` — 运行时页面探测（登录后 DOM 抓取）
- `dom/` — DOM 元素提取
- `executor/` — 测试执行 + 深度校验
- `login/` — 登录态处理
- `reporter/` — WebUI 报告
- `validators/` — 选择器/测试深度校验

## 七、Agent 体系（.claude/，prompt 层）

| 文件 | 职责 | 加载时机 |
|------|------|---------|
| `commands/qa.md` | `/qa` 命令入口 + 5 档路由 + 6 步流程 + W2需求预审 | 始终 |
| `agents/qa-test-engineer.md` | Designer+Runner（设计+执行+@AI-FILL+数据流追踪+10维度自检） | L1/L2/L3 |
| `agents/qa-gatekeeper.md` | 独立判定（9 条硬规则 + 6 追问 + waivers） | L1-L4 |
| `agents/guidance/backend-api.md` | API维度矩阵+接口扫描+调用链/SQL+场景设计6维度+pytest规范+双轨覆盖 | 测后端时按需 Read |
| `agents/guidance/web-frontend.md` | Web维度矩阵+Vue前端分析+选择器质量 | 测前端时按需 Read |
| `agents/guidance/mobile.md` | 移动维度矩阵+三轨工具+Android填充手册+source set判定 | 测移动端时按需 Read |

---

## 八、核心防护机制（区别于普通测试工具）

1. **7+2 条 Gatekeeper 硬规则**（不可协商）：执行证据/P0P1不跳过/E2E不跳过/失败一致性/
   前端错误零容忍/L3规模/假E2E检查/选中即执行一致性/@AI-FILL填充完整性
2. **@AI-FILL 完全自动化**：Adapter 生成半成品 + Designer 读源码填真实代码，不留 TODO
3. **四端假绿守卫**：Espresso/Robolectric/iOS/Flutter/RN 未填充即 fail，非静默通过
4. **数据流追踪**：防"测试通过却漏主流程"（步骤间数据传递断裂）
5. **会话感知 finalize**：杜绝无参数洗白，verdict 由真实状态推导
6. **scope 兜底 + 多 feature**：容错自然语言输入 + 跨 feature 选用例
7. **Kotlin 静态校验**：编译前拦截 val 重复/import 缺失/括号不配平/@AI-FILL 残留

## 九、能力来源标注

- ✅迁移/借鉴自 oec-ai-infra：requirement_parser / api_scanner / coverage_analyzer /
  report_generator / paths / webui/analyzer + A2-A5/D1/W2 prompt 增强
- 🔵 TestAgent 特有（oec 无）：@AI-FILL 自动填充 / Kotlin 校验 / Bugfix 修复循环 /
  Flaky 检测 / 五档模式分级 / 移动端三轨方案 / scope 兜底

---

## 与 oec-ai-infra 的本质区别

| | oec-ai-infra | TestAgent |
|---|---|---|
| 能力载体 | 59 个 prompt skill | 25 Python模块 + 21 CLI + 5 prompt |
| 执行性质 | LLM 编排（非确定性） | 代码确定性执行 + LLM 仅推理 |
| 质量保障 | prompt 规范 | 187 单测 + 静态校验 |
| 平台依赖 | UTP/Midscene/platform-gateway | 本地优先，无平台依赖 |
| 定位 | 企业级测试平台集成 | 个人/小团队本地快速验证 |

**结论**：文件数量差异源于工程哲学不同（prompt 即能力 vs 能用代码就不用 prompt），
不反映能力差距。TestAgent 的能力以可测试的确定性代码为主。
