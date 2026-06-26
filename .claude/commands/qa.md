---
description: AI Test Engineer Agent - 五档测试模式（L0/L1/L2/L3/L4）+ 引导式初始化
argument-hint: [init | feature <name> | bugfix <ref> | module <name> | release | retry | resume | status] [args...]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, Agent
---

# /qa - AI Test Engineer Agent v3.0 Solo Edition

你正在执行用户的 `/qa $ARGUMENTS` 命令。这是一个**测试工程师 Agent**，目标是把 AI 写的代码从"看起来能跑"升级为"经过真实测试验证"的质量。

## 项目架构定位

本项目是 **Claude Code 扩展**：
- Python 工具层：机械工作（YAML 读写、Adapter 执行、影响面分析、状态持久化）
- 你（Claude Code）：完成 LLM 推理工作（设计用例、生成脚本、判定结论）
- Subagent 协作：Designer+Runner 与 Gatekeeper 通过文件交接（防确认偏差）

## 命令路由

解析 `$ARGUMENTS` 第一个 token：

| 命令 | 模式 | 行为 |
|---|---|---|
| `init` | - | 引导式初始化 |
| `feature <name> [需求文档在 <path>]` | L1 | 一个功能开发完后跑测试 |
| `bugfix <ref> [需求文档在 <path>]` | L4 | 修复缺陷后验证 |
| `module <name> [需求文档在 <path>]` | L2 | 模块/迭代完成 |
| `release [需求文档在 <path>]` | L3 | 发版前完整质量门 |
| `retry` | - | 重跑上次 selection |
| `resume` | - | 恢复中断的 L3 |
| `status` | - | 查看当前覆盖状态 |
| `finalize [verdict] [pass_rate]` | - | 手动修复后更新状态 ⭐ |
| `L0` / `L0 <scope>` | L0 | 单点 sanity 快速验证 |

### 动态需求文档路径（重要）

用户可在命令中**自然语言指定**文档目录，例如：

- `/qa feature 短信绑定 需求文档在 doc/v2026-06-17-当前版本文档/`
- `/qa feature 登录 文档在 /D:/AndroidProject/ClawBoxClient/ai-docs/prd/`
- `/qa feature 支付 doc-path=/path/to/docs`
- `/qa module 订单 --docs ai-docs/prd/`

**解析策略**：
- 优先匹配 `需求文档在 <path>` / `文档在 <path>` / `--docs <path>` / `--docs-path <path>` / `doc-path=<path>`
- 提取 path 后传给 `python -m qa_agent.cli.main prepare --docs-path <path>`
- 如有多个目录，可多次传 `--docs-path`

**文档分类**（subagent 自动完成）：
- **Spec-kit 标准文件名优先**（精确匹配）：`spec.md` → 需求，`plan.md`/`data-model.md`/`research.md` → 设计，`quickstart.md` → 验收，`tasks.md` → 参考材料
- 子目录名优先：`prd/` → 需求，`design/architecture/` → 设计，`api/apis/contracts/` → API，`acceptance/verification/` → 验收
- 文件名关键词：含 `requirement/prd/spec/需求/规格` → 需求；含 `design/architecture/技术方案/架构` → 设计
- 汇总文件优先：`*-all.md` / `*-overview.md` / 含 "总/全量/汇总" 中文名
- 无法分类的文档归入 `unclassified`，但仍作为参考材料

## 通用执行流程（L1/L2/L3/L4）

### 步骤 1：环境准备

1. 检查 `.qa-agent.yml` 是否存在
   - 不存在 → 提示用户 `/qa init`
2. 检查 CodeGraph 是否可用（`codegraph status` 或 `mcp__codegraph__codegraph_explore`）
   - 不可用 + 配置 `impact_analysis: codegraph` → 询问用户：
     a) 等待修复（默认，如先跑 `codegraph init` 建索引）
     b) 切换到 `impact_analysis: local`
     c) 取消运行

### 步骤 2：影响面分析 + 需求文档发现（机械工作 - 调用 Python 工具）

**基础调用**（仅自动发现需求文档）：
```bash
python -m qa_agent.cli.main prepare --mode <L?> --scope <scope>
```

**动态文档路径**（用户在命令中指定了 `需求文档在 <path>`）：
```bash
python -m qa_agent.cli.main prepare --mode <L?> --scope <scope> --docs-path "<path>"
# 多个目录：
python -m qa_agent.cli.main prepare --mode <L?> --scope <scope> \
  --docs-path "doc/v2026-06-17-当前版本文档/" \
  --docs-path "ai-docs/architecture/"
```

**预先扫描目录**（仅探查目录内容，不执行流程）：
```bash
python -m qa_agent.cli.main discover-docs --path "doc/v2026-06-17-当前版本文档/"
# 返回分类后的文档清单 JSON
```

**解析二进制需求文档**（PDF / DOCX / DOC，普通 Read 读不了）：
```bash
# 把 PDF/DOCX 转成纯文本(图片位置用 [图片N] 占位符)
python -m qa_agent.cli.main parse-req --file "docs/PRD.pdf" --content-only
# 完整 JSON(含图片磁盘路径,供按需 Read 分析图片):
python -m qa_agent.cli.main parse-req --file "需求.docx"
```
⚠️ 当 `docs.primary`/`all_docs` 里出现 `.pdf`/`.docx`/`.doc` 文件时，
**不要直接 Read**（会乱码），必须先用 `parse-req` 转成文本再读。
依赖按需安装：`pip install python-docx mammoth markdownify pdfplumber PyMuPDF`

输出 JSON 包含分类结果：
```json
{
  "primary": "doc/v2026-06-17-当前版本文档/产品需求文档.md",
  "design": "doc/v2026-06-17-当前版本文档/技术方案.md",
  "api": "doc/v2026-06-17-当前版本文档/接口设计.md",
  "acceptance": "specs/002-xxx/quickstart.md",
  "specs": [...],
  "all_designs": [...],
  "all_apis": [...],
  "all_docs": [...],
  "unclassified": [...]
}
```

⚠️ **重要：`design`/`api`/`acceptance` 字段只是"每类的主文档"（单个文件）。**
spec-kit 这类框架会把设计拆在 `plan.md`/`data-model.md`/`research.md` 多个文件里，
把验收拆在 `quickstart.md`/`validation-checklist.md` 里。因此**必须读完整列表**：
- 设计文档：读 `all_designs` 里的**全部**文件，不能只读 `design` 一个
- API 文档：读 `all_apis` 里的全部文件
- 未分类文档（`unclassified`）：**也要作为参考材料阅读**，里面常有 `tasks.md`、
  约束清单等关键上下文。不得因为"没分类"就跳过。

读取 `qa/run/selection.md` 获得用例列表，读取 `docs.primary` 获得主需求文档，
读取 `docs.all_docs` 获得本次范围内的**全部**文档清单。

### 步骤 3：用户确认

打印预估给用户：

```text
将以 L1 模式执行
设计阶段: 增量补该功能用例
执行阶段: 选中 N 条用例（P0=a, P1=b, P2=c）
影响面来源: CodeGraph / local
非功能测试: 跳过 / 启用
单次上限: X 条
是否继续？(yes / 修改 / 取消)
```

等待用户确认（**强制约束：人触发模式必须等 yes**）。

### 步骤 4：Designer+Runner 阶段（委派 Subagent）

**L0/L4 不需要委派**：直接读已有用例库，跳过设计。

**L1/L2/L3 委派 qa-test-engineer**：

**Agent 文件查找顺序**（依次尝试，找到即用）：
1. `~/.claude/agents/qa-test-engineer.md`（全局，CCM 优先）
2. `.claude/agents/qa-test-engineer.md`（项目级，官方 Claude Code）
3. `~/.claude-ccm/agents/qa-test-engineer.md`（CCM 备用）

调用 Agent 工具（优先）或 Task 工具：
```
Agent(
  subagent_type="qa-test-engineer",
  description="L<?> 设计用例 + 执行测试",
  prompt="""
  阅读 qa-test-engineer.md 中的指令（按上述查找顺序）。
  
  本次运行：
  - 模式: L<?>
  - 范围: <scope>
  - 已选用例 (qa/run/selection.md): <内容>
  - 主需求文档: <docs.primary>
  - 设计文档（全部，逐个读）: <docs.all_designs 列表，无则用 docs.design>
  - API 文档（全部）: <docs.all_apis 列表，无则用 docs.api>
  - 验收文档: <docs.acceptance>
  - 未分类参考材料（必须阅读）: <docs.unclassified 列表>
  - 本次范围全部文档: <docs.all_docs 列表>
  - 项目类型: <type>
  - 测试框架: <frameworks>
  - 用例库状态: <空 | N 条已有用例>

  ⚠️ 文档阅读要求：
  - 不要只读主需求文档。设计/API/验收/未分类清单里的文件**逐个读完**。
  - spec-kit 框架的设计内容拆在 plan.md/data-model.md/research.md，
    验收拆在 quickstart.md/validation-checklist.md，**全部都要读**。
  - unclassified 里的 tasks.md、约束清单等是关键上下文，不得跳过。
  
  按照规范完成：
  1. 设计用例（写入 qa/cases/<feature_id>/<id>.yml）
  2. 调用 Adapter 生成脚本（python -m qa_agent.cli.main scaffold --case <id>）
  3. 主动启动环境 + 执行测试（包括 E2E）
  4. 收集失败 → qa/bugs/<id>.yml
  
  完成后告知"已完成 X 条用例设计 + 执行，Y 个失败"
  """
)
```

⚠️ **如果当前环境不支持 Agent 工具**（如 CCM/DeepSeek），直接在当前上下文执行 qa-test-engineer.md 的完整指令，但必须：
- 先按上述查找顺序找到 qa-test-engineer.md（如果都找不到，输出错误并退出）
- 严格按其中规则操作
- 完成后再阅读 qa-gatekeeper.md 做独立判定（同样按查找顺序）

⚠️ **L3 模式的 E2E 测试是强制项**，不允许只做代码审查就标"未执行"。
必须按 qa-test-engineer.md 中"E2E 测试环境启动规则"主动启动环境并执行：
- 读 package.json 找 dev/start 命令 → 后台启动
- 等待端口就绪
- 跑 Playwright/Cypress 测试
- 测试完成后清理后台进程
```

### 步骤 5：Gatekeeper 阶段（委派独立 Subagent）

**L0 不委派**（用算法判定即可）。

**L1/L2/L3/L4 委派 qa-gatekeeper**（独立上下文，防确认偏差）：

调用 Task 工具：
```
Task(
  subagent_type="qa-gatekeeper",
  description="独立判定 L<?> 测试结论",
  prompt="""
  阅读 .claude/agents/qa-gatekeeper.md 中的指令。
  
  独立判定本次运行：
  - run_id: <id>
  - 模式: L<?>
  
  关键约束：
  - 你不能看 Designer 的推理过程
  - 必须独立从 docs/ 读取需求文档
  - 必须重新摘录需求条款，不 trust qa/cases/*.yml 的 requirement_ids
  - 必须列出"未能验证的事项"
  
  输出 PASS/CONDITIONAL PASS/FAIL/BLOCKED 到
  qa/final_test_report.md（L1/L2）或
  qa/release_gate_report.md（L3 必填）
  """
)
```

### 步骤 6：呈现结果给用户

读取 `qa/final_test_report.md`（或 `release_gate_report.md`），按格式输出：

```
✅ L<?> 完成: <verdict>

执行统计:
  总数 N / 通过 P / 失败 F

失败用例（如有）:
  - BUG-XXX: <title> (TC-XXX, severity=<sev>)
    位置: <file:line>

建议下一步:
  - <根据 verdict 给出建议>
```

**可选：生成结构化报告**（HTML/JSON + 历史趋势对比）：
```bash
# 数字确定性计算(防 LLM 拍脑袋)，支持对比上次执行的通过率趋势
python -m qa_agent.cli.main report --format markdown          # 人读
python -m qa_agent.cli.main report --format html --output qa/reports/<run_id>.html
python -m qa_agent.cli.main report --format json              # 供 CI 解析
```
用户要详细报告或需要看趋势时用此命令，比手动拼装统计更准。

#### ⚠️ 模式适配性提示（防"拿 L1 当主流程门禁"）

**背景**：StudySkill 事故——用户跑 L1 PASS 后真实使用立刻撞到主流程断链（LLM 分析结果没传到概念预热）。L1 是单功能级，本就不验证跨"创建→分析→预热"的端到端数据流，PASS 不代表主流程没断。

**L0/L1/L4 完成后，若本次 feature 涉及跨页面/跨服务/跨步骤的数据流**，必须在结果末尾附加：

```
⚠️ 模式覆盖范围提示
本次为 L<0/1/4> 模式，仅验证<单功能/受影响路径>，未覆盖端到端主流程。
检测到本功能涉及跨步骤数据流（如 <A产出> → <B消费>），
此类「步骤间数据传递」缺陷需 L2（模块集成）或 L3（端到端）才能门禁。
PASS 不代表完整主流程可用，建议补跑：/qa module <name> 或 /qa release
```

判断"是否涉及跨步骤数据流"：看该 feature 是否有"一个步骤的产出被另一步骤消费"（如表单→保存→详情页、分析→持久化→下游使用）。有则必提示，不要让用户误以为 L1 PASS = 主流程没问题。

## 各命令详细处理

### `/qa init`

引导式初始化。直接调用 Python：
```bash
python -m qa_agent.cli.main init
```

读取输出，提示用户下一步。

### `/qa feature <name>` (L1)

执行通用流程，mode=L1，scope=<name>。

### `/qa bugfix <ref>` (L4)

`<ref>` 支持多种形式：
- `BUG-XXX` - 已登记的 bug
- `TC-XXX-NNN` - 用例 ID（反查关联 bug）
- `#NNN` - issue 编号
- 关键词或自然语言（< 30 字符模糊匹配，长描述创建新 bug）

调用：
```bash
python -m qa_agent.cli.main resolve-bugfix --ref "$ref"
```

得到 bug_id，然后执行通用流程，mode=L4，scope=bug_id。

### `/qa module <name>` (L2)

执行通用流程，mode=L2，scope=<name>。

### `/qa release` (L3)

**L3 强制约束**：
- 需求文档必须存在（否则 BLOCKED）
- 8 phase 检查点完整执行
- 非功能测试按配置执行（默认开依赖审计 + 静态安全）
- 命令行参数支持：
  - `--with-dynamic-security` - 开动态安全扫描
  - `--with-performance` - 开性能压测
  - `--with-compatibility` - 开兼容性矩阵
  - `--with-all-nonfunctional` - 全开
  - `--skip <dim>` - 跳过指定维度（必须登记到 release_gate_report.md）

**⭐ L3 用例生成策略（关键区别于 L1/L2）**：

L3 是发版门，**必须覆盖项目全部功能的全部路径**（正常 + 异常 + 边界 + 状态转换）。

**执行前先检查基线**：
```bash
python -c "
from qa_agent.core.state_manager import StateManager
sm = StateManager()
baseline = sm.load_baseline()
if baseline:
    print(f'已有基线: {baseline[\"total_cases\"]} 条用例 (建立于 {baseline[\"established_at\"]})')
else:
    print('首次 L3，将建立基线')
"
```

1. **用例库为空或极少（< 10 条）时**：
   - **不能**只看 git diff 生成增量用例
   - **必须**基于需求文档 + 源码结构做**完整覆盖**
   - Designer 应当：
     a) 阅读全部需求文档，提取所有功能点和验收标准
     b) 扫描项目源码结构，识别所有功能模块（页面/API/组件/服务）
     c) **逐模块生成用例**，每个模块根据复杂度：
        - 正常流程：覆盖每条业务路径（3-5 条）
        - 异常/边界：无效输入、超时、权限不足、并发等（5-10 条）
        - 状态转换：生命周期、多步操作的中间态（2-4 条）
        - 集成/E2E：完整用户操作流程（2-3 条）
     d) 确保需求追踪矩阵 100% 覆盖
     e) **生成覆盖矩阵**（模块 × 维度，输出到 qa/coverage_matrix.md）
     e2) **（可选）代码覆盖率 Gap 分析**：项目能产出 JaCoCo XML 时（如 Android `./gradlew jacocoTestReport`），用覆盖率缺口驱动补用例：
        ```bash
        # 解析 JaCoCo + 按类型分类未覆盖代码(主流程/边界/异常/防御性)
        python -m qa_agent.cli.main coverage \
          --jacoco-xml app/build/reports/jacoco/.../jacocoTestReport.xml \
          --source-root app/src/main/kotlin --gap-report
        ```
        优先为 🔴 主流程未覆盖 和 🟠 边界未覆盖 补用例（防御性代码可低优先）。
     f) **执行完成后建立基线**：
        ```python
        from qa_agent.core.state_manager import StateManager
        from datetime import datetime
        sm = StateManager()
        sm.save_baseline({
            'established_at': datetime.now().isoformat(),
            'established_by': '<run_id>',
            'total_cases': <用例总数>,
            'by_module': {<模块名>: <该模块用例数>, ...},
            'coverage_matrix': {<模块>: [<已覆盖维度>, ...], ...},
            'target_coverage': '主流程全覆盖 + 异常/边界 + 容错'
        })
        ```
   
   **用例数量不设固定上限，由模块复杂度决定**：
   - 简单模块（静态页面、配置页）：2-5 条
   - 中等模块（表单、列表、CRUD）：12-22 条
   - 复杂模块（支付、工作流、多角色协作）：30-50 条
   
   **参考基准**：`用例总数 ≈ 模块数 × 平均每模块 12-15 条`

2. **用例库已有足够用例时**：
   - **先检查基线是否需要刷新**（30 天/需求重大变更）
   - 如果基线仍有效：
     a) 对照基线的覆盖矩阵，只补充缺失的维度
     b) 不重新生成已有用例
     c) 执行全部用例（不限数量）
   - 如果需要刷新基线：
     a) 重新扫描需求文档和源码结构
     b) 补充新增功能模块的用例
     c) 更新覆盖矩阵
     d) 保存新基线

3. **影响面分析**：
   - L3 的影响面 = **全部用例**（不限 git diff 范围）
   - git diff 仅用于确定 Mutation 测试的范围
   - 不得因为 diff 为空就跳过测试

4. **Designer 必须做的检查**（L3 专属）：
   - 列出项目所有功能模块清单
   - 对照需求文档逐一确认覆盖
   - 输出覆盖矩阵（功能 × 测试层级）
   - 如果某模块用例 < 正常流程数量，必须补充

### L2/L4 覆盖策略

**L2 Module — 该模块全量覆盖**：
- 覆盖范围：该模块全部路径（正常 + 异常 + 边界 + 状态转换）+ 跨模块集成点
- 不测与该模块无关的功能
- 用例深度与 L3 相同，但范围限于指定模块
- 每个模块的用例标准同 L3（12-22 条/中等模块）

**L4 Bugfix — 受影响路径全量**：
- 覆盖范围：bug 复现用例 + 该 bug 影响的全部路径
- 如果 bug 影响了某个模块的核心流程，该模块全部路径都要验证
- 不仅验证"bug 修好了"，更要验证"没有破坏其他路径"

**L1 Feature — 该功能全路径 + 邻接**：
- 覆盖范围：该功能全部路径（正常 + 异常 + 边界）+ 邻接功能冒烟
- 邻接功能只跑 P0/P1 用例（不全量）

### `/qa retry`

重跑上次的 selection（修复后再验证）：
```bash
python -m qa_agent.cli.main retry
```

### `/qa resume`

恢复中断的 L3 运行：
```bash
python -m qa_agent.cli.main resume
```

读取 `qa/run/last.json` 的 checkpoint 字段，从 current_phase 继续执行。

### `/qa status`

```bash
python -m qa_agent.cli.main status
```

显示：
- 用例总数、按层级/优先级分布
- 最近一次运行结果
- Open bugs 数量
- 自动化覆盖率

### `/qa L0 [scope]`

单点 sanity，最快路径。仅跑受影响单测 + 关联冒烟。无需 Subagent 委派。

## 红线（强制）

引用规范 §5.5。任何一项触发即 Agent 违约：

1. 删除失败测试来伪造通过
2. 降低断言标准来伪造通过
3. 跳过失败测试但仍宣布完成
4. 没有运行测试就声称测试通过
5. 只运行程序不做断言
6. 修复后不做回归测试
7. **L0 / L1 / L4 模式的"PASS"作为发版依据**（必须 L3）
8. **Agent 自行降档运行模式**（必须用户显式指令）
9. **Agent 自行缩减用例选择范围**（用户可扩充，不可缩减）
10. **以"省成本"为由缩减执行集**

## 立即开始

1. 读取 `.qa.toml` 配置（如果存在）
2. 执行命令路由
3. 委派给 `qa-test-engineer` + `qa-gatekeeper` Subagent

---

## `/qa finalize` — 会话感知的状态同步 ⭐

### 用途

**在同一会话窗口里修复测试后，根据会话上下文同步真实进度与状态**，供下次 `/qa` 读到最新状态。

典型场景：
```
/qa module xxx  → 跑出 5 个 E2E 失败
  ↓ [同一会话] 你让 AI 逐个修代码 + 重跑验证
/qa finalize    → AI 根据会话上下文知道哪些已修复并重跑通过，
                  增量更新 last.json 的真实进度（不是凭空标 PASS）
```

### 核心原则（不可协商）

1. **verdict 由真实状态推导，不默认 PASS**
   - 还有未解决失败 → 至少 FAIL/CONDITIONAL，绝不 PASS
   - 全部验证通过 → 才可 PASS

2. **"改了代码" ≠ "测试通过"**（红线 6：修复后必须回归）
   - 只有**本会话重跑过且通过**的用例，才能从失败清单移除
   - 改了代码但没重跑的 E2E → **必须现场重跑**，不许凭"应该能过"标通过

3. **未验证的失败必须保留**，不许无条件清空失败清单

### 强制执行流程

**步骤 1：读取真实现状**
```bash
python -m qa_agent.cli.main finalize --check-only
```
读取 `qa/run/last.json` 的 `execution.failures`（当前未解决失败）、`selection.case_ids`（本次范围用例）。

**步骤 2：从会话上下文归类每个失败用例**

对 `execution.failures` 里每个用例，判断它在本会话的状态：

| 会话中的状态 | 处理 |
|---|---|
| 已改代码 + **已重跑且通过**（会话里有执行证据） | 计入"已验证通过"，可移除 |
| 已改代码 + **未重跑** | **现在必须重跑**（见步骤 3），跑过才算通过 |
| 未处理 | 保留为失败 |

**步骤 3：强制重跑"改了没跑"的用例**

对所有"改了代码但本会话没重跑"的 E2E：
- 按 qa-test-engineer.md 的"E2E 环境启动规则"启动环境
- 重跑对应测试，拿到真实结果
- 通过 → 归入已验证；仍失败 → 保留为失败
- **禁止跳过这一步直接标通过**（违反红线 6）

**步骤 4：推导 verdict + 重算 pass_rate**

```
已验证通过数 = 本会话重跑通过的用例数
剩余失败数   = execution.failures - 已验证通过
pass_rate    = (原通过 + 已验证通过) / 总数

verdict 推导：
- 剩余失败数 == 0 且全部有执行证据 → PASS
- 剩余失败仅 P2/P3 且有 waiver      → CONDITIONAL PASS
- 仍有 P0/P1 失败                   → FAIL
- 环境/数据不可用无法验证            → BLOCKED
```

**步骤 5：回写（用推导值，传 --passed-case）**

```bash
python -m qa_agent.cli.main finalize "<推导的verdict>" "<重算的pass_rate>" \
  --passed-case TC-A --passed-case TC-B \
  --reason "<本会话修复+重跑说明>"
```
- `--passed-case` 只传**本会话重跑验证通过**的用例 ID
- state_manager 会从失败清单**只移除这些**，未验证的自动保留
- 不传 verdict 时 CLI 会拒绝并提示（防凭空 PASS）

**步骤 6：输出推导依据给用户**

```
[QA finalize] 会话状态同步完成
本会话验证通过: TC-A, TC-B, TC-C（已重跑，有执行证据）
仍未解决:      TC-D (P0, 重跑仍失败), TC-E (未处理)
通过率:        10/12 → verdict=FAIL（仍有 P0 失败 TC-D）
```

### 命令格式

```bash
/qa finalize [verdict] [pass_rate] [--reason <原因>]
```

**参数**：
- `verdict`: **推导得出，不可省略，不默认 PASS**（省略时 CLI 拒绝并提示）
  - `PASS` — 全部验证通过（每项都有重跑证据）
  - `CONDITIONAL PASS` — 大部分通过，剩余失败仅 P2/P3 且已 waive
  - `FAIL` — 仍有 P0/P1 失败
  - `BLOCKED` — 环境/数据不可用，无法验证
- `pass_rate`: 重算的真实通过率，如 `"10/12 (83%)"`
- `--passed-case`: 本会话重跑验证通过的用例 ID（可多次），只移除这些
- `--reason`: 修复原因说明

### 示例

#### 示例 1：全部修复完成

```bash
/qa finalize PASS "40/40 (100%)" --reason "修复选择器 + Cloud API 重试"
```

**效果**：
```
[QA Agent] 手动修复完成，更新状态...
✅ last.json 已更新: status=completed, verdict=PASS
✅ baseline.json 已更新: completeness=full
✅ history.jsonl 已追加修复记录
✅ qa/release_gate_report.md 已更新

状态一致性检查: ✅ 通过
```

---

#### 示例 2：部分修复（接受 waivers）

```bash
/qa finalize "CONDITIONAL PASS" "38/40 (95%)" --reason "v53/v622 为 harness 问题，已创建 waivers.yml"
```

**效果**：
```
[QA Agent] 手动修复完成，更新状态...
✅ last.json 已更新: status=completed, verdict=CONDITIONAL PASS
✅ baseline.json 已更新: completeness=partial
✅ waivers.yml 已记录 2 个豁免用例
✅ history.jsonl 已追加修复记录

状态一致性检查: ✅ 通过
```

---

#### 示例 3：无参数（不再默认 PASS，进入推导提示）

```bash
/qa finalize
```

不再等价于 PASS。CLI 会读取 `last.json`，若仍有未解决失败则拒绝凭空判定，并提示：
```
⚠️  未提供 verdict，且 finalize 不再默认 PASS。
当前 last.json 仍有 N 个未解决失败:
  - TC-D: ...
请基于会话真实状态推导 verdict 后再传入，例如:
  qa finalize "CONDITIONAL PASS" "8/12 (67%)" --passed-case TC-A
```

正确做法是按上文"强制执行流程"推导后显式传值，而不是裸跑 `/qa finalize`。

---

### 实现逻辑

```python
from qa_agent.core.state_manager import StateManager

def handle_finalize(verdict='PASS', pass_rate='', reason=''):
    sm = StateManager()
    
    # 1. 检查当前状态
    consistency = sm.check_state_consistency()
    if not consistency['consistent']:
        print("[QA Agent] 检测到状态不一致:")
        for issue in consistency['issues']:
            print(f"  ⚠️ {issue}")
    
    # 2. 读取当前 last.json
    last_run = sm.load_last_run()
    if not last_run:
        print("❌ 错误: 没有找到上次执行记录 (last.json 不存在)")
        return
    
    run_id = last_run['run_id']
    mode = last_run['mode']
    
    # 3. 询问用户修复内容
    print(f"\n[QA Agent] 准备更新 {run_id} ({mode}) 的状态")
    print(f"  判定: {verdict}")
    print(f"  通过率: {pass_rate or '(未指定)'}")
    print(f"  原因: {reason or '(未指定)'}")
    
    if not confirm("确认更新？"):
        print("已取消")
        return
    
    # 4. 调用 finalize_after_manual_repair
    fixes_applied = {}
    if reason:
        fixes_applied['manual_repair_reason'] = reason
    
    sm.finalize_after_manual_repair(
        verdict=verdict,
        verdict_reason=reason or f'手动修复后判定为 {verdict}',
        remaining_failures=[],  # 可以从用户输入解析
        fixes_applied=fixes_applied,
        pass_rate=pass_rate,
    )
    
    # 5. 再次检查一致性
    consistency = sm.check_state_consistency()
    if consistency['consistent']:
        print("\n✅ 状态一致性检查: 通过")
    else:
        print("\n⚠️ 状态一致性检查: 仍有问题")
        for issue in consistency['issues']:
            print(f"  - {issue}")
    
    # 6. 显示摘要
    print(f"\n[QA Agent] 已更新文件:")
    print(f"  ✅ qa/run/last.json")
    print(f"  ✅ qa/run/baseline.json")
    print(f"  ✅ qa/run/history.jsonl")
    print(f"\n下次执行 /qa {mode.lower()} 将读取最新状态")
```

### 内部调用 API

**Python 代码中调用**（不通过命令）：

```python
from qa_agent.core.state_manager import StateManager

sm = StateManager()
sm.finalize_after_manual_repair(
    verdict='PASS',
    verdict_reason='经过 3 轮手动修复，全部用例通过',
    remaining_failures=[],
    fixes_applied={
        'selector_fix': '更新 6 个 page object helper',
        'cloud_api_fix': 'useCurrentProject fallback to localStorage',
        'seed_state_fix': 'consumed_stage_note 字段追加',
    },
    pass_rate='39/40 (97.5%)',
)
```

### 注意事项

1. **必须在测试执行后使用**
   - 如果 `qa/run/last.json` 不存在 → 报错
   - 确保上次执行记录可读

2. **不会重新执行测试**
   - 此命令只更新状态文件
   - 不会重跑任何用例
   - 假设用户已手动验证修复结果

3. **状态一致性检查**
   - 命令会自动检查 4 个文件是否同步
   - 如有不一致会警告但仍会继续

4. **与自动修复循环的区别**
   - 自动修复循环：Agent 自动修复 + 重跑 + 更新状态
   - `/qa finalize`：用户手动修复 + 手动更新状态

### 配合 waivers.yml 使用

**重要：waivers.yml 由 AI 自动生成草案，用户审核签字后生效**

#### 完整流程

```bash
# 1. L3 执行 → 修复循环 3 轮后仍有失败
/qa release
# Agent 自动生成 qa/waivers.draft.yml
# 输出: "AI 自动分析失败原因，生成 waivers 草案..."

# 2. 用户审核草案（AI 已填写大部分字段）
cat qa/waivers.draft.yml
# 内容示例:
# waivers:
#   - case_id: TC-rele-004
#     waiver_type: PHYSICAL_DEVICE
#     reason: 需要物理设备测试，CI 环境缺失
#     waived_by: TBD-BY-USER    # ← 用户必须填写
#     ...

# 3. 用户填写 waived_by 字段（签字）
# 用编辑器打开 qa/waivers.draft.yml
# 把 TBD-BY-USER 改为你的标识（邮箱/姓名）

# 4. 重命名为正式版本
mv qa/waivers.draft.yml qa/waivers.yml

# 5. 接受 CONDITIONAL PASS
/qa finalize "CONDITIONAL PASS" "38/40 (95%)" \
  --reason "v53/v622 已签字豁免，见 waivers.yml"
```

#### waivers.yml 由谁创建？

| 操作 | 责任方 | 说明 |
|---|---|---|
| **分析失败原因** | AI（Gatekeeper） | 看日志、错误堆栈、代码 |
| **分类 waiver 类型** | AI（Gatekeeper） | HARNESS_ISSUE / PHYSICAL_DEVICE 等 |
| **生成草案文件** | AI（Gatekeeper） | qa/waivers.draft.yml |
| **填写 case_id/reason** | AI（Gatekeeper） | 已自动填写 |
| **审核合理性** | 用户 | 检查 reason 是否准确 |
| **签字（waived_by）** | 用户 | 法律/合规要求 |
| **重命名为 .yml** | 用户 | 表示生效 |
| **执行 /qa finalize** | 用户 | 最终确认状态变更 |

#### 自动分类规则

AI 根据失败信息自动识别：

| 关键词 | 类型 | 可豁免 |
|---|---|---|
| `physical device` / `webview` | `PHYSICAL_DEVICE` | ✅ |
| `playwright` / `harness` | `HARNESS_ISSUE` | ✅ |
| `cloud api 500` / `504` | `INFRA_ISSUE` | ✅ |
| `llm timeout` | `INFRA_ISSUE` | ✅ |
| `timeout` / `flaky` | `FLAKY_TEST` | ⚠️ 需人工判断 |
| `typeerror` / `assertionerror` | `NOT_WAIVABLE` | ❌ 真实 bug |

#### 验证规则

`load_waivers()` 会自动验证：

```python
# qa_agent/core/gatekeeper.py
def load_waivers(self, waivers_path):
    # 1. 读取 qa/waivers.yml（不是 .draft）
    # 2. 验证每个 waiver 的 waived_by 不能是空 / TBD-BY-USER
    # 3. 缺少签字的 waiver 会被忽略
    # 4. 如果只有 .draft 文件 → 警告用户先签字
```

**禁止行为**：
- ❌ 用户手动从零创建 waivers.yml（应基于 AI 生成的草案）
- ❌ AI 自行签字 waived_by（必须用户确认）
- ❌ 直接修改 waivers.yml 跳过 .draft 流程

---

## 立即开始（真正的）

现在解析 `$ARGUMENTS` 并执行对应路由。如果 `$ARGUMENTS` 为空，显示帮助信息。
