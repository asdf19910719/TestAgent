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
- 子目录名优先：`prd/` → 需求，`design/architecture/` → 设计，`api/apis/` → API
- 文件名关键词：含 `requirement/prd/spec/需求/规格` → 需求；含 `design/architecture/技术方案/架构` → 设计
- 汇总文件优先：`*-all.md` / `*-overview.md` / 含 "总/全量/汇总" 中文名
- 无法分类的文档归入 `unclassified`，但仍作为参考材料

## 通用执行流程（L1/L2/L3/L4）

### 步骤 1：环境准备

1. 检查 `.qa-agent.yml` 是否存在
   - 不存在 → 提示用户 `/qa init`
2. 检查 GitNexus MCP 是否可用（`mcp__gitnexus__detect_changes`）
   - 不可用 + 配置 `impact_analysis: gitnexus` → 询问用户：
     a) 等待修复（默认）
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

输出 JSON 包含分类结果：
```json
{
  "primary": "doc/v2026-06-17-当前版本文档/产品需求文档.md",
  "design": "doc/v2026-06-17-当前版本文档/技术方案.md",
  "api": "doc/v2026-06-17-当前版本文档/接口设计.md",
  "specs": [...],
  "all_docs": [...],
  "unclassified": [...]
}
```

读取 `qa/run/selection.md` 获得用例列表，读取 `docs.primary` 获得主需求文档。

### 步骤 3：用户确认

打印预估给用户：

```text
将以 L1 模式执行
设计阶段: 增量补该功能用例
执行阶段: 选中 N 条用例（P0=a, P1=b, P2=c）
影响面来源: GitNexus / local
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
  - 需求文档: <路径>
  - 项目类型: <type>
  - 测试框架: <frameworks>
  - 用例库状态: <空 | N 条已有用例>
  
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

现在解析 `$ARGUMENTS` 并执行对应路由。如果 `$ARGUMENTS` 为空，显示帮助信息。
