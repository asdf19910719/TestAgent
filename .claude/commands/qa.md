---
description: AI Test Engineer Agent - 五档测试模式（L0/L1/L2/L3/L4）+ 引导式初始化
argument-hint: [init | feature <name> | bugfix <ref> | module <name> | release | retry | resume | status] [args...]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
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
| `feature <name>` | L1 | 一个功能开发完后跑测试 |
| `bugfix <ref>` | L4 | 修复缺陷后验证 |
| `module <name>` | L2 | 模块/迭代完成 |
| `release` | L3 | 发版前完整质量门 |
| `retry` | - | 重跑上次 selection |
| `resume` | - | 恢复中断的 L3 |
| `status` | - | 查看当前覆盖状态 |
| `L0` / `L0 <scope>` | L0 | 单点 sanity 快速验证 |

## 通用执行流程（L1/L2/L3/L4）

### 步骤 1：环境准备

1. 检查 `.qa-agent.yml` 是否存在
   - 不存在 → 提示用户 `/qa init`
2. 检查 GitNexus MCP 是否可用（`mcp__gitnexus__detect_changes`）
   - 不可用 + 配置 `impact_analysis: gitnexus` → 询问用户：
     a) 等待修复（默认）
     b) 切换到 `impact_analysis: local`
     c) 取消运行

### 步骤 2：影响面分析（机械工作 - 调用 Python 工具）

```bash
python -m qa_agent.cli.main prepare --mode <L?> --scope <scope>
```

这会输出：
- `qa/run/selection.md` - 选中的用例清单
- `qa/run/last.json` - 状态文件（含 phase, checkpoint）

读取 `qa/run/selection.md` 获得用例列表。

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

调用 Task 工具：
```
Task(
  subagent_type="qa-test-engineer",
  description="L<?> 设计用例 + 生成测试脚本",
  prompt="""
  阅读 .claude/agents/qa-test-engineer.md 中的指令。
  
  本次运行：
  - 模式: L<?>
  - 范围: <scope>
  - 已选用例 (qa/run/selection.md): <内容>
  - 需求文档: <路径>
  - 项目类型: <type>
  - 测试框架: <frameworks>
  
  按照规范完成：
  1. 增量补充用例（写入 qa/cases/<feature_id>/<id>.yml）
  2. 调用 Adapter 生成脚本（python -m qa_agent.cli.main scaffold --case <id>）
  3. 执行测试（python -m qa_agent.cli.main execute --selection ...）
  4. 收集失败 → qa/bugs/<id>.yml
  
  完成后告知"已完成 X 条用例设计 + 执行，Y 个失败"
  """
)
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
